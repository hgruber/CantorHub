#!/bin/bash

rm -rf db.sqlite3 media intern/migrations/0002_add_filer.py
mv intern/migrations/0003_import.py /tmp
set -e
python manage.py makemigrations intern --name add_filer
python manage.py migrate

mv /tmp/0003_import.py intern/migrations
python manage.py import_files --path portrait
python manage.py migrate

python manage.py runserver
