#!/usr/bin/env bash
#
# One-shot provisioning for a fresh Ubuntu 24.04 droplet that has no hostname.
# Brings up PostgreSQL, gunicorn and nginx, obtains a Let's Encrypt certificate
# for the droplet's own IP, and leaves the API answering on https://<ip>/.
#
#   sudo bash deploy/bootstrap-ip.sh [ip] [admin-email]
#
# Re-running it is safe: every step checks for its own result first, so it
# doubles as the repair path when one step failed and you fixed the cause.
#
# Set STAGING=1 for the first run against a new droplet. Let's Encrypt counts
# failed authorisations against an hourly limit, and a firewall or DNS mistake
# discovered on the staging endpoint costs nothing.

set -euo pipefail

REPO="${REPO:-https://github.com/DovudbekMurodov/ieltsMock-backend.git}"
APP_DIR=/srv/ieltsmock
APP_USER=ieltsmock
ACME_ROOT=/var/www/acme
STAGING="${STAGING:-0}"

log() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
die() { printf '\n\033[1;31m!!! %s\033[0m\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "run with sudo"

# ---------------------------------------------------------------- IP address
IP="${1:-}"
if [ -z "$IP" ]; then
    # The address on the default route, not whatever an echo service reports:
    # behind NAT those differ, and the certificate has to match the address
    # nginx actually answers on.
    IP=$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{print $7; exit}')
fi
[ -n "$IP" ] || die "could not determine the public IP; pass it as the first argument"
case "$IP" in
    10.*|192.168.*|172.1[6-9].*|172.2[0-9].*|172.3[01].*|127.*)
        die "$IP is a private address. Let's Encrypt validates from the public internet and cannot reach it." ;;
esac
ADMIN_EMAIL="${2:-}"
log "Provisioning for $IP"

# ---------------------------------------------------------------------- swap
# The smallest droplets ship with 1 GB and no swap, which is enough to run this
# but not enough to survive a pip resolve and a migration at the same time. The
# OOM killer picks postgres surprisingly often, and a half-applied migration is
# a worse problem than a slow one.
if [ -z "$(swapon --show)" ] && [ ! -f /swapfile ]; then
    log "Adding 2G swap"
    fallocate -l 2G /swapfile || dd if=/dev/zero of=/swapfile bs=1M count=2048 status=none
    chmod 600 /swapfile
    mkswap -q /swapfile
    swapon /swapfile
    grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
    # Default 60 is tuned for desktops; on a small server it evicts working set
    # that is about to be used again.
    sysctl -qw vm.swappiness=10
    grep -q '^vm.swappiness' /etc/sysctl.conf || echo 'vm.swappiness=10' >> /etc/sysctl.conf
fi

# ------------------------------------------------------------------ packages
log "Installing packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq \
    postgresql nginx git curl ca-certificates ufw \
    python3.12 python3.12-venv python3.12-dev build-essential libpq-dev snapd

# Ubuntu's apt certbot is far too old to know --ip-address. The snap tracks
# upstream and refreshes itself, which also matters for a 160-hour certificate.
if ! snap list certbot >/dev/null 2>&1; then
    snap install --classic certbot
    ln -sf /snap/bin/certbot /usr/bin/certbot
fi
snap refresh certbot >/dev/null 2>&1 || true

CERTBOT_VER=$(certbot --version 2>&1 | awk '{print $2}')
# --ip-address landed in 5.3 and webroot support for it in 5.4.
if [ "$(printf '%s\n5.4.0\n' "$CERTBOT_VER" | sort -V | head -1)" != "5.4.0" ]; then
    die "certbot $CERTBOT_VER is too old for IP certificates; 5.4 or newer is required"
fi
log "certbot $CERTBOT_VER"

# ------------------------------------------------------------------ firewall
ufw allow OpenSSH >/dev/null
ufw allow 80/tcp  >/dev/null
ufw allow 443/tcp >/dev/null
ufw --force enable >/dev/null

# --------------------------------------------------------------- app account
id -u "$APP_USER" >/dev/null 2>&1 || \
    adduser --system --group --home "$APP_DIR" "$APP_USER"

# -------------------------------------------------------------------- source
log "Fetching source"
if [ -d "$APP_DIR/.git" ]; then
    sudo -u "$APP_USER" git -C "$APP_DIR" fetch --quiet origin
    sudo -u "$APP_USER" git -C "$APP_DIR" reset --hard --quiet origin/main
else
    # adduser --home already created the directory, and git refuses to clone
    # into a non-empty one.
    rm -rf "${APP_DIR:?}"/..?* "${APP_DIR:?}"/.[!.]* "${APP_DIR:?}"/* 2>/dev/null || true
    sudo -u "$APP_USER" git clone --quiet "$REPO" "$APP_DIR"
fi

log "Installing Python dependencies"
[ -x "$APP_DIR/.venv/bin/python" ] || sudo -u "$APP_USER" python3.12 -m venv "$APP_DIR/.venv"
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install --quiet --upgrade pip
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install --quiet -r "$APP_DIR/requirements/prod.txt"

# ------------------------------------------------------------------ database
log "Configuring PostgreSQL"
systemctl enable --now postgresql
if ! sudo -u postgres psql -tAc "select 1 from pg_roles where rolname='$APP_USER'" | grep -q 1; then
    DB_PASS=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')
    sudo -u postgres psql -qc "create role $APP_USER login password '$DB_PASS'"
    echo "$DB_PASS" > /root/.ieltsmock-db-password
    chmod 600 /root/.ieltsmock-db-password
else
    [ -f /root/.ieltsmock-db-password ] || \
        die "role $APP_USER exists but /root/.ieltsmock-db-password is gone; reset it and update $APP_DIR/.env by hand"
    DB_PASS=$(cat /root/.ieltsmock-db-password)
fi
sudo -u postgres psql -tAc "select 1 from pg_database where datname='$APP_USER'" | grep -q 1 || \
    sudo -u postgres createdb "$APP_USER" --owner="$APP_USER"

# ----------------------------------------------------------------------- env
if [ ! -f "$APP_DIR/.env" ]; then
    log "Writing .env"
    SECRET=$(python3 -c 'import secrets; print(secrets.token_urlsafe(64))')
    cat > "$APP_DIR/.env" <<ENV
DJANGO_SECRET_KEY=$SECRET
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=$IP
DATABASE_URL=postgres://$APP_USER:$DB_PASS@localhost/$APP_USER

# Flipped to True by this script once the certificate is in place.
DJANGO_SECURE_SSL=False
# Stays 0 while the host is an IP: the certificate lives 160 hours, and an HSTS
# pin would outlive a stalled renewal by a year with no way to undo it.
DJANGO_HSTS_SECONDS=0

CSRF_TRUSTED_ORIGINS=https://$IP
CORS_ALLOWED_ORIGINS=http://localhost:5173
CORS_ALLOWED_ORIGIN_REGEXES=
ENV
    chown "$APP_USER:$APP_USER" "$APP_DIR/.env"
    chmod 600 "$APP_DIR/.env"
else
    log "Keeping existing .env"
fi

# ------------------------------------------------------- nginx, http-only first
# The certificate does not exist yet, so a config referencing it would stop
# nginx from starting and there would be nothing to serve the challenge with.
log "Starting nginx on port 80"
mkdir -p "$ACME_ROOT/.well-known/acme-challenge"
chown -R www-data:www-data "$ACME_ROOT"
rm -f /etc/nginx/sites-enabled/default
sed "s|root /var/www/acme;|root $ACME_ROOT;|" "$APP_DIR/deploy/nginx-ip.conf" \
    > /etc/nginx/sites-available/ieltsmock
ln -sf /etc/nginx/sites-available/ieltsmock /etc/nginx/sites-enabled/ieltsmock
nginx -t
systemctl enable --now nginx
systemctl reload nginx

# ----------------------------------------------------------------- certificate
log "Requesting certificate for $IP"
CERTBOT_ARGS=(certonly --non-interactive --agree-tos
              --preferred-profile shortlived
              --webroot --webroot-path "$ACME_ROOT"
              --ip-address "$IP")
[ "$STAGING" = "1" ] && CERTBOT_ARGS+=(--staging)
if [ -n "$ADMIN_EMAIL" ]; then
    CERTBOT_ARGS+=(-m "$ADMIN_EMAIL")
else
    CERTBOT_ARGS+=(--register-unsafely-without-email)
fi
certbot "${CERTBOT_ARGS[@]}"

[ -f "/etc/letsencrypt/live/$IP/fullchain.pem" ] || die "certbot reported success but no certificate is on disk"

# ------------------------------------------------------------- nginx with TLS
log "Switching nginx to TLS"
sed "s|__IP__|$IP|g" "$APP_DIR/deploy/nginx-ip-tls.conf" > /etc/nginx/sites-available/ieltsmock
sed -i 's|root /var/www/acme;|root '"$ACME_ROOT"';|' /etc/nginx/sites-available/ieltsmock
nginx -t
systemctl reload nginx

# Real TLS now terminates in front of Django, so the redirect and the Secure
# cookie flags are correct. HSTS stays off; see the note in .env.
sed -i 's/^DJANGO_SECURE_SSL=.*/DJANGO_SECURE_SSL=True/' "$APP_DIR/.env"

# ------------------------------------------------------------------- renewals
# The certbot snap ships a twice-daily timer, which leaves under three attempts
# inside the window a 160-hour certificate gives you. Four a day is cheap:
# certbot exits immediately when ARI says renewal is not due yet.
mkdir -p /etc/systemd/system/snap.certbot.renew.timer.d
cat > /etc/systemd/system/snap.certbot.renew.timer.d/override.conf <<'TIMER'
[Timer]
OnCalendar=
OnCalendar=*-*-* 0,6,12,18:17:00
RandomizedDelaySec=1800
TIMER

mkdir -p /etc/letsencrypt/renewal-hooks/deploy
cat > /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh <<'HOOK'
#!/bin/sh
# nginx keeps the certificate it read at start-up, so a renewal that nothing
# reloads changes nothing that clients see.
systemctl reload nginx
HOOK
chmod +x /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh

# ------------------------------------------------------------------- services
log "Installing services"
install -m 644 "$APP_DIR/deploy/gunicorn.service" /etc/systemd/system/ieltsmock.service

# The committed unit asks for 3 workers, which is right for the 2 GB box it was
# written against and roughly 150 MB too many for a 1 GB one once postgres has
# taken its share. Size it from the RAM actually present rather than editing a
# file that is correct elsewhere.
MEM_MB=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)
WORKERS=$(( MEM_MB / 350 ))
[ "$WORKERS" -lt 2 ] && WORKERS=2
MAX_WORKERS=$(( $(nproc) * 2 + 1 ))
[ "$WORKERS" -gt "$MAX_WORKERS" ] && WORKERS=$MAX_WORKERS
log "Sizing gunicorn to $WORKERS workers (${MEM_MB}MB RAM, $(nproc) vCPU)"
mkdir -p /etc/systemd/system/ieltsmock.service.d
cat > /etc/systemd/system/ieltsmock.service.d/workers.conf <<UNIT
[Service]
ExecStart=
ExecStart=$APP_DIR/.venv/bin/gunicorn config.wsgi:application \\
    --bind unix:/run/ieltsmock/gunicorn.sock \\
    --workers $WORKERS \\
    --timeout 60 \\
    --max-requests 1000 \\
    --max-requests-jitter 100 \\
    --access-logfile - \\
    --error-logfile -
UNIT
install -m 644 "$APP_DIR/deploy/ieltsmock-rollup.service" /etc/systemd/system/
install -m 644 "$APP_DIR/deploy/ieltsmock-rollup.timer"   /etc/systemd/system/
install -m 644 "$APP_DIR/deploy/ieltsmock-backup.service" /etc/systemd/system/
install -m 644 "$APP_DIR/deploy/ieltsmock-backup.timer"   /etc/systemd/system/

log "Migrating and collecting static files"
sudo -u "$APP_USER" mkdir -p "$APP_DIR/media"
run_manage() {
    sudo -u "$APP_USER" env DJANGO_SETTINGS_MODULE=config.settings.prod \
        "$APP_DIR/.venv/bin/python" "$APP_DIR/manage.py" "$@"
}
run_manage migrate --noinput
run_manage collectstatic --noinput
# Only used when REDIS_URL is unset, and harmless when the table already exists.
run_manage createcachetable

systemctl daemon-reload
systemctl enable --now ieltsmock ieltsmock-rollup.timer ieltsmock-backup.timer
systemctl restart ieltsmock
systemctl reload-or-restart snap.certbot.renew.timer 2>/dev/null || true

# --------------------------------------------------------------------- verify
log "Verifying"
sleep 3
run_manage check --deploy || true
curl -fsS "https://$IP/healthz" && echo

cat <<DONE

  API is up:   https://$IP/
  health:      https://$IP/healthz
  dashboard:   https://$IP/dashboard/
  admin:       https://$IP/admin/
  API docs:    https://$IP/api/v1/docs/

  Create the first staff account:
    sudo -u $APP_USER env DJANGO_SETTINGS_MODULE=config.settings.prod \\
      $APP_DIR/.venv/bin/python $APP_DIR/manage.py createsuperuser

  The certificate expires in 160 hours and renews unattended. Confirm the
  timer is armed before you rely on it:
    systemctl list-timers snap.certbot.renew.timer

DONE
