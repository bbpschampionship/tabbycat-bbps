import os
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import dj_database_url

# ==============================================================================
# Vercel (serverless WSGI) + Supabase Postgres
# ==============================================================================

if os.environ.get('TAB_DIRECTOR_EMAIL', ''):
    TAB_DIRECTOR_EMAIL = os.environ.get('TAB_DIRECTOR_EMAIL')

SECRET_KEY = os.environ['DJANGO_SECRET_KEY']

ALLOWED_HOSTS = ['*']
CSRF_TRUSTED_ORIGINS = [o for o in os.environ.get('CSRF_TRUSTED_ORIGINS', '').split(',') if o]
if os.environ.get('VERCEL_URL'):
    CSRF_TRUSTED_ORIGINS.append('https://' + os.environ['VERCEL_URL'])
if os.environ.get('VERCEL_PROJECT_PRODUCTION_URL'):
    CSRF_TRUSTED_ORIGINS.append('https://' + os.environ['VERCEL_PROJECT_PRODUCTION_URL'])

SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# Supabase transaction pooler (port 6543): no persistent connections and no
# server-side cursors, since each transaction may land on a different backend.
def _database_url():
    # Supabase's Vercel integration appends a "supa=" query param that libpq rejects.
    url = os.environ.get('DATABASE_URL') or os.environ['POSTGRES_URL']
    parts = urlsplit(url)
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query) if k != 'supa'])
    return urlunsplit(parts._replace(query=query))


DATABASES = {
    'default': dj_database_url.parse(_database_url(), conn_max_age=0),
}
DATABASES['default']['DISABLE_SERVER_SIDE_CURSORS'] = True

# Optional Redis (e.g. Upstash) for a cache shared across function instances;
# without it each instance keeps its own short-lived local cache.
REDIS_URL = os.environ.get('REDIS_URL') or os.environ.get('KV_URL')
if REDIS_URL:
    CACHES = {
        "default": {
            "BACKEND": "django_redis.cache.RedisCache",
            "LOCATION": REDIS_URL,
            "OPTIONS": {
                "CLIENT_CLASS": "django_redis.client.DefaultClient",
                "SOCKET_CONNECT_TIMEOUT": 5,
                "SOCKET_TIMEOUT": 10,
                "IGNORE_EXCEPTIONS": True,
            },
        },
    }

# No background worker on Vercel: websockets/channels stay in-process only.
CHANNEL_LAYERS = {
    "default": {"BACKEND": "channels.layers.InMemoryChannelLayer"},
}

# Static files are collected into public/static at build time and served by
# the Vercel CDN, so no manifest lookup is needed at runtime.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

DISABLE_SENTRY = True
DEBUG = bool(int(os.environ.get('DEBUG', 0)))

# Sessions must survive across function instances: core.py keeps them in the
# cache, which is per-instance memory here unless Redis is configured.
SESSION_ENGINE = ('django.contrib.sessions.backends.cached_db' if REDIS_URL
                  else 'django.contrib.sessions.backends.db')

# collectstatic writes straight into Vercel's CDN output directory.
STATIC_ROOT = os.path.join(os.path.dirname(BASE_DIR), 'public', 'static')
