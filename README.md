# Postbean

Open-source, self-hostable social media management platform built for agencies and SMBs. Supports Facebook, Instagram, LinkedIn, TikTok, YouTube, Pinterest, Threads, Bluesky, Google Business Profile, and Mastodon.

## Quick Start (Docker)

```bash
git clone https://github.com/yourorg/postbean.git
cd postbean
cp .env.example .env
```

Edit `.env` — change `DATABASE_URL` to point to the Docker service name:

```
DATABASE_URL=postgres://postgres:postgres@postgres:5432/postbean
```

Then start everything:

```bash
docker compose up -d
docker compose exec app python manage.py migrate
docker compose exec app python manage.py createsuperuser
```

Open http://localhost:8000 — you're running.

## Local Development (without Docker for the app)

Use Docker only for PostgreSQL, run Django on your host for faster iteration.

### Prerequisites

- Python 3.12+
- Node.js 20+ (for Tailwind CSS)
- Docker (for PostgreSQL)

### Setup

**1. Clone and configure**

```bash
git clone https://github.com/yourorg/postbean.git
cd postbean
cp .env.example .env
```

The default `.env` is ready for local development — `DATABASE_URL` points to `localhost:5432` which is correct when running Django on your host.

**2. Start PostgreSQL**

```bash
docker compose up postgres -d
```

Verify it's running:

```bash
docker compose ps
# postgres should show "healthy"
```

**3. Set up Python**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**4. Set up Tailwind CSS**

```bash
cd theme/static_src
npm install
cd ../..
```

**5. Run database migrations**

```bash
python manage.py migrate
```

**6. Create your admin account**

```bash
python manage.py createsuperuser
```

**7. Start the app (3 terminal tabs)**

Tab 1 — Tailwind watcher (recompiles CSS on template changes):
```bash
cd theme/static_src && npm run start
```

Tab 2 — Django dev server:
```bash
source .venv/bin/activate
python manage.py runserver
```

Tab 3 — Background worker (processes scheduled posts, inbox sync, etc.):
```bash
source .venv/bin/activate
python manage.py process_tasks
```

Open http://localhost:8000 and log in with the superuser you created.

### What each process does

| Process | Command | Purpose |
|---------|---------|---------|
| **Web server** | `python manage.py runserver` | Serves the Django app |
| **Worker** | `python manage.py process_tasks` | Runs background jobs (publishing, inbox sync, analytics collection) |
| **Tailwind** | `npm run start` (in `theme/static_src/`) | Watches templates and recompiles CSS |
| **PostgreSQL** | `docker compose up postgres -d` | Database |

### Daily workflow

After initial setup, your daily startup is:

```bash
docker compose up postgres -d           # start DB (if not running)
source .venv/bin/activate                # activate Python env
python manage.py runserver               # start web server
# (open another tab)
python manage.py process_tasks           # start worker
```

Tailwind watcher is only needed when you're editing templates/CSS.

## Running Tests

```bash
pytest
```

With coverage:

```bash
pytest --cov=apps --cov-report=term-missing
```

## Linting & Type Checking

```bash
ruff check .                             # lint
ruff format --check .                    # format check
mypy apps/ config/ --ignore-missing-imports  # type check
```

Auto-fix lint issues:

```bash
ruff check --fix .
ruff format .
```

## Production Deployment

### Docker Compose on a VPS (recommended)

```bash
# On your server:
git clone https://github.com/yourorg/postbean.git
cd postbean
cp .env.example .env
# Edit .env:
#   SECRET_KEY=<generate a random 50+ char string>
#   DEBUG=false
#   ALLOWED_HOSTS=yourdomain.com
#   APP_URL=https://yourdomain.com
#   DATABASE_URL=postgres://postgres:<strong-password>@postgres:5432/postbean

docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
docker compose exec app python manage.py migrate
docker compose exec app python manage.py createsuperuser
```

This starts 4 containers: app (Gunicorn), worker, PostgreSQL, and Caddy (auto-HTTPS). Edit the `Caddyfile` with your domain.

To update:

```bash
git pull
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
docker compose exec app python manage.py migrate
```

### Other Platforms

| Platform | Config file | Notes |
|----------|-------------|-------|
| **Heroku** | `Procfile` + `app.json` | Deploy-button ready. Must use Basic+ dynos (Eco dynos break the worker). |
| **Railway** | `railway.toml` | Three services: web, worker, managed PostgreSQL. |
| **Render** | `render.yaml` | Blueprint with web, worker, PostgreSQL. Must use paid tier. |

All platforms with ephemeral filesystems require `STORAGE_BACKEND=s3` — see `.env.example` for S3 configuration.

See `architecture.md` for detailed per-platform instructions and cost breakdowns.

## Project Structure

```
postbean/
├── config/
│   ├── settings/
│   │   ├── base.py            # Shared settings
│   │   ├── development.py     # Local dev overrides
│   │   ├── production.py      # Production hardening
│   │   └── test.py            # Test overrides
│   ├── urls.py                # Root URL configuration
│   ├── wsgi.py
│   └── asgi.py
├── apps/
│   ├── accounts/              # Custom User model, auth, OAuth, sessions
│   ├── organizations/         # Organization management
│   ├── workspaces/            # Workspace CRUD
│   ├── members/               # RBAC, invitations, middleware, decorators
│   ├── settings_manager/      # Configurable defaults with cascade logic
│   ├── credentials/           # Platform API credential storage (encrypted)
│   └── common/                # Shared: encrypted fields, scoped model managers
├── providers/                 # Social platform API modules (one file per platform)
├── templates/                 # Django templates
│   ├── base.html              # Layout with sidebar + nav
│   └── components/            # Reusable HTMX partials
├── static/
│   └── js/                    # Vendored HTMX + Alpine.js
├── theme/                     # django-tailwind theme app
│   └── static_src/
│       ├── src/styles.css     # Tailwind directives
│       └── tailwind.config.js
├── Dockerfile
├── docker-compose.yml         # Dev: app + worker + postgres
├── docker-compose.prod.yml    # Prod override: adds Caddy, uses Gunicorn
├── Caddyfile                  # Reverse proxy + auto-HTTPS config
├── .env.example               # All environment variables
├── Procfile                   # Heroku
├── app.json                   # Heroku deploy button
├── railway.toml               # Railway config
└── render.yaml                # Render blueprint
```

## Environment Variables

All configuration is via environment variables. See `.env.example` for the full list.

Key variables for local development:

| Variable | Default | Description |
|----------|---------|-------------|
| `SECRET_KEY` | (required) | Django secret key. Any random string for dev. |
| `DEBUG` | `false` | Set to `true` for local development. |
| `DATABASE_URL` | — | PostgreSQL connection string. |
| `STORAGE_BACKEND` | `local` | `local` for filesystem, `s3` for S3-compatible storage. |
| `EMAIL_BACKEND_TYPE` | `smtp` | Set to `smtp` for SMTP or leave default (console in dev). |

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Django 5.x, Django REST Framework |
| Frontend | Django templates, HTMX, Alpine.js |
| CSS | Tailwind CSS 4 via django-tailwind |
| Database | PostgreSQL 16+ |
| Background jobs | django-background-tasks (no Redis required) |
| Auth | django-allauth (email + Google OAuth) |
| Media | Pillow (images), FFmpeg (video) |
| Deployment | Docker, Gunicorn, Caddy |

## License

See [LICENSE](LICENSE) for details.
