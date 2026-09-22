#!/usr/bin/env bash
# Database and media backup.
#
# A backup that has never been restored is a guess, so this also prints the
# restore command every night -- it should be run against a scratch database
# from time to time.
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/srv/ieltsmock/backups}"
MEDIA_DIR="${MEDIA_DIR:-/srv/ieltsmock/media}"
KEEP_DAYS="${KEEP_DAYS:-14}"
STAMP="$(date +%Y%m%d-%H%M%S)"

mkdir -p "$BACKUP_DIR"

# DATABASE_URL comes from the EnvironmentFile.
pg_dump --no-owner --format=custom "$DATABASE_URL" \
    > "$BACKUP_DIR/db-$STAMP.dump"

if [ -d "$MEDIA_DIR" ]; then
    tar -czf "$BACKUP_DIR/media-$STAMP.tar.gz" -C "$(dirname "$MEDIA_DIR")" "$(basename "$MEDIA_DIR")"
fi

# Droplet disks fail as a unit, so a backup that never leaves the box is not a
# backup. Set OFFSITE_TARGET to an rsync/rclone destination.
if [ -n "${OFFSITE_TARGET:-}" ]; then
    rsync -a --delete "$BACKUP_DIR/" "$OFFSITE_TARGET"
else
    echo "WARNING: OFFSITE_TARGET is unset — backups live only on this droplet." >&2
fi

find "$BACKUP_DIR" -name 'db-*.dump' -mtime "+$KEEP_DAYS" -delete
find "$BACKUP_DIR" -name 'media-*.tar.gz' -mtime "+$KEEP_DAYS" -delete

echo "backed up to $BACKUP_DIR/db-$STAMP.dump"
echo "restore with: pg_restore --clean --no-owner -d \$DATABASE_URL $BACKUP_DIR/db-$STAMP.dump"
