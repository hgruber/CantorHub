#!/bin/bash

rm -rf db.sqlite3 media intern/migrations/0002_add_filer.py
mv intern/migrations/0003_import.py .
set -e
./manage.py makemigrations intern --name add_filer
./manage.py migrate

mv 0003_import.py intern/migrations
./manage.py import_files --path Avatare
./manage.py migrate
./manage.py index_files
./manage.py collectstatic --noinput

# XMPP/ejabberd integration
if [ "${EJABBERD_ENABLED}" = "1" ]; then
    echo "ejabberd_sync: syncing XMPP state..."
    ./manage.py ejabberd_sync --sync
    echo "ejabberd_bot: starting bot..."
    ./manage.py ejabberd_bot &
fi

/usr/sbin/nginx -g 'daemon on; master_process on;'
gunicorn --bind 0.0.0.0:8001 --workers 3 config.wsgi:application
