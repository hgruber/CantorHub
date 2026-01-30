#!/bin/bash

rm -f db.sqlite3 media accounts/migrations/0002_add_filer.py
mv accounts/migrations/0003_import.py /tmp
set -e
python manage.py makemigrations accounts --name add_filer
python manage.py migrate

mv /tmp/0003_import.py accounts/migrations
python manage.py import_files --path portrait
python manage.py migrate

python manage.py runserver
