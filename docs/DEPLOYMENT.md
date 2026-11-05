# Deploying Applination

This guide uses example hostnames, paths, and account names. Replace them with values for your installation before deploying. Keep your actual environment file, access-policy addresses, and infrastructure inventory outside the repository.

The [technical guide](TECHNICAL.md) covers local development and application configuration. The templates under `deploy/` describe a container installation with PostgreSQL, an internal Redis cache, a FastAPI API, and a Next.js frontend.

## Architecture

```text
Browser -> HTTPS reverse proxy -> /api, /docs, /openapi.json -> API
                              -> other paths             -> frontend
API -> PostgreSQL + internal Redis
API -> persistent per-account files under /app/data
```

The API and frontend share a public origin, for example `https://applination.example.com`. This lets the browser send session cookies to the API. `NEXT_PUBLIC_API_BASE` is empty by default, so browser requests use that origin. If you override it, it is a frontend build-time setting and requires rebuilding the image.

The sample compose file binds the frontend to `127.0.0.1:3001` and API to `127.0.0.1:3002`. These are example ports: select unused ports on your host and update the reverse proxy to match. PostgreSQL and Redis are not published to host ports.

## 1. Prepare persistent storage

Install Docker with Compose, or use a container platform that accepts Compose YAML. Run the following from your repository checkout on the deployment host:

```bash
sudo mkdir -p /srv/applination/{data,pgdata,backups,scripts}
sudo cp deploy/applination.env.example /srv/applination/applination.env
sudo chmod 600 /srv/applination/applination.env
```

`/srv/applination` is an example storage root. Change every corresponding `env_file` and bind-mount path in the compose template if you choose another directory. On a NAS, use your own dataset mount path and grant the containers access to it.

- `data/` holds each account's config, profile, and generated documents under `users/<id>/`.
- `pgdata/` holds PostgreSQL data and must start empty for a new installation.
- Repository-owned writing guidelines and templates stay in the image; do not mount over `/app/master_data` on a current installation.

## 2. Configure the environment

Edit `/srv/applination/applination.env` privately. Set:

| Variable | Purpose |
|---|---|
| `ALLOWED_ORIGINS` | Your public HTTPS origin, for example `https://applination.example.com` |
| `TZ` | Your chosen timezone; the template uses `UTC` |
| `POSTGRES_PASSWORD` | A generated database password |
| `DATABASE_URL` | The matching password and internal service host `applination-db` |
| `APPLINATION_SECRET_KEY` | The Fernet key used to encrypt stored provider keys and Gmail tokens |
| `REDIS_PASSWORD` | A separate generated password for the internal cache |
| `MAX_CONCURRENT_RUNS` | Maximum concurrent pipeline runs across accounts |

Generate database and Redis passwords separately:

```bash
openssl rand -base64 32
```

Generate the encryption key using a Python environment with the project dependencies installed:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Percent-encode reserved characters in the password portion of `DATABASE_URL`. Keep the encryption key in a separate secure backup: without the original key, restored provider credentials and Gmail tokens cannot be decrypted.

Provider keys and user preferences are entered through the app and stored per account. Leave `ALLOW_ENV_API_KEYS` unset for multi-user installations.

## 3. Build or obtain container images

The repository's [image workflow](../.github/workflows/deploy-image.yml) builds API and frontend images and publishes them under the repository owner's GHCR namespace. It publishes `latest` and commit-specific tags. Configure registry access for your deployment host, or make the packages public if that suits your installation.

Replace `your-org` in `deploy/applination.compose.yaml` with your image namespace. Prefer a commit-specific tag when you need a reproducible deployment. Check that both images are available before proceeding.

The API image includes LibreOffice for PDF conversion and Chromium for job pages that require a browser. The frontend image uses Next.js standalone output.

## 4. Start the services

```bash
sudo docker compose -f deploy/applination.compose.yaml up -d
sudo docker compose -f deploy/applination.compose.yaml ps
sudo docker compose -f deploy/applination.compose.yaml logs --tail=100 applination-api
```

On a NAS platform, import the customized compose YAML through its app installation interface instead. The environment file and mount sources must already exist.

The API entrypoint runs `python -m alembic upgrade head` before serving requests. Check its logs for migration failures. Verify both services locally:

```bash
curl -fsS http://127.0.0.1:3002/api/health
curl -sSI http://127.0.0.1:3001
```

For maintenance commands below, `docker compose exec` assumes the services were started with this compose file. On platforms that manage Compose projects themselves, use their container shell or resolve the API container by its service name instead.

The commands in this guide use `sudo docker compose` because the environment file is root-owned and readable only by root. If you choose a dedicated deployment user instead, grant that user ownership of the private environment file and storage directories while keeping the file mode at `600`.

## 5. Configure HTTPS and routing

Customize [the Traefik template](../deploy/traefik-applination.yml) for your hostname, ports, entrypoint, and certificate resolver. Install it in your reverse proxy's configured dynamic-file directory. The example hostname is `applination.example.com`; it is not a live deployment address.

Route `/api`, `/docs`, and `/openapi.json` to the API, and other paths to the frontend. Generated documents are authenticated API responses under `/api/files`; there is no public static document mount. Give the API router a higher priority than the frontend catch-all and preserve streamed responses for run progress.

If you use a tunnel, configure your own tunnel and route your chosen hostname to the proxy. For an HTTPS origin, the origin server name must match the proxy's certificate. Keep tunnel credentials and private host inventory outside Git.

Applination has its own account authentication. An additional identity gateway is optional. If you use one, configure your own authorized email addresses or groups privately, and account for the local worker and browser extension when deciding which noninteractive clients can connect. Never copy real policy addresses into public examples.

## 6. Verify the installation

1. Open your configured public HTTPS hostname and create an account or sign in.
2. Complete onboarding and test your selected provider from Config.
3. Start a dry run and verify that progress updates stream through the proxy. Scoring can incur provider charges.
4. Generate materials for a selected job, then verify Word downloads and PDF previews.
5. Sign out and verify that authenticated API endpoints reject unauthenticated requests.

If you advertise the shared demo, seed it and configure its reset schedule as described below.

## Migrating an older installation

Back up the database, files, and encryption key before migration. Keep the old installation available for rollback until you have verified the new one.

### SQLite to PostgreSQL

These steps apply only to an older SQLite installation and a new, empty PostgreSQL target. Do not downgrade or copy into a database containing current account data.

1. Retain the original SQLite file under `/app/data/app.db`.
2. Start PostgreSQL and the API so the entrypoint creates the current schema.
3. With the target still empty, stop public traffic and downgrade to the baseline revision for the copy:

   ```bash
   sudo docker compose -f deploy/applination.compose.yaml exec applination-api \
     python -m alembic downgrade 314cc8e80422
   ```

4. Preview the import, check the row counts, then import:

   ```bash
   sudo docker compose -f deploy/applination.compose.yaml exec applination-api \
     python scripts/sqlite_to_postgres.py --sqlite /app/data/app.db --dry-run
   sudo docker compose -f deploy/applination.compose.yaml exec applination-api \
     python scripts/sqlite_to_postgres.py --sqlite /app/data/app.db
   sudo docker compose -f deploy/applination.compose.yaml exec applination-api \
     python -m alembic upgrade head
   ```

5. Set the adopted account's password privately using `scripts/set_password.py` inside the API container. Compare database row counts with the source and verify that a new run can be created.

The baseline copy is necessary because the legacy SQLite rows predate required `user_id` columns. Upgrading afterward adopts those rows into the owner account. The copy script refuses a nonempty target and leaves the source SQLite file intact.

### Legacy files to per-account storage

If the older installation has separate `config.yaml`, `master_data/`, and `output/` mounts, keep them visible while migrating:

```bash
sudo docker compose -f deploy/applination.compose.yaml exec applination-api \
  python scripts/migrate_to_multiuser.py --dry-run
sudo docker compose -f deploy/applination.compose.yaml exec applination-api \
  python scripts/migrate_to_multiuser.py
```

Review the dry-run output first. The migration moves files into `data/users/<owner-id>/` and rewrites document paths. Afterward, switch the API to the single `/app/data` mount in the current template, restart, and confirm that existing documents load. For rollback, restore the matching database and filesystem backup with the previous image version.

## Updates and backups

Pull the chosen image tags and recreate the services:

```bash
sudo docker compose -f deploy/applination.compose.yaml pull
sudo docker compose -f deploy/applination.compose.yaml up -d
```

The template labels API and frontend services for optional Watchtower updates. Watchtower is not installed by the template. PostgreSQL and Redis are excluded from those unattended updates. Pin image tags and disable automatic updates if you need manual releases.

Runtime environment changes require recreating the affected containers. Frontend `NEXT_PUBLIC_*` changes require rebuilding the frontend image. PostgreSQL major-version changes require an explicit migration plan; do not point a new major version at an older data directory.

Back up both the per-account files and PostgreSQL, and keep the encryption key separately. Create a logical database backup:

```bash
sudo install -m 600 /dev/null /srv/applination/backups/database.dump
set -o pipefail
sudo docker compose -f deploy/applination.compose.yaml exec -T applination-db \
  pg_dump -U applination -d applination --format=custom \
  | sudo tee /srv/applination/backups/database.dump > /dev/null
```

Use private, dated backup locations in your operational configuration. Test a restore before relying on the backup. Redis is a disposable, memory-only cache; it does not need a persistent backup. If Redis is unavailable, the API can continue without caching.

## Shared demo reset

The demo uses fictional data and simulated AI responses. It is writable, so restore it on a schedule if you advertise it publicly. Verify the reset manually first:

```bash
sudo docker compose -f deploy/applination.compose.yaml exec applination-api \
  python scripts/seed_demo.py
sudo cp scripts/seed_demo_cron.sh /srv/applination/scripts/
sudo chmod 755 /srv/applination/scripts/seed_demo_cron.sh
```

Schedule the copied script with your host's scheduler. For example, this cron entry resets the demo daily at 04:10 in the host's configured timezone:

```cron
10 4 * * * /srv/applination/scripts/seed_demo_cron.sh >> /var/log/applination-demo-seed.log 2>&1
```

Set `DEMO_ENABLED=0` and recreate the API to disable demo login. Remove the reset schedule as well.

## Troubleshooting

| Symptom | Check |
|---|---|
| Image pull fails | Image namespace/tag and registry credentials or package visibility |
| API cannot connect to PostgreSQL | `DATABASE_URL` uses `applination-db`, and its encoded password matches `POSTGRES_PASSWORD` |
| API reports missing schema or revision | Entrypoint logs and `python -m alembic upgrade head` |
| Login succeeds but requests return 401 | UI and API use the same origin and the proxy routes `/api` to the API |
| Run progress does not update | Proxy routing, buffering, timeouts, and SSE forwarding |
| Documents generate only as Word files | LibreOffice is present and PDF conversion is enabled |
| Existing document previews return 404 | Legacy-file migration and the `/app/data` mount |
| Provider keys cannot be decrypted | The configured encryption key matches the key used when storing them |
| Browser uses a different API hostname | Frontend build arguments; runtime environment edits cannot change bundled values |
| PostgreSQL refuses a data directory | Mount parent is `/var/lib/postgresql` for the example PostgreSQL 18 image; the data version matches the image major version |
| Calendar subscription fails | Use the signed feed link from the app rather than the bare API path |
