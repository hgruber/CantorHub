#!/bin/bash

set -e

DEBUG="${DEBUG:-}"
DB_HOST="${DB_HOST:-}"

if [ -n "$DB_HOST" ]; then
    echo "Detected DB_HOST=$DB_HOST; using MySQL."
else
    echo "No DB_HOST set; using SQLite."
fi

python manage.py migrate
python manage.py apply_initial_config

python manage.py ejabberd_admin sync
python manage.py ejabberd_bot &

if [ "${DEBUG}" = "1" ]; then
    python manage.py runserver 0.0.0.0:8001
else
    python manage.py collectstatic --noinput
    /usr/sbin/nginx -g 'daemon on; master_process on;'
    gunicorn --bind 0.0.0.0:8001 --workers 3 config.wsgi:application
fi
