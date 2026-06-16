#!/bin/bash

set -e

DEBUG="${DEBUG:-}"

python manage.py migrate
python manage.py apply_initial_config

if [ -n "${EJABBERD_HOST:-}" ] && [ -n "${EJABBERD_BOT_JID:-}" ]; then
    echo "ejabberd_admin: syncing XMPP state..."
    python manage.py ejabberd_admin sync
    echo "ejabberd_bot: starting bot..."
    python manage.py ejabberd_bot &
fi

if [ "${DEBUG}" = "1" ]; then
    python manage.py runserver 0.0.0.0:8001
else
    python manage.py collectstatic --noinput
    /usr/sbin/nginx -g 'daemon on; master_process on;'
    gunicorn --bind 0.0.0.0:8001 --workers 3 config.wsgi:application
fi
