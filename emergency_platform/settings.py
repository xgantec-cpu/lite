import base64
import hashlib
import os
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from django.contrib.auth.hashers import make_password
from django.core.exceptions import ImproperlyConfigured


BASE_DIR = Path(__file__).resolve().parent.parent
DEBUG = os.getenv("DJANGO_DEBUG", "1") == "1"
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured("DJANGO_SECRET_KEY must be set when DJANGO_DEBUG=0.")
    SECRET_KEY = "django-insecure-change-this-in-production"
FIELD_ENCRYPTION_KEY = os.getenv("DJANGO_FIELD_ENCRYPTION_KEY")
if not FIELD_ENCRYPTION_KEY:
    if not DEBUG:
        raise ImproperlyConfigured("DJANGO_FIELD_ENCRYPTION_KEY must be set when DJANGO_DEBUG=0.")
    FIELD_ENCRYPTION_KEY = base64.urlsafe_b64encode(
        hashlib.sha256(f"{SECRET_KEY}:field-encryption".encode()).digest()
    ).decode()
ALLOWED_HOSTS = [host.strip() for host in os.getenv("DJANGO_ALLOWED_HOSTS", "").split(",") if host.strip()]
if DEBUG and not ALLOWED_HOSTS:
    ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]", "testserver", " helpug.pythonanywhere.com "]
if not DEBUG and not ALLOWED_HOSTS:
    raise ImproperlyConfigured("DJANGO_ALLOWED_HOSTS must be set when DJANGO_DEBUG=0.")
CSRF_TRUSTED_ORIGINS = [
    origin.strip().rstrip("/")
    for origin in os.getenv("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",")
    if origin.strip()
]
TRUST_PROXY_HEADERS = os.getenv("DJANGO_TRUST_PROXY_HEADERS", "0") == "1"

INSTALLED_APPS = [
    "daphne",
    "channels",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "incidents",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "incidents.middleware.WorkspaceInactivityMiddleware",
    "incidents.middleware.AdminMFAEnforcementMiddleware",
    "incidents.middleware.AdminSectionPasswordMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "emergency_platform.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "incidents.context_processors.dashboard_navigation",
            ],
        },
    },
]

WSGI_APPLICATION = "emergency_platform.wsgi.application"
ASGI_APPLICATION = "emergency_platform.asgi.application"
DATABASE_URL = os.getenv("DATABASE_URL")
USE_SQLITE = os.getenv("DJANGO_USE_SQLITE", "0") == "1"
SQLITE_DATABASE_PATH = os.getenv("DJANGO_SQLITE_PATH", str(BASE_DIR / "db.sqlite3"))
if USE_SQLITE:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": SQLITE_DATABASE_PATH,
            "OPTIONS": {"timeout": 20},
            "CONN_MAX_AGE": 0,
        },
    }
elif DATABASE_URL:
    database_url = urlparse(DATABASE_URL)
    if database_url.scheme not in {"postgres", "postgresql"}:
        raise ImproperlyConfigured("DATABASE_URL must use the postgres:// or postgresql:// scheme.")
    database_query = parse_qs(database_url.query)
    database_options = {
        key: database_query[key][0]
        for key in ("sslmode", "target_session_attrs")
        if database_query.get(key)
    }
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": unquote(database_url.path.lstrip("/")),
            "USER": unquote(database_url.username or ""),
            "PASSWORD": unquote(database_url.password or ""),
            "HOST": database_url.hostname or "",
            "PORT": str(database_url.port or "5432"),
            "OPTIONS": database_options,
            "CONN_MAX_AGE": int(os.getenv("DJANGO_DB_CONN_MAX_AGE", "60")),
        },
    }
elif DEBUG:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": SQLITE_DATABASE_PATH,
            "OPTIONS": {"timeout": 20},
            "CONN_MAX_AGE": 0,
        },
    }
else:
    raise ImproperlyConfigured("DATABASE_URL must be set when DJANGO_DEBUG=0.")

CACHE_LOCATION = os.getenv("DJANGO_CACHE_LOCATION", str(BASE_DIR / ".cache"))
if DEBUG:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "rapid-response-development",
        },
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.filebased.FileBasedCache",
            "LOCATION": CACHE_LOCATION,
            "TIMEOUT": 300,
            "OPTIONS": {"MAX_ENTRIES": 10000},
        },
    }

REDIS_URL = os.getenv("REDIS_URL")
if REDIS_URL:
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels_redis.core.RedisChannelLayer",
            "CONFIG": {"hosts": [REDIS_URL]},
        },
    }
else:
    CHANNEL_LAYERS = {
        "default": {"BACKEND": "channels.layers.InMemoryChannelLayer"},
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
LANGUAGE_CODE = "en-us"
TIME_ZONE = "Africa/Kampala"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = Path(os.getenv("DJANGO_STATIC_ROOT", str(BASE_DIR / "staticfiles")))
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LOGIN_URL = "/dashboard/login/"
MFA_REQUIRED = os.getenv("DJANGO_MFA_REQUIRED", "1" if not DEBUG else "0") == "1"
MFA_CHALLENGE_AGE = 10 * 60
ADMIN_SECTION_PASSWORD = os.getenv("DJANGO_ADMIN_SECTION_PASSWORD")
if not ADMIN_SECTION_PASSWORD and DEBUG:
    ADMIN_SECTION_PASSWORD = "mindset123.."
ADMIN_SECTION_PASSWORD_HASH = os.getenv("DJANGO_ADMIN_SECTION_PASSWORD_HASH") or (
    make_password(ADMIN_SECTION_PASSWORD) if ADMIN_SECTION_PASSWORD else None
)
if not DEBUG and not ADMIN_SECTION_PASSWORD_HASH:
    raise ImproperlyConfigured(
        "DJANGO_ADMIN_SECTION_PASSWORD or DJANGO_ADMIN_SECTION_PASSWORD_HASH must be set when DJANGO_DEBUG=0."
    )
CASE_DELETE_PASSWORD = os.getenv("DJANGO_CASE_DELETE_PASSWORD")
if not CASE_DELETE_PASSWORD and DEBUG:
    CASE_DELETE_PASSWORD = "778899"
CASE_DELETE_PASSWORD_HASH = os.getenv("DJANGO_CASE_DELETE_PASSWORD_HASH") or (
    make_password(CASE_DELETE_PASSWORD) if CASE_DELETE_PASSWORD else None
)
if not DEBUG and not CASE_DELETE_PASSWORD_HASH:
    raise ImproperlyConfigured(
        "DJANGO_CASE_DELETE_PASSWORD or DJANGO_CASE_DELETE_PASSWORD_HASH must be set when DJANGO_DEBUG=0."
    )

# Production deployments should set DJANGO_SECURE_COOKIES=1 behind HTTPS.
SECURE_COOKIES = os.getenv("DJANGO_SECURE_COOKIES", "0" if DEBUG else "1") == "1"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = SECURE_COOKIES
SESSION_COOKIE_AGE = 30 * 60
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SECURE = SECURE_COOKIES
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_SSL_REDIRECT = SECURE_COOKIES
if TRUST_PROXY_HEADERS:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_HSTS_SECONDS = 31536000 if SECURE_COOKIES else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = SECURE_COOKIES
SECURE_HSTS_PRELOAD = SECURE_COOKIES
DATA_UPLOAD_MAX_MEMORY_SIZE = 30 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 30 * 1024 * 1024
DATA_UPLOAD_MAX_NUMBER_FIELDS = 100
FILE_UPLOAD_PERMISSIONS = 0o640
FILE_UPLOAD_DIRECTORY_PERMISSIONS = 0o750
