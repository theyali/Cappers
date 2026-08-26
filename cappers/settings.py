import os
from datetime import timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


def env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


SECRET_KEY = os.getenv("SECRET_KEY", "unsafe-development-key")
DEBUG = env_bool("DEBUG", True)
ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "tinymce",
    "django_celery_beat",
    "cabinet.apps.CabinetConfig",
    "game.apps.GameConfig",
    "back.apps.BackConfig",
    "front.apps.FrontConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "cappers.urls"

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
            ],
        },
    },
]

WSGI_APPLICATION = "cappers.wsgi.application"
ASGI_APPLICATION = "cappers.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("POSTGRES_DB", "cappers"),
        "USER": os.getenv("POSTGRES_USER", "cappers"),
        "PASSWORD": os.getenv("POSTGRES_PASSWORD", "cappers_dev_password"),
        "HOST": os.getenv("DB_HOST", "pgbouncer"),
        "PORT": os.getenv("DB_PORT", "6432"),
        "CONN_MAX_AGE": 0,
        "DISABLE_SERVER_SIDE_CURSORS": True,
    }
}

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": os.getenv("CACHE_URL", "redis://redis:6379/2"),
        "KEY_PREFIX": "cappers",
    }
}

AUTH_USER_MODEL = "cabinet.User"
LOGIN_URL = "cabinet:login"
LOGIN_REDIRECT_URL = "cabinet:dashboard"
LOGOUT_REDIRECT_URL = "front:index"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "ru"
TIME_ZONE = os.getenv("TIME_ZONE", "Asia/Baku")
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

TINYMCE_DEFAULT_CONFIG = {
    "height": 560,
    "menubar": True,
    "plugins": "advlist autolink lists link image charmap preview anchor searchreplace visualblocks code fullscreen insertdatetime media table help wordcount",
    "toolbar": "undo redo | blocks | bold italic underline | alignleft aligncenter alignright | bullist numlist | link image media table | blockquote code | removeformat fullscreen",
    "content_style": "body { font-family: Arial, sans-serif; font-size: 16px; line-height: 1.6; }",
}

EMAIL_BACKEND = os.getenv(
    "EMAIL_BACKEND",
    (
        "django.core.mail.backends.console.EmailBackend"
        if DEBUG
        else "django.core.mail.backends.smtp.EmailBackend"
    ),
)
EMAIL_HOST = os.getenv("EMAIL_HOST", "localhost")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "25"))
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", False)
EMAIL_USE_SSL = env_bool("EMAIL_USE_SSL", False)
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "noreply@cappers.local")

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

CELERY_BROKER_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://redis:6379/1")
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 300
CELERY_TASK_SOFT_TIME_LIMIT = 270
CELERY_TIMEZONE = TIME_ZONE
CELERY_BEAT_SCHEDULE = {
    "fetch-live-football-matches": {
        "task": "game.tasks.fetch_live_matches",
        "schedule": timedelta(seconds=15),
    },
    "fetch-prematch-football-matches": {
        "task": "game.tasks.fetch_upcoming_matches",
        "schedule": timedelta(minutes=10),
    },
    "fetch-finished-football-matches": {
        "task": "game.tasks.fetch_finished_matches",
        "schedule": timedelta(minutes=15),
    },
}

NEUROKEFF_API_BASE_URL = os.getenv(
    "NEUROKEFF_API_BASE_URL",
    "https://sports.api-neurokeff.ru/api/v2",
)
NEUROKEFF_API_TOKEN = os.getenv("NEUROKEFF_API_TOKEN", "")
NEUROKEFF_FOOTBALL_SPORT_ID = env_int("NEUROKEFF_FOOTBALL_SPORT_ID", 2)
NEUROKEFF_LANG = os.getenv("NEUROKEFF_LANG", "ru,en")
NEUROKEFF_PAGE_SIZE = env_int("NEUROKEFF_PAGE_SIZE", 100)
NEUROKEFF_MAX_PAGES = env_int("NEUROKEFF_MAX_PAGES", 20)
NEUROKEFF_API_TIMEOUT = env_int("NEUROKEFF_API_TIMEOUT", 20)
NEUROKEFF_PREMATCH_DAYS_AHEAD = env_int("NEUROKEFF_PREMATCH_DAYS_AHEAD", 1)
NEUROKEFF_FINISHED_DAYS_BACK = env_int("NEUROKEFF_FINISHED_DAYS_BACK", 1)
COUPON_MATCH_STALE_SECONDS = env_int("COUPON_MATCH_STALE_SECONDS", 60)
COUPON_MATCH_STATE_CACHE_SECONDS = env_int("COUPON_MATCH_STATE_CACHE_SECONDS", 10)
