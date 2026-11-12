# e-commerce-website

**Local Setup**
1. `pipenv install`
2. Copy `.env.example` to `.env` and fill in values.
3. `pipenv run python manage.py migrate`
4. `pipenv run python manage.py runserver`

**Deployment Checklist**
1. Set `DEBUG=False` and configure `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS`.
2. Provide a production database in `DATABASE_URL`.
3. `pipenv run python manage.py migrate`
4. `pipenv run python manage.py collectstatic --noinput`
5. Run the app with a WSGI server, for example `gunicorn storefront.wsgi:application`.

**Notes**
1. Static files are served with WhiteNoise.
2. Email uses the console backend when `DEBUG=True` and SMTP in production.
