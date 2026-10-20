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

# Media is a dated snapshot, hard-linked against the previous one: audio and
# images never change once uploaded (audio is content-addressed), so a nightly
# tarball of gigabytes of identical files would fill the disk within days.
# Each snapshot is still a complete copy you can restore from on its own.
if [ -d "$MEDIA_DIR" ]; then
    PREVIOUS="$(ls -1d "$BACKUP_DIR"/media-*/ 2>/dev/null | tail -n 1 || true)"
    rsync -a ${PREVIOUS:+--link-dest="$PREVIOUS"} "$MEDIA_DIR/" "$BACKUP_DIR/media-$STAMP/"
    touch "$BACKUP_DIR/media-$STAMP"  # rsync copies the source's mtime; retention needs the snapshot's own
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
find "$BACKUP_DIR" -mindepth 1 -maxdepth 1 -type d -name 'media-*' -mtime "+$KEEP_DAYS" -exec rm -rf {} +

echo "backed up to $BACKUP_DIR/db-$STAMP.dump"
echo "restore with: pg_restore --clean --no-owner -d \$DATABASE_URL $BACKUP_DIR/db-$STAMP.dump"
