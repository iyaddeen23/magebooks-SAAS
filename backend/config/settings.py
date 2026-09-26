"""Mage Books SAAS - Unified Django Settings.

Single configuration module utilizing django-environ with explicit type casting,
safe fallback defaults, and automated test routing to in-memory SQLite.
"""

import sys
from datetime import timedelta
from pathlib import Path

import environ

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# 1. Initialize environ
env = environ.Env()

# 2. Read .env file from BASE_DIR if present (does not fail if missing)
environ.Env.read_env(BASE_DIR / ".env")

# 3. Detect Testing and Debug Modes
IS_TESTING = "test" in sys.argv or "pytest" in sys.modules
DEBUG = env.bool("DJANGO_DEBUG", default=False)

# 4. Fail-closed Security Defaults for SECRET_KEY, ALLOWED_HOSTS, and CORS:
# Fallbacks are strictly restricted to automated test runners or explicit local DEBUG=True.
# In production (DEBUG=False), missing variables cause an immediate startup crash (fail fast).
if IS_TESTING or DEBUG:
    SECRET_KEY = env(
        "DJANGO_SECRET_KEY",
        default="django-insecure-magebooks-dev-key-change-in-production",
    )
    ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["*"])
    CORS_ALLOWED_ORIGINS = env.list(
        "DJANGO_CORS_ALLOWED_ORIGINS",
        default=["http://localhost:3000"],
    )
else:
    SECRET_KEY = env("DJANGO_SECRET_KEY")
    ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS")
    CORS_ALLOWED_ORIGINS = env.list("DJANGO_CORS_ALLOWED_ORIGINS")

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
    "apps.tenancy.middleware.TenantSecurityMiddleware",
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
if IS_TESTING:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": ":memory:",
        }
    }
    # Fast password hasher to accelerate automated test suite (<2s vs 60s+)
    PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
elif DEBUG:
    # Safe fallback for local development with DEBUG=True
    DATABASES = {
        "default": env.db(
            "DATABASE_URL",
            default="postgres://postgres:postgres@localhost:5432/magebooks_db",
        )
    }
else:
    # Production strictly requires DATABASE_URL to prevent silent fallback to default credentials
    DATABASES = {"default": env.db("DATABASE_URL")}

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

# Custom User Model (UUIDv7 primary key, email-based auth)
AUTH_USER_MODEL = "authentication.CustomUser"

# Django REST Framework
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "apps.authentication.authentication.JWTCookieAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
    ],
}

# Simple JWT Configuration
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": False,
    "BLACKLIST_AFTER_ROTATION": False,
    "ALGORITHM": "HS256",
    "SIGNING_KEY": SECRET_KEY,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
}

# JWT Cookie Transport Settings
JWT_AUTH_COOKIE = "access_token"
JWT_REFRESH_COOKIE = "refresh_token"
JWT_COOKIE_SECURE = env.bool("JWT_COOKIE_SECURE", default=not DEBUG)
JWT_COOKIE_SAMESITE = env("JWT_COOKIE_SAMESITE", default="Strict")

# Cloudflare R2 Object Storage (S3-Compatible)
CLOUDFLARE_R2_ACCESS_KEY_ID = env("R2_ACCESS_KEY_ID", default="")
CLOUDFLARE_R2_SECRET_ACCESS_KEY = env("R2_SECRET_ACCESS_KEY", default="")
CLOUDFLARE_R2_BUCKET_NAME = env("R2_BUCKET_NAME", default="magebooks-prod")
CLOUDFLARE_R2_ENDPOINT_URL = env("R2_ENDPOINT_URL", default="")

# Payment Gateway & Webhook Secrets
PAYSTACK_SECRET_KEY = env("PAYSTACK_SECRET_KEY", default="sk_test_mock_paystack_secret_key")
HUBTEL_CLIENT_SECRET = env("HUBTEL_CLIENT_SECRET", default="mock_hubtel_secret_key")
MOMO_WEBHOOK_SECRET = env("MOMO_WEBHOOK_SECRET", default="mock_momo_webhook_secret_key")
ACTIVE_PAYMENT_GATEWAY = env("ACTIVE_PAYMENT_GATEWAY", default="mock")

# Redis & Distributed Idempotency Configuration
REDIS_URL = env("REDIS_URL", default="redis://localhost:6379/0")
IDEMPOTENCY_LOCK_TTL = env.int("IDEMPOTENCY_LOCK_TTL", default=60)
USE_MOCK_REDIS = env.bool("USE_MOCK_REDIS", default=IS_TESTING or DEBUG)
