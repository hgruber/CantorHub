#!/bin/bash

rm -rf db.sqlite3 media intern/migrations/0002_add_filer.py
mv intern/migrations/0003_import.py .
set -e
./manage.py makemigrations intern --name add_filer
./manage.py migrate

mv 0003_import.py intern/migrations
./manage.py import_files --path portrait
./manage.py migrate
./manage.py collectstatic --noinput

/usr/sbin/nginx -g 'daemon on; master_process on;'
gunicorn --bind 0.0.0.0:8001 --workers 3 config.wsgi:application
