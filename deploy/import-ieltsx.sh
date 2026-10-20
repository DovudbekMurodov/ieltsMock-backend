#!/usr/bin/env bash
# Import the ieltsx.com scrape into the IELTS Mock database.
#
#   sudo bash /srv/ieltsmock/deploy/import-ieltsx.sh trial   # copy of the live DB, no files written
#   sudo bash /srv/ieltsmock/deploy/import-ieltsx.sh prod    # backup, then the real import
#   sudo bash /srv/ieltsmock/deploy/import-ieltsx.sh drop-trial
#
# Data: /srv/ieltsmock-import/data/{ieltsx,ieltsx-reading,ieltsx-writing,ieltsx-speaking}
set -euo pipefail

APP=/srv/ieltsmock
DATA=${DATA:-/srv/ieltsmock-import/data}
TRIAL_DB=ieltsmock_trial
MODE=${1:-}

run_manage() {  # manage.py as the app user; settings read .env themselves and never override these
    local db_url=$1; shift
    (cd "$APP" && sudo -u ieltsmock env DJANGO_SETTINGS_MODULE=config.settings.prod DATABASE_URL="$db_url" \
        nice "$APP/.venv/bin/python" "$APP/manage.py" "$@")
}

LIVE_URL=$(grep '^DATABASE_URL=' "$APP/.env" | cut -d= -f2- | tr -d '"'"'"'"'"'")
TRIAL_URL="${LIVE_URL%/*}/$TRIAL_DB"

counts() {
    sudo -u postgres psql -d "$1" -P pager=off -c "
        select 'reading/listening tests' as what, skill, count(*) from content_test where slug like 'ix-%' group by skill
        union all select 'questions', '', count(*) from content_question q join content_test t on t.id=q.test_id where t.slug like 'ix-%'
        union all select 'writing tasks', '', count(*) from writing_writingtask where slug like 'ix-%'
        union all select 'speaking topics', '', count(*) from speaking_speakingtopic where slug like 'ix-%'
        union all select 'audio assets', '', count(*) from content_audioasset;"
}

case "$MODE" in
trial)
    sudo -u postgres dropdb --if-exists "$TRIAL_DB"
    sudo -u postgres createdb -O ieltsmock "$TRIAL_DB"
    sudo -u postgres pg_dump ieltsmock | sudo -u postgres psql -q -d "$TRIAL_DB" >/dev/null
    echo "== importing into $TRIAL_DB (no files written)"
    run_manage "$TRIAL_URL" import_ieltsx --data "$DATA" --no-media 2>&1 | tee /tmp/import-ieltsx-trial.log | grep -vE '^\s+(listening|reading|writing|speaking): [0-9]+/' || true
    run_manage "$TRIAL_URL" publish_content > /tmp/publish-trial.log 2>&1 && echo "publish_content: ok ($(grep -c 'test ' /tmp/publish-trial.log) tests)"
    counts "$TRIAL_DB"
    echo "full log: /tmp/import-ieltsx-trial.log"
    ;;
prod)
    echo "== backup"
    sudo -u ieltsmock env DATABASE_URL="$LIVE_URL" bash "$APP/deploy/backup.sh" 2>&1 | grep -v OFFSITE || true
    echo "== importing into the live database"
    run_manage "$LIVE_URL" import_ieltsx --data "$DATA" 2>&1 | tee /tmp/import-ieltsx.log | grep -vE '^\s+(listening|reading|writing|speaking): [0-9]+/' || true
    run_manage "$LIVE_URL" publish_content > /tmp/publish.log 2>&1 && echo "publish_content: ok ($(grep -c 'test ' /tmp/publish.log) tests)"
    counts ieltsmock
    df -h / | tail -1
    ;;
drop-trial)
    sudo -u postgres dropdb --if-exists "$TRIAL_DB" && echo "dropped $TRIAL_DB"
    ;;
*)
    sed -n '2,8p' "$0"; exit 1
    ;;
esac
