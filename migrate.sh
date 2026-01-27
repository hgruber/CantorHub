#!/bin/bash

rm -f db.sqlite3
mv accounts/migrations/0002_import.py /tmp
rm -f accounts/migrations/0001_*

set -e
python manage.py makemigrations
mv /tmp/0002_import.py accounts/migrations/
python manage.py migrate
python manage.py runserver
