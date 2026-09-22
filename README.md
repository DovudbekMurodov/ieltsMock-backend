# ieltsMock-backend

Django backend for the [PrepPath IELTS SPA](https://github.com/DovudbekMurodov/ieltsMock).

Owns all practice content (Reading, Listening, Writing, Speaking, Vocabulary), serves it to
the React frontend over a cached REST API, and tracks accounts, attempts, band scores and
usage. Content is managed through a custom staff dashboard, with Django admin kept as a
fallback.

## Stack

Python 3.12 · Django 5.2 LTS · DRF 3.18 · PostgreSQL 17

Django 5.2 rather than 6.1 because `django-cors-headers` and `drf-spectacular` do not yet
declare Django 6.1 support, and both are load-bearing here. Python 3.12 rather than 3.14
because `gunicorn` and `django-storages` do not declare 3.14.

## Local setup

Requires Python 3.12 and a running PostgreSQL 17.

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements/dev.txt
cp .env.example .env          # then edit
createdb ieltsmock
.venv/bin/python manage.py migrate
.venv/bin/python manage.py createsuperuser
.venv/bin/python manage.py runserver
```

Check it came up:

```bash
curl http://127.0.0.1:8000/healthz
# {"status": "ok", "checks": {"database": "ok"}}
```

| URL | What |
|---|---|
| `/dashboard/` | Staff content studio (Tailwind + HTMX) |
| `/healthz` | Liveness + a real database round-trip |
| `/admin/` | Django admin |
| `/api/v1/docs/` | Swagger UI |
| `/api/v1/schema/` | OpenAPI schema |

## Content

Load the seed data (idempotent), then build the public payloads:

```bash
node seed/export_from_frontend.mjs --src=../ieltsMock/src/data   # only when the source data changes
.venv/bin/python manage.py seed_content
.venv/bin/python manage.py publish_content
.venv/bin/python manage.py bootstrap_groups     # staff roles
.venv/bin/python manage.py seed_demo_data       # optional demo accounts
```

Nothing is served over the API until it is published. The dashboard's Publish
button rebuilds a test's payload; `publish_content` does the same in bulk.

## Dashboard

Django templates + Tailwind + HTMX + Alpine, styled after the student app.
Staff-only; non-staff get a 404 rather than a 403.

The CSS is built with the Tailwind CLI and **committed**, so a deploy needs no
Node:

```bash
npm install
npm run tw:dev     # watch while editing templates
npm run tw:build   # minified, commit the result
```

`tailwind.config.cjs` mirrors the frontend's, pinned to Tailwind 3.4. Tailwind 4
changed the config format, and using it here would guarantee the two design
systems drift apart.

## Settings

`config/settings/` splits into `base`, `dev`, `test` and `prod`. `manage.py` defaults to
`dev`; `wsgi.py`/`asgi.py` default to `prod`; pytest uses `test`.

`prod.py` resolves its required environment variables at import time, so a misconfigured
deploy fails at boot instead of on the first request that happens to need them.

## Checks

```bash
.venv/bin/ruff check .
.venv/bin/python -m pytest
.venv/bin/python manage.py makemigrations --check --dry-run
.venv/bin/python manage.py spectacular --file api-schema.yml   # committed; CI fails on drift
```

All three run in CI on every push and pull request.

## Deploying

`deploy/DEPLOY.md` covers the droplet end to end: nginx, gunicorn under
systemd, the nightly rollup and backup timers, and what `.env` must contain.

## Deployment note — read before wiring up auth

The SPA is served over HTTPS from `*.vercel.app`, so a plain `http://<droplet-ip>/api`
call is **blocked by the browser as mixed content**. The API therefore needs TLS, and
Let's Encrypt will not issue a certificate for a bare IP address — so the droplet needs a
hostname before auth work can be tested end to end.

`*.duckdns.org` is on the Public Suffix List, which means each subdomain gets its own
Let's Encrypt rate-limit bucket; `nip.io` and `sslip.io` are not, so their shared bucket is
routinely exhausted. Point a DuckDNS subdomain at the droplet and run certbot, or use a
real domain. Moving to a real domain later is a DNS change, not a rewrite.

Related: `vercel.app` is itself on the Public Suffix List, so no cookie can ever be shared
between the SPA origin and this API. That is why the SPA authenticates with JWT while the
same-origin staff dashboard uses ordinary Django sessions.

## What the frontend still needs

The React app in `../ieltsMock` continues to read its five bundled data files; nothing in
it calls this API yet. Wiring it up means an API client, TanStack Query, auth screens,
merging the two results pages, and — the largest and least visible part — a loading and
error state for roughly a dozen components that currently have neither, because `import`
is synchronous.
