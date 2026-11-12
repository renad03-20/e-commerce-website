"""Isolated tests: no project .env, production database, email or Stripe calls."""
from pathlib import Path
from tempfile import gettempdir

BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = 'isolated-tests-only-not-a-deployment-secret'
DEBUG = True
USE_TZ = True
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
INSTALLED_APPS = [
    'django.contrib.admin', 'django.contrib.auth', 'django.contrib.contenttypes',
    'django.contrib.sessions', 'django.contrib.messages', 'django.contrib.staticfiles',
    'products', 'cart', 'orders', 'pages', 'artwork', 'accounts',
]
DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}}
ROOT_URLCONF = 'storefront.urls'
MIDDLEWARE = [
    'artwork.private_files.LegacyCommissionMediaGuard',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
]
TEMPLATES = [{
    'BACKEND': 'django.template.backends.django.DjangoTemplates', 'APP_DIRS': True,
    'DIRS': [BASE_DIR / 'templates'],
    'OPTIONS': {'context_processors': [
        'django.template.context_processors.request',
        'django.contrib.auth.context_processors.auth',
        'django.contrib.messages.context_processors.messages',
        'cart.context_processors.cart_context', 'pages.context_processors.is_artist_processor',
    ]},
}]
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
MEDIA_URL = '/media/'
MEDIA_ROOT = str(Path(gettempdir()) / 'artsy-test-media')
PRIVATE_MEDIA_ROOT = str(Path(gettempdir()) / 'artsy-test-private-media')
LOGIN_URL = 'login'
ALLOWED_HOSTS = ['testserver', 'localhost', '127.0.0.1']
PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']
STRIPE_SECRET_KEY = 'sk_test_mock_only'
STRIPE_WEBHOOK_SECRET = 'whsec_mock_only'
EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
DEFAULT_FROM_EMAIL = 'test@example.com'
