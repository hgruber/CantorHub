#!/bin/bash

set -e

DEBUG="${DEBUG:-}"

DB_HOST="${DB_HOST:-}"

if [ -n "$DB_HOST" ]; then
    echo "Detected DB_HOST=$DB_HOST; using MySQL."
    echo "Dropping all tables to start fresh..."
    python manage.py shell -c "
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
mv intern/migrations/0003_import.py /tmp || true

python manage.py makemigrations intern --name add_filer
python manage.py migrate

mv /tmp/0003_import.py intern/migrations || true
python manage.py import_files --path Avatare
python manage.py migrate
python manage.py index_files &
(python manage.py thumbnail_files && python manage.py filer_check --delete-orphans --noinput) &

python manage.py ejabberd_admin sync
python manage.py ejabberd_bot &

if [ "${DEBUG}" = "1" ]; then
    python manage.py runserver 0.0.0.0:8001
else
    python manage.py collectstatic --noinput
    /usr/sbin/nginx -g 'daemon on; master_process on;'
    gunicorn --bind 0.0.0.0:8001 --workers 3 config.wsgi:application
fi
