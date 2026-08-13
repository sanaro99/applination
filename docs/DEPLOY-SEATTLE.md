# Deploying Applination to Sanchit-Cloud (Seattle)

Target: `https://applination.sanchitarora.me`, gated by Cloudflare Access,
push-to-`main` CI/CD via GHCR + Watchtower.

```
Browser ──▶ Cloudflare edge ──▶ Cloudflare Access (email policy)
                                      │
                                      ▼
                          Tunnel "sanchit-seattle" ──▶ Traefik :443
                                      │
                    ┌─────────────────┴─────────────────┐
        /api /files /docs                        everything else
                    ▼                                    ▼
      applination-api  127.0.0.1:3002       applination-web  127.0.0.1:3001
      (FastAPI + LibreOffice + Chromium)    (Next.js standalone)
                    │
                    ▼
      /mnt/apps-pool/appconfig/applination/{config.yaml,master_data,data,output}
```

**Port registry:** `3001` applination-web, `3002` applination-api.
(`3000` luggist, `5432` postgres are taken.)

---

## Why two images and one hostname

The frontend is a client-rendered Next app — every page is `"use client"` and
all API calls happen in the browser. `NEXT_PUBLIC_API_BASE` is therefore
inlined into the JS bundle **at build time**; setting it on the NAS does
nothing. Serving both on one hostname and splitting by path prefix in Traefik
means the baked-in value is same-origin, which also removes CORS entirely and
avoids certifying a second subdomain.

---

## Step 0 — Prerequisites on the NAS

**Datasets → `apps-pool` → Add Dataset → `appconfig`** (skip if it exists).

Then, **System → Shell**:

```bash
sudo mkdir -p /mnt/apps-pool/appconfig/applination/{master_data,data,output,pgdata}
```

`pgdata` backs the Postgres container and must start empty — Postgres
initialises it on first boot and refuses to start against a directory it did
not create.

Do **not** create `config.yaml` as an empty file yet — see Step 1. If a
bind-mount source file is missing, Docker silently creates a *directory* in
its place and the container fails in a confusing way; if it exists but is
empty, the backend crashes at startup with a `KeyError` because
`load_config()` returns `{}`.

---

## Step 1 — Migrate your local data

From your Windows machine, with the NAS reachable over Tailscale:

```powershell
# Your NAS over Tailscale: <admin-user>@<machine>.<your-tailnet>.ts.net
# Find it with `tailscale status` on the NAS, or in the Tailscale admin console.
$NAS = "$env:NAS_HOST"
cd D:\gitgit\internship_bot

# Staging area you can write to without sudo
ssh $NAS "mkdir -p ~/applination-stage"

scp config.yaml                  "${NAS}:~/applination-stage/"
scp -r master_data               "${NAS}:~/applination-stage/"
scp -r data                      "${NAS}:~/applination-stage/"
scp -r output                    "${NAS}:~/applination-stage/"   # ~99 MB, 2138 files
```

Then **System → Shell** on the NAS:

```bash
sudo rsync -a ~/applination-stage/config.yaml   /mnt/apps-pool/appconfig/applination/
sudo rsync -a ~/applination-stage/master_data/  /mnt/apps-pool/appconfig/applination/master_data/
sudo rsync -a ~/applination-stage/data/         /mnt/apps-pool/appconfig/applination/data/
sudo rsync -a ~/applination-stage/output/       /mnt/apps-pool/appconfig/applination/output/

sudo chmod 600 /mnt/apps-pool/appconfig/applination/config.yaml
rm -rf ~/applination-stage

# Sanity: config.yaml must be a FILE with content, not a directory
ls -la /mnt/apps-pool/appconfig/applination/
```

If `output/` is slow over the tunnel, tar it first
(`tar czf output.tgz output` locally, scp one file, `tar xzf` on the NAS).

> `config.yaml` holds your live LLM API keys and Gmail app password. It never
> enters the image, the repo, or GHCR — `.gitignore` and `.dockerignore` both
> exclude it, and it reaches the container only as a bind mount.

---

## Step 2 — Write the app env file

**System → Shell** (must exist before deploying — compose fails on a missing
`env_file`):

```bash
sudo tee /mnt/apps-pool/appconfig/applination.env >/dev/null <<'EOF'
PYTHON_ENV=production
TZ=America/Los_Angeles
ALLOWED_ORIGINS=https://applination.sanchitarora.me
EOF
sudo chmod 600 /mnt/apps-pool/appconfig/applination.env
```

Everything else (provider keys, search prefs, inbox credentials) lives in the
bind-mounted `config.yaml` and is editable from the in-app **Setup** page.

---

## Step 3 — Build and publish the images

Merge `feat/deploy-seattle` into `main`. The workflow builds both images in a
matrix and pushes `latest` + `sha-xxxxxxx` to GHCR.

**After the first green run, make both packages public** (once each — the
default `GITHUB_TOKEN` cannot do this):

- https://github.com/users/sanaro99/packages/container/applination-api/settings
- https://github.com/users/sanaro99/packages/container/applination-web/settings

→ Danger Zone → Change visibility → **Public**.

The API image is large (~1.5 GB: LibreOffice Writer for docx→pdf, plus the
Playwright Chromium runtime for JS-rendered job pages). First build ~10 min;
later builds hit the GHA layer cache.

---

## Step 4 — Deploy

**Apps → Discover → ⋮ (top right) → Install via YAML**, name `applination`,
paste `deploy/applination.compose.yaml` from this repo.

Confirm both services reach **Running**, then verify from evidence:

```bash
# API is actually serving, not merely started
curl -fsS http://127.0.0.1:3002/api/health          # -> {"ok":true}

# Frontend is serving
curl -sSI http://127.0.0.1:3001 | head -1           # -> HTTP/1.1 200 OK

# Your real data mounted, not an empty seed
sudo docker exec $(sudo docker ps -qf name=applination-api) \
  sh -c 'ls -la /app/config.yaml /app/master_data | head'

# env_file resolved
sudo docker exec $(sudo docker ps -qf name=applination-api) env | grep PYTHON_ENV
```

---

## Step 5 — Traefik route

**System → Shell** — this is `deploy/traefik-applination.yml`:

```bash
sudo tee /mnt/apps-pool/traefik/applination.yml >/dev/null <<'EOF'
http:
  routers:
    applination-api:
      rule: "Host(`applination.sanchitarora.me`) && (PathPrefix(`/api`) || PathPrefix(`/files`) || PathPrefix(`/docs`) || Path(`/openapi.json`))"
      priority: 100
      entryPoints:
        - websecure
      service: applination-api
      tls:
        certResolver: letsencrypt
    applination-web:
      rule: "Host(`applination.sanchitarora.me`)"
      priority: 10
      entryPoints:
        - websecure
      service: applination-web
      tls:
        certResolver: letsencrypt
  services:
    applination-api:
      loadBalancer:
        servers:
          - url: "http://127.0.0.1:3002"
        responseForwarding:
          flushInterval: "100ms"
    applination-web:
      loadBalancer:
        servers:
          - url: "http://127.0.0.1:3001"
EOF
```

Hot-reloads immediately. **Read the Traefik logs right away** — a bad file
logs `EntryPoint doesn't exist` or `nonexistent certificate resolver` rather
than failing loudly.

---

## Step 6 — Tunnel route

Cloudflare Zero Trust → **Networks → Tunnels → `sanchit-seattle` → Routes →
Add route → Published application**:

| Field | Value |
|---|---|
| Subdomain | `applination` |
| Domain | `sanchitarora.me` |
| Service type | **HTTPS** |
| URL | `localhost:443` |
| Additional application settings → TLS → **Origin Server Name** | `applination.sanchitarora.me` |

The Origin Server Name is required — without it the tunnel can't validate
Traefik's per-host certificate and you get a 526.

---

## Step 7 — Cloudflare Access (do this before you load the URL)

The app has no authentication of its own. Anything that reaches it can spend
your LLM credits, read your resume and Gmail-synced application history, and
edit `config.yaml` — which displays your API keys. Access is the only thing
standing in front of it.

Zero Trust → **Access → Applications → Add an application → Self-hosted**:

- **Name** `Applination`
- **Public hostname** `applination.sanchitarora.me`
- **Session duration** 1 month (it's a daily-use tool)

Add a policy:

- **Name** `Owner only`
- **Action** Allow
- **Include** → *Emails* → `iamsacaro@gmail.com`

Under **Login methods**, One-time PIN is enabled by default and is enough;
adding Google gives you one-click sign-in.

Two settings that matter for this app specifically:

1. **Do not enable "Bypass" for any path.** `/api` is the whole application
   surface — bypassing it defeats the entire policy.
2. The SSE run stream and long tailoring requests run for minutes. Access
   doesn't interrupt an established connection, but keep session duration
   generous so you aren't re-authenticating mid-run.

---

## Step 8 — Verify end to end

Wait 30–60 s for first certificate issuance, then load
`https://applination.sanchitarora.me`.

1. Cloudflare Access challenges you → sign in
2. Dashboard loads and shows your **existing** applications (proof the
   bind-mounted `app.db` is live, not a fresh one)
3. **Setup → Providers → Test** succeeds → migrated keys work
4. Start a **dry run** → the progress stream updates live → SSE survives
   Cloudflare + Traefik
5. Open an existing application → PDF preview renders → the `/files` static
   mount is routed correctly
6. Generate one document → confirm a `.pdf` appears next to the `.docx` →
   LibreOffice conversion works in-container

---

## Upgrading a live instance from SQLite to Postgres

One-time cutover for an instance already running the pre-Postgres build. The
old `data/app.db` is **never deleted** — it is left in place as the rollback
path. Budget ~15 minutes of downtime.

**1. Snapshot first.** Datasets → `apps-pool/appconfig` → Snapshots → Add.
This is the thing that makes every later step reversible.

**2. Add the database settings** to `/mnt/apps-pool/appconfig/applination.env`:

```bash
# openssl rand -base64 32   — generate, don't invent
POSTGRES_PASSWORD=<generated>
DATABASE_URL=postgresql+psycopg://applination:<generated>@applination-db:5432/applination
```

Percent-encode the password in `DATABASE_URL` if it contains `@ : / ?`.

**3. Create the pgdata directory** (must be empty):

```bash
sudo mkdir -p /mnt/apps-pool/appconfig/applination/pgdata
```

**4. Update the app YAML** from `deploy/applination.compose.yaml` (it now has
the `applination-db` service) and Save. Postgres initialises, then the API
container runs `alembic upgrade head` on start and creates the schema.

**5. Confirm the schema exists and is empty:**

```bash
sudo docker compose -p applination exec applination-db \
  psql -U applination -d applination -c "\dt"
# expect: alembic_version, application, chatmessage, chatsession,
#         rankedjob, run, savedanswer, setting
```

**6. Copy the data in.** Dry run first — it writes nothing:

```bash
sudo docker compose -p applination exec applination-api \
  python scripts/sqlite_to_postgres.py --sqlite /app/data/app.db --dry-run
```

Check the reported per-table counts against what you expect, then run it for
real by dropping `--dry-run`. The script refuses to touch a non-empty target,
so it cannot double-copy by accident.

**7. Verify the counts match**, comparing against the SQLite source:

```bash
sudo docker compose -p applination exec applination-db \
  psql -U applination -d applination -c \
  "SELECT 'run' t, count(*) FROM run
   UNION ALL SELECT 'application', count(*) FROM application
   UNION ALL SELECT 'rankedjob', count(*) FROM rankedjob
   UNION ALL SELECT 'chatsession', count(*) FROM chatsession
   UNION ALL SELECT 'chatmessage', count(*) FROM chatmessage
   UNION ALL SELECT 'savedanswer', count(*) FROM savedanswer
   UNION ALL SELECT 'setting', count(*) FROM setting;"
```

**8. Restart the API** and load the app. Applications, run history, and Coach
chats should look exactly as before, and a **new** run must be creatable —
that last check is what proves the id sequences were fast-forwarded correctly.

**Rollback:** roll back to the snapshot from step 1, or simply redeploy the
previous image tag — `data/app.db` is untouched and still authoritative for
the old build.

---

## Ongoing

**Deploy:** `git push origin main` → Actions builds both images → Watchtower
picks up new digests within ~120 s. Roughly 2–5 min end to end.

**Rollback:** find the good `sha-xxxxxxx` in GHCR, pin it as the image tag in
the app's YAML, Save. Pinning also stops Watchtower from moving it.

**Change a runtime env var:** edit `/mnt/apps-pool/appconfig/applination.env`,
then **Apps → applination → Restart**. Editing the file alone does nothing.

**Change `NEXT_PUBLIC_API_BASE`:** that one is build-time. Set an Actions
*variable* of that name and re-run the workflow — an app restart won't help.

**Back up:** add a periodic ZFS snapshot task on the `appconfig` dataset.
`pgdata/` is your entire application history and `master_data/` is your resume
source of truth; neither exists anywhere else once you stop running locally.

A filesystem snapshot of a running Postgres is crash-consistent, which
Postgres recovers from cleanly — but for a backup you can actually inspect and
restore selectively, also take a logical dump:

```bash
sudo docker compose -p applination exec applination-db \
  pg_dump -U applination -d applination --format=custom \
  > /mnt/apps-pool/appconfig/applination/backups/app-$(date +%F).dump
```

---

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| API container restarts, `KeyError: 'output'` | `config.yaml` is empty or a directory — re-copy it (Step 1) |
| `config.yaml` shows as a directory in the container | Bind source didn't exist when the app first started; remove the dir, copy the real file, redeploy |
| Frontend loads, every API call fails / CORS error | Traefik `/api` router priority lost to the catch-all; confirm `priority: 100` |
| Frontend calls `127.0.0.1:8000` | Image built without the build arg — set the Actions variable and rebuild |
| 502, Traefik `no available server` | Container not listening on 3001/3002; check `docker ps` port bindings |
| 502, nothing in Traefik logs | Tunnel service must be `https://localhost:443` |
| 526 | Missing Origin Server Name, or cert not issued yet |
| Run progress never updates | SSE buffering — confirm `flushInterval` is in the service block |
| Documents generate as `.docx` only | LibreOffice missing from the image; check `soffice --version` in the container |
| Single-job URL wizard extracts nothing | Chromium missing; `python -m playwright install chromium` in the container to confirm |
| Image pull fails | GHCR package still private (Step 3) |
| API restarts, `database has no Alembic revision` | `alembic upgrade head` did not run — check the API container's start logs for a migration failure |
| API restarts, `connection refused` to `applination-db` | `DATABASE_URL` host must be `applination-db` (the service name), not `localhost` |
| API starts but every query 500s | `DATABASE_URL` password disagrees with `POSTGRES_PASSWORD`, or contains an unencoded `@ : / ?` |
| Postgres won't start after a version bump | `pgdata` was initialised by an older major version; restore the snapshot and pin the previous image tag |
| New run fails on a duplicate primary key | Sequences were not fast-forwarded — re-run the `setval` block at the end of `scripts/sqlite_to_postgres.py` |
