#!/bin/bash

rm -f db.sqlite3 media accounts/migrations/0002_add_filer.py
mv accounts/migrations/0003_import.py /tmp
set -e
python manage.py makemigrations accounts --name add_filer
mv /tmp/0003_import.py accounts/migrations
python manage.py migrate
python manage.py runserver
