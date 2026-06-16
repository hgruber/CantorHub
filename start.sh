#!/bin/bash

set -e

DEBUG="${DEBUG:-}"

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
