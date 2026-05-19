#!/bin/bash

set -e

DB_HOST="${DB_HOST:-}"

if [ -n "$DB_HOST" ]; then
    echo "Detected DB_HOST=$DB_HOST; using MySQL."
    echo "Dropping all tables to start fresh..."
    ./manage.py shell -c "
from django.db import connection
with connection.cursor() as c:
    c.execute('SET FOREIGN_KEY_CHECKS = 0')
    c.execute('SHOW TABLES')
    tables = [row[0] for row in c.fetchall()]
    for t in tables:
        c.execute(f'DROP TABLE IF EXISTS {t}')
    c.execute('SET FOREIGN_KEY_CHECKS = 1')
print('Database cleared.')
"
else
    echo "No DB_HOST set; using SQLite."
    rm -rf db.sqlite3 media
fi

rm -rf intern/migrations/0002_add_filer.py
mv intern/migrations/0003_import.py . || true

./manage.py makemigrations intern --name add_filer
./manage.py migrate

mv 0003_import.py intern/migrations || true
./manage.py import_files --path Avatare
./manage.py migrate
./manage.py apply_initial_config
./manage.py index_files &
./manage.py thumbnail_files &
./manage.py collectstatic --noinput

# XMPP/ejabberd integration — read from DB (set via initial.sh or admin)
EJABBERD_ENABLED=$(./manage.py shell -c "from intern.app_settings import get_config_bool; print('1' if get_config_bool('EJABBERD_ENABLED') else '0')")
if [ "${EJABBERD_ENABLED}" = "1" ]; then
    echo "ejabberd_sync: syncing XMPP state..."
    ./manage.py ejabberd_sync --sync
    echo "ejabberd_bot: starting bot..."
    ./manage.py ejabberd_bot &
fi

/usr/sbin/nginx -g 'daemon on; master_process on;'
gunicorn --bind 0.0.0.0:8001 --workers 3 config.wsgi:application
