"""
Django settings for AERO-OPS (SIH26250) — Dynamic Air Operations & Resource Optimisation.
Human-in-the-loop, simulation-first decision-support platform.
"""
from pathlib import Path
from django.core.exceptions import ImproperlyConfigured
import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, False),
    DEMO_MODE=(bool, False),
    ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1", "0.0.0.0", "web"]),
    CSRF_TRUSTED_ORIGINS=(
        list,
        ["http://localhost:8000", "http://127.0.0.1:8000", "http://localhost:5008"],
    ),
    DATABASE_URL=(
        str,
        "postgis://aero_ops_user:aero_ops_pass@localhost:5432/aero_ops",
    ),
    REDIS_URL=(str, "redis://localhost:6379/0"),
    SIMULATION_DEFAULT_SEED=(int, 26250),
)

env_file = BASE_DIR / ".env"
if env_file.exists():
    environ.Env.read_env(str(env_file))

DEBUG = env("DEBUG")
DEMO_MODE = env("DEMO_MODE")

# Enforce secret key presence outside DEMO_MODE (Phase 1 Security)
raw_secret_key = env("DJANGO_SECRET_KEY", default=None)
if not raw_secret_key:
    if DEMO_MODE:
        raw_secret_key = "sih26250-aero-ops-local-demo-secret-key-9981234567890"
    else:
        raise ImproperlyConfigured("DJANGO_SECRET_KEY environment variable is required outside DEMO_MODE.")
SECRET_KEY = raw_secret_key

ALLOWED_HOSTS = env("ALLOWED_HOSTS")
CSRF_TRUSTED_ORIGINS = env("CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    "daphne",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "whitenoise.runserver_nostatic",
    "django.contrib.staticfiles",
    "django.contrib.gis",
    "channels",
    "rest_framework",
    "rest_framework_gis",
    "apps.core.apps.CoreConfig",
    "apps.radar_simulation.apps.RadarSimulationConfig",
    "apps.suggestion.apps.SuggestionConfig",
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

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.core.portal_views.demo_mode_context_processor",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": env.db("DATABASE_URL", engine="django.contrib.gis.db.backends.postgis")
}
DATABASES["default"]["CONN_MAX_AGE"] = 60

REDIS_URL = env("REDIS_URL")
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [REDIS_URL],
            "capacity": 1500,
            "expiry": 10,
        },
    },
}

# Cache layer supporting rate limiting
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "aero-ops-ratelimit-cache",
    }
}

AUTH_USER_MODEL = "core.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 8},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Phase 1: Only robust PBKDF2; dropped weak PBKDF2SHA1
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_AGE = 3600 * 4
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_HTTPONLY = False
CSRF_COOKIE_SAMESITE = "Lax"
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "30/minute",
        "user": "120/minute",
        "auth": "5/minute",
        "simulation": "20/minute",
    },
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 25,
    "DATETIME_FORMAT": "%Y-%m-%dT%H:%M:%SZ",
}

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"] if (BASE_DIR / "static").exists() else []
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_STORAGE = "whitenoise.storage.CompressedStaticFilesStorage"

FIXTURE_DIRS = [BASE_DIR / "fixtures"]

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

SIMULATION_DEFAULT_SEED = env("SIMULATION_DEFAULT_SEED")
ML_ARTIFACTS_DIR = Path(env("ML_ARTIFACTS_DIR", default=str(BASE_DIR / "ml_artifacts")))
SIMULATION_MODE_BANNER = "SYNTHETIC SIMULATION MODE — NON-OPERATIONAL DEMO (SIH26250)"
