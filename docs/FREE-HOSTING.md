# Free hosting

This guide puts Applination on the internet without a hosting bill. It reuses the one-command Docker setup from the [technical guide](TECHNICAL.md#option-a-docker-one-command), so the steps are the same on a laptop and on a cloud VM. For a long-lived installation behind your own reverse proxy, see the [deployment guide](DEPLOYMENT.md).

Free-tier terms change often. The limits below were checked in November 2026 against each provider's own documentation. Re-check them before you rely on them.

## What the app needs from a host

Applination is not a static site, so it fits fewer free tiers than most apps do. A host has to provide:

- **Persistent disk.** Generated resumes and cover letters, profiles, and the encryption key live on disk under `data/`. A host that wipes the filesystem on restart loses them.
- **About 2 GB of memory.** The API renders PDFs with LibreOffice and opens job pages in Chromium, alongside Postgres and the Next.js server.
- **No forced sleep.** A run fetches and scores jobs for several minutes in a background thread and streams progress to the browser. A host that suspends idle services stops the run.
- **A database that does not expire.**

## Recommended: an Oracle Cloud Always Free VM

Oracle's Always Free tier includes an Arm (Ampere A1) VM that meets all four needs. As of November 2026, [Oracle's documentation](https://docs.oracle.com/en-us/iaas/Content/FreeTier/resourceref.htm) lists:

| Resource | Always Free allowance |
|---|---|
| Ampere A1 compute | 2 OCPUs and 12 GB of memory in total, as one VM or two smaller ones |
| Block storage | 200 GB in total, including boot volumes |
| Outbound data | 10 TB per month |

Oracle halved the A1 allowance from 4 OCPUs and 24 GB in mid-2026 ([InfoQ](https://www.infoq.com/news/2026/07/oracle-cloud-free-tier-limits/)). 2 OCPUs and 12 GB is still plenty for Applination and a handful of users.

Know these limits before you start:

- **Sign-up asks for a payment card** for identity verification. An Always Free account is not charged unless you upgrade it.
- **Arm capacity can run out** in popular regions. If creating the VM fails with an out-of-capacity error, try another availability domain or try again later. Your home region cannot be changed after sign-up.
- **Idle instances can be reclaimed.** Oracle may reclaim an Always Free VM whose CPU, network, and memory use each stay under 20% over seven days. Applination idles most of the day, so this applies. A scheduled daily run adds activity, but does not guarantee the VM counts as active. Upgrading the account to Pay As You Go is the common way around reclamation; Always Free resources stay free there, but anything you create beyond the free limits is billed, so set a budget alert if you upgrade.
- **Stay within the free shapes.** Use `VM.Standard.A1.Flex` with at most 2 OCPUs and 12 GB, and a boot volume no larger than you need.

### 1. Create the VM

1. Sign up for an Oracle Cloud account and open **Compute → Instances → Create instance**.
2. Choose an **Ubuntu 24.04** image (the aarch64 build) and the **VM.Standard.A1.Flex** shape with 2 OCPUs and 12 GB of memory.
3. Add your SSH public key and keep the default public subnet.
4. Leave the firewall closed. The tunnel in step 3 connects outward, so the VM needs no open inbound port other than SSH.

### 2. Install Docker and the app

SSH into the VM, then run:

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$USER"    # log out and back in afterwards

git clone https://github.com/sanaro99/applination.git
cd applination
cp .env.example .env
```

Edit `.env` and set at least:

```ini
PUBLIC_URL=https://applination.example.com
POSTGRES_PASSWORD=<output of: openssl rand -hex 24>
CLOUDFLARE_TUNNEL_TOKEN=<from step 3>
```

Set `POSTGRES_PASSWORD` before the first start. The database is created with it, and changing it later means recreating the database volume.

### 3. Give it an HTTPS address with a Cloudflare Tunnel

A [Cloudflare Tunnel](https://developers.cloudflare.com/tunnel) gives the app an HTTPS hostname with no open ports and no certificate to manage. It is free, and needs a domain whose DNS is on Cloudflare (the free plan works).

1. In the Cloudflare dashboard, open **Zero Trust → Networks → Tunnels** and create a tunnel of type **Cloudflared**.
2. Copy the token from the install command it shows, the long string after `--token`, into `CLOUDFLARE_TUNNEL_TOKEN` in `.env`.
3. Add a **public hostname**: your chosen subdomain, service type **HTTP**, URL **`web:3000`**.

Route everything to `web:3000`. The web container forwards `/api` to the API itself, including the live progress stream, so the tunnel needs only one route.

### 4. Start it

```bash
docker compose --profile tunnel up -d --build
docker compose ps
```

The first build takes ten minutes or more on a 2-OCPU VM. When `docker compose ps` shows the services running, open your hostname, create an account, and complete onboarding.

Check that it works end to end:

1. Sign up, then test your AI provider from **Config**.
2. Start a dry run and watch progress update live.
3. Generate documents for one job and open both the Word and PDF versions.

## Alternative: your own computer plus the tunnel

If you do not want a cloud account, run the same stack on your laptop and add the tunnel. Follow steps 3 and 4 above on your computer, with `PUBLIC_URL` and `CLOUDFLARE_TUNNEL_TOKEN` in `.env`. The public address works only while the computer is on and Docker is running. On Windows, `scripts\start.cmd` starts the stack without the tunnel; run `docker compose --profile tunnel up -d` once to add it.

For use only on your own computer, you need neither: `docker compose up -d --build` and http://localhost:3000 are enough.

## Hosts that do not fit

Free plans on app platforms look simpler, but miss at least one of the needs above. For example, [Render's free tier](https://render.com/docs/free) spins services down after 15 minutes without traffic, has no persistent disk, and deletes free Postgres databases 30 days after creation. Splitting the app across a frontend host, a container host, and a managed database adds three accounts and still leaves generated documents with nowhere durable to live.

## Running it

**Update** to the latest code:

```bash
cd applination
git pull
docker compose --profile tunnel up -d --build
```

Migrations run automatically when the API starts.

**Back up** the database and files, and keep a copy off the VM:

```bash
docker compose exec -T db pg_dump -U applination -d applination --format=custom > applination.dump
tar czf applination-data.tgz data/
```

`data/` contains `data/secret.key`. Without that key, restored API keys and Gmail connections cannot be decrypted, and every user must enter them again.

**Restore** onto a fresh install, including from an older installation:

```bash
docker compose up -d db
docker compose exec -T db pg_restore -U applination -d applination --clean --if-exists < applination.dump
tar xzf applination-data.tgz            # restores data/, including data/secret.key
docker compose --profile tunnel up -d --build
```

If the old installation set `APPLINATION_SECRET_KEY` as an environment variable instead, write that value into `data/secret.key` or set it in `.env` before starting the API.

**Reset the shared demo** nightly if you keep it enabled. Add a cron entry on the VM:

```cron
10 4 * * * cd /home/ubuntu/applination && docker compose exec -T api python scripts/seed_demo.py >> demo-seed.log 2>&1
```

Set `DEMO_ENABLED=0` in `.env` and run `docker compose up -d` to turn the demo off.

**Read logs** with `docker compose logs -f api` or `docker compose logs -f web`.
