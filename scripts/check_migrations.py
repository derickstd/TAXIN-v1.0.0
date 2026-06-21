import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
django.setup()
from django.db import connection
c = connection.cursor()
c.execute("select app,name,applied from django_migrations where app='core' order by name")
rows = c.fetchall()
for r in rows:
    print(r)
