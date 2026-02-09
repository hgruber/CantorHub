#!/bin/bash

/usr/sbin/nginx -g 'daemon on; master_process on;'
gunicorn --bind 0.0.0.0:8001 --workers 3 config.wsgi:application
