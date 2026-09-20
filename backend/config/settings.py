"""Mage Books SAAS - Unified Django Settings.

Single configuration module utilizing django-environ with explicit type casting,
safe fallback defaults, and automated test routing to in-memory SQLite.
"""

import sys
from pathlib import Path

import environ

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# 1. Initialize environ with explicit type casting and safe fallback defaults
env = environ.Env(
    DJANGO_DEBUG=(bool, False),
    DJANGO_SECRET_KEY=(str, "django-insecure-magebooks-dev-key-change-in-production"),
    DJANGO_ALLOWED_HOSTS=(list, ["*"]),
    DJANGO_CORS_ALLOWED_ORIGINS=(list, ["http://localhost:3000"]),
)

# 2. Read .env file from BASE_DIR if present (does not fail if missing)
environ.Env.read_env(BASE_DIR / ".env")

# 3. Pull Core Variables
SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = env("DJANGO_DEBUG")
ALLOWED_HOSTS = env("DJANGO_ALLOWED_HOSTS")
CORS_ALLOWED_ORIGINS = env("DJANGO_CORS_ALLOWED_ORIGINS")

# Application definition
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third-party extensions
    "rest_framework",
    "corsheaders",
    "storages",
    # Core Domain Apps
    "apps.core",
    "apps.authentication",
    "apps.tenancy",
    "apps.ledger",
    "apps.tax",
    "apps.invoicing",
    "apps.payments",
    "apps.payroll",
    "apps.audit",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# Database Routing: In-Memory SQLite for Automated Tests, PostgreSQL for Dev/Prod
IS_TESTING = "test" in sys.argv or "pytest" in sys.modules

if IS_TESTING:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": ":memory:",
        }
    }
else:
    DATABASES = {
        "default": env.db(
            "DATABASE_URL",
            default="postgres://postgres:postgres@localhost:5432/magebooks_db",
        )
    }

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

# Internationalization & Ghanaian Locale
LANGUAGE_CODE = "en-us"
TIME_ZONE = "Africa/Accra"
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# Default primary key field type
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Django REST Framework
REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
    ],
}

# Cloudflare R2 Object Storage (S3-Compatible)
CLOUDFLARE_R2_ACCESS_KEY_ID = env("R2_ACCESS_KEY_ID", default="")
CLOUDFLARE_R2_SECRET_ACCESS_KEY = env("R2_SECRET_ACCESS_KEY", default="")
CLOUDFLARE_R2_BUCKET_NAME = env("R2_BUCKET_NAME", default="magebooks-prod")
CLOUDFLARE_R2_ENDPOINT_URL = env("R2_ENDPOINT_URL", default="")
