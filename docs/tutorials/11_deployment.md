# Tutorial 11: Deploying a Generated App to Production

This tutorial walks through taking a pgappforge-generated app from your laptop to a live production server using the `flask forge deploy` CLI. By the end you will have a running app behind nginx with TLS, a managed PostgreSQL connection pool, and GitHub Actions deploying on every push to `main`.

## Prerequisites

- pgappforge installed: `pip install pgappforge`
- Docker Desktop (for local testing)
- SSH access to a VPS or cloud VM (Ubuntu 22.04 recommended)
- A generated app — if you do not have one yet, run `flask forge gen all` first

---

## Step 1 — Generate the app and initialise deploy config

`flask forge gen all` already writes a `Dockerfile` and `docker-compose.yml` to the output directory. `flask forge deploy init` layers on top of that: it writes `.fab-deploy.yml` (the deploy manifest), a production-hardened `nginx.conf`, a `gunicorn.conf.py`, and a GitHub Actions workflow file.

```bash
flask forge gen all postgresql://user:pass@localhost/mydb \
  --name MyApp \
  --output-dir ./myapp/

cd myapp
flask forge deploy init
```

Files created by `deploy init`:

```
myapp/
├── .fab-deploy.yml          # deploy manifest (hosts, registry, env vars)
├── Dockerfile               # multi-stage Python 3.12-slim image
├── docker-compose.yml       # app + postgresql + redis + nginx services
├── gunicorn.conf.py         # worker count, gevent, access log format
├── nginx.conf               # TLS termination, rate limiting, static caching
└── .github/
    └── workflows/
        └── deploy.yml       # CI/CD pipeline
```

---

## Step 2 — Local Docker smoke test

Before touching a server, verify the image builds and the app responds correctly on your machine.

```bash
flask forge deploy docker build
flask forge deploy docker run
# App available at http://localhost:8080
```

`docker build` runs `docker compose build`. `docker run` starts all services defined in `docker-compose.yml` and tails stdout until you press Ctrl-C.

Check the health endpoint:

```bash
curl -s http://localhost:8080/health
# {"status": "healthy", "timestamp": "...", "version": "1.0.0"}
```

Stop containers when done:

```bash
flask forge deploy docker restart   # graceful restart (zero-downtime rolling)
```

---

## Step 3 — Environment variables for production

Never bake secrets into the image. The generated `.fab-deploy.yml` lists required variables; populate them before pushing to the server.

| Variable | Notes |
|---|---|
| `SQLALCHEMY_DATABASE_URI` | Use a connection pooler (PgBouncer) URI in production, not a direct connection |
| `SECRET_KEY` | Minimum 32 characters; generate with `python -c "import secrets; print(secrets.token_hex(32))"` |
| `FLASK_ENV` | Set to `production`; disables debug mode and enables secure cookie flags |
| `REDIS_URL` | Required if using caching, sessions, or the `workflow`/`realtime` plugins |
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` | Only if using AI features |

On the server, write these to `/etc/myapp/env` (mode 600, owned by the deploy user) and reference them via `env_file` in `docker-compose.yml`. Never commit `.env` files to version control.

The generated `config.py` already reads all of these from `os.environ`:

```python
SQLALCHEMY_DATABASE_URI = os.environ.get('SQLALCHEMY_DATABASE_URI')
SECRET_KEY = os.environ.get('SECRET_KEY')
WTF_CSRF_ENABLED = True
SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
FAB_UPDATE_PERMS = False   # set True only on first boot
```

---

## Step 4 — Docker Compose service topology

The generated `docker-compose.yml` defines four services:

```yaml
version: '3.8'
services:
  app:
    build: .
    restart: unless-stopped
    env_file: /etc/myapp/env
    depends_on: [db, redis]

  db:
    image: postgres:15
    restart: unless-stopped
    volumes:
      - postgres_data:/var/lib/postgresql/data

  redis:
    image: redis:7-alpine
    restart: unless-stopped

  nginx:
    image: nginx:alpine
    restart: unless-stopped
    ports: ["80:80", "443:443"]
    volumes:
      - ./nginx.conf:/etc/nginx/conf.d/default.conf
      - ./ssl:/etc/ssl/certs
    depends_on: [app]
```

To customise — for example, to point `db` at an external managed PostgreSQL instance instead of the local container — remove the `db` service and update `SQLALCHEMY_DATABASE_URI` in your env file. The `app` service's `depends_on` list can be adjusted accordingly.

---

## Step 5 — Running database migrations

The generated app uses Flask-Migrate (Alembic). Before starting the app for the first time on a new database, run:

```bash
flask forge deploy server migrate
```

This SSH-es to the target host and runs `flask db upgrade` inside the running `app` container. It is safe to run on every deploy — Alembic is idempotent.

For the very first deploy, also create the admin user:

```bash
flask forge deploy server migrate
# Then, once on the server:
docker compose exec app flask fab create-admin
```

---

## Step 6 — Pushing and starting on a VPS

`.fab-deploy.yml` holds the server connection details:

```yaml
# .fab-deploy.yml
host: myapp.example.com
user: deploy
app_dir: /opt/myapp
registry: ghcr.io/myorg/myapp
```

Deploy workflow:

```bash
# Sync files and pull latest image on the server
flask forge deploy server push --host myapp.example.com --user deploy

# Start (or restart) all containers
flask forge deploy server start

# Tail logs in real time
flask forge deploy server logs -f
```

`server push` uses rsync over SSH to sync only changed files, then pulls the latest Docker image from the registry. `server start` runs `docker compose up -d --remove-orphans`.

---

## Step 7 — GitHub Actions CI/CD

The generated `.github/workflows/deploy.yml` runs on every push to `main`:

```yaml
name: Deploy

on:
  push:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pip install -e ".[dev]" && pytest tests/ci/ -x

  build-push:
    needs: test
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - run: |
          docker build -t ghcr.io/${{ github.repository }}:${{ github.sha }} .
          docker push ghcr.io/${{ github.repository }}:${{ github.sha }}
          docker tag ghcr.io/${{ github.repository }}:${{ github.sha }} \
                     ghcr.io/${{ github.repository }}:latest
          docker push ghcr.io/${{ github.repository }}:latest

  deploy:
    needs: build-push
    runs-on: ubuntu-latest
    steps:
      - uses: webfactory/ssh-agent@v0.9.0
        with:
          ssh-private-key: ${{ secrets.DEPLOY_SSH_KEY }}
      - run: flask forge deploy server push && flask forge deploy server start
```

Add `DEPLOY_SSH_KEY` as a repository secret. The pipeline: runs tests, builds and pushes the Docker image to GitHub Container Registry, then deploys to your server — all without manual steps.

---

## Step 8 — Health checks and monitoring

The generated app registers a `/health` endpoint (see `monitoring.py`):

```python
@monitoring_bp.route('/health')
def health_check():
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.utcnow().isoformat(),
        'version': current_app.config.get('VERSION', '1.0.0')
    })
```

The `Dockerfile` includes a Docker-level health check:

```dockerfile
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1
```

The generated `nginx.conf` includes rate limiting on the login endpoint:

```nginx
limit_req_zone $binary_remote_addr zone=login:10m rate=5r/m;
location /login { limit_req zone=login burst=3 nodelay; ... }
```

All application logs write to stdout/stderr in JSON format, ready for any container log aggregator (CloudWatch, Loki, Datadog). Slow SQLAlchemy queries (>100ms) are logged as `WARNING` level automatically.

---

## Production checklist

Before going live, verify each item:

- [ ] `SECRET_KEY` is at least 32 random characters and set only via environment variable
- [ ] `FLASK_ENV=production` (disables debug mode)
- [ ] HTTPS enabled — TLS certificate installed, nginx redirects HTTP to HTTPS
- [ ] `WTF_CSRF_ENABLED = True` in config
- [ ] `FAB_UPDATE_PERMS = False` after the first boot (prevents permission churn on startup)
- [ ] Database backups scheduled (pg_dump cron job or managed backup service)
- [ ] `SESSION_COOKIE_SECURE = True` and `SESSION_COOKIE_HTTPONLY = True`
- [ ] Rate limiting active on login and API endpoints
- [ ] `/health` endpoint responding before routing traffic
- [ ] Log rotation configured (`/etc/logrotate.d/myapp`)
- [ ] Firewall allows only ports 22, 80, 443

---

## Next steps

- Tutorial 12 covers generating a desktop app using the same database
- `docs/deployment/production_deployment.md` contains the full nginx, gunicorn, and Kubernetes configurations
- `docs/deployment/cicd_setup.md` covers multi-environment (staging/production) pipeline configuration
