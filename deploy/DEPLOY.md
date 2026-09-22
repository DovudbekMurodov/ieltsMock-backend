# Deploying to the droplet

Assumes Ubuntu with PostgreSQL 17, nginx and Python 3.12 available.

## Two ways to run this

The full setup below assumes a hostname and a certificate. A droplet with
neither can still run the API over plain HTTP on its IP — see
[Running on a bare IP](#running-on-a-bare-ip) for what changes, and read the
mixed-content warning there before pointing a deployed SPA at it.

## Before anything else: a hostname

The SPA is served over HTTPS, so a call to `http://<droplet-ip>/api` is
**blocked by the browser as mixed content**, and Let's Encrypt will not issue a
certificate for a bare IP. The API therefore needs a hostname before any of
this can be tested end to end.

`*.duckdns.org` is on the Public Suffix List, so each subdomain gets its own
Let's Encrypt rate-limit bucket. `nip.io` and `sslip.io` are not, so their
shared bucket is routinely exhausted — avoid them. A real domain is better
still, and moving to one later is a DNS change plus two env vars.

```bash
sudo certbot --nginx -d api.example.duckdns.org
```

## Running on a bare IP

No hostname yet. The API answers on `http://<droplet-ip>/` and nothing is
encrypted, so treat it as a staging step, not a destination.

**What this cannot do.** A browser refuses a plain-`http` call made from an
`https` page, so a Vercel-hosted SPA cannot reach this API — the request is
blocked as mixed content before it leaves the browser and no CORS header can
unblock it. Until a certificate exists, exercise the API from a frontend served
over `http` (`npm run dev` on `http://localhost:5173`), from `curl`, or from the
dashboard directly. Credentials also cross the network in clear text, so use
throwaway passwords and do not load real student data yet.

Follow [One-time setup](#one-time-setup) unchanged, then differ in three places.

**`.env`** — the host is the IP, both origins are `http`, and TLS is off:

```
DJANGO_SECRET_KEY=<50+ random characters>
DJANGO_DEBUG=False
DJANGO_SECURE_SSL=False
DJANGO_ALLOWED_HOSTS=<droplet-ip>
DATABASE_URL=postgres://ieltsmock:<password>@localhost/ieltsmock
CORS_ALLOWED_ORIGINS=http://localhost:5173
CSRF_TRUSTED_ORIGINS=http://<droplet-ip>
```

`DJANGO_SECURE_SSL=False` is what makes this work at all: it drops the https
redirect, HSTS, and the `Secure` flag on the session and CSRF cookies. Left at
its default the redirect loops forever, and the dashboard cannot log in because
the browser discards a `Secure` cookie arriving over `http`.

**nginx** — use the plain-HTTP config and skip certbot:

```bash
sudo cp deploy/nginx-ip.conf /etc/nginx/sites-available/ieltsmock
sudo ln -sf /etc/nginx/sites-available/ieltsmock /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default   # it also claims default_server
sudo nginx -t && sudo systemctl reload nginx
```

Services, releases and timers are identical to the sections below.

**Checks.** `check --deploy` reports the security settings this mode turns off —
`SECURE_SSL_REDIRECT`, `SECURE_HSTS_SECONDS`, `SESSION_COOKIE_SECURE`,
`CSRF_COOKIE_SECURE`. Those four are expected here; any other warning is not.

```bash
curl -sS http://<droplet-ip>/healthz
```

**Moving to a hostname.** Point the DNS record at the droplet, then:

```bash
sudo cp deploy/nginx.conf /etc/nginx/sites-available/ieltsmock
sudo editor /etc/nginx/sites-available/ieltsmock   # server_name
sudo certbot --nginx -d api.example.duckdns.org
sudo -u ieltsmock editor /srv/ieltsmock/.env       # drop DJANGO_SECURE_SSL,
                                                   # host + origins to https
sudo systemctl restart ieltsmock && sudo systemctl reload nginx
```

HSTS only starts counting once a browser sees it over https, so switching in
this direction is safe. Switching back is not: a browser that has seen the HSTS
header refuses plain http for a year.

## One-time setup

```bash
sudo adduser --system --group --home /srv/ieltsmock ieltsmock
sudo -u postgres createuser ieltsmock --pwprompt
sudo -u postgres createdb ieltsmock --owner=ieltsmock

sudo -u ieltsmock git clone https://github.com/DovudbekMurodov/ieltsMock-backend.git /srv/ieltsmock
cd /srv/ieltsmock
sudo -u ieltsmock python3.12 -m venv .venv
sudo -u ieltsmock .venv/bin/pip install -r requirements/prod.txt

sudo -u ieltsmock cp .env.example .env
sudo -u ieltsmock editor .env      # see below
sudo chmod 600 .env
```

`.env` must set, at minimum:

```
DJANGO_SECRET_KEY=<50+ random characters>
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=api.example.duckdns.org
DATABASE_URL=postgres://ieltsmock:<password>@localhost/ieltsmock
CORS_ALLOWED_ORIGINS=https://ieltsmock.vercel.app
CORS_ALLOWED_ORIGIN_REGEXES=^https://ieltsmock-[a-z0-9-]+\.vercel\.app$
CSRF_TRUSTED_ORIGINS=https://api.example.duckdns.org
REDIS_URL=redis://127.0.0.1:6379/0    # optional; falls back to the database cache
SENTRY_DSN=                            # optional
OFFSITE_TARGET=                        # where backups are copied to
```

`config/settings/prod.py` resolves the required ones at import time, so a
missing variable fails at boot rather than on the first request that needs it.

## Services

```bash
sudo cp deploy/gunicorn.service          /etc/systemd/system/ieltsmock.service
sudo cp deploy/ieltsmock-rollup.*        /etc/systemd/system/
sudo cp deploy/ieltsmock-backup.*        /etc/systemd/system/
sudo cp deploy/nginx.conf                /etc/nginx/sites-available/ieltsmock
sudo ln -sf /etc/nginx/sites-available/ieltsmock /etc/nginx/sites-enabled/

sudo systemctl daemon-reload
sudo systemctl enable --now ieltsmock ieltsmock-rollup.timer ieltsmock-backup.timer
sudo nginx -t && sudo systemctl reload nginx
```

`X-Forwarded-Proto` in the nginx config is not optional: `SECURE_PROXY_SSL_HEADER`
reads it, and without it Django believes every request arrived over plain HTTP
and redirect-loops.

## Releasing

```bash
cd /srv/ieltsmock
sudo -u ieltsmock git pull
sudo -u ieltsmock .venv/bin/pip install -r requirements/prod.txt
sudo -u ieltsmock .venv/bin/python manage.py migrate
sudo -u ieltsmock .venv/bin/python manage.py collectstatic --noinput
sudo systemctl reload ieltsmock
```

The dashboard CSS is committed, so no Node is needed on the droplet.

## Checks

```bash
DJANGO_SETTINGS_MODULE=config.settings.prod .venv/bin/python manage.py check --deploy
curl -sS https://api.example.duckdns.org/healthz
systemctl list-timers 'ieltsmock-*'
```

`check --deploy` must report no issues before the first release.

## Restoring

A backup that has never been restored is a guess. Roughly monthly:

```bash
sudo -u postgres createdb ieltsmock_restore_test
pg_restore --clean --no-owner -d postgres://.../ieltsmock_restore_test backups/db-<stamp>.dump
sudo -u postgres dropdb ieltsmock_restore_test
```

Backups that never leave the droplet do not survive the droplet, so set
`OFFSITE_TARGET`. `backup.sh` warns on every run while it is unset.
