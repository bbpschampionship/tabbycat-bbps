import os
import sys

# Tabbycat's Django project lives in tabbycat/ (settings module is "settings").
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tabbycat'))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "settings")

from django.core.wsgi import get_wsgi_application  # noqa: E402

app = get_wsgi_application()
