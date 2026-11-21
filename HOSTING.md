# Hosting the GoodSAM → REDCap app

For IT. Describes what the web app needs so it can be hosted centrally instead of on a
staff member's PC. Questions about the app itself: [app owner – add name and contact].

## What it is

A small Python web app (`app.py`, built with [Streamlit](https://streamlit.io)) that:

1. reads the latest record from a **REDCap** project (to know where the last upload stopped),
2. downloads alert and responder data from the **GoodSAM reporting API**,
3. reshapes it into REDCap's import format, and
4. uploads it to REDCap.

Staff open it in a browser and press **Daily run**. It also shows responders who asked for a welfare
check. It is used by a handful of people, about once a day.

```
Staff browser ──HTTPS──▶  App (this server)  ──HTTPS──▶  goodsamgateway.org        (GoodSAM API)
                                              ──HTTPS──▶  nswa-redcap.ambulance.nsw.gov.au (REDCap API)
```

## Server requirements

| | |
|---|---|
| **Runtime** | Python 3.10+ (tested on 3.13–3.15), **or** the included `Dockerfile` (tested). Linux or Windows. |
| **Size** | 1 vCPU, 1–2 GB RAM, ~1 GB disk. No database. |
| **Inbound** | Staff browsers → app on port **8501** (HTTP). Put it behind your usual HTTPS reverse proxy / load balancer. **WebSockets must be allowed** (Streamlit uses them; without them the page loads but never responds). |
| **Outbound** | HTTPS 443 to `goodsamgateway.org` and `nswa-redcap.ambulance.nsw.gov.au`. See *Network* below. |
| **Timezone** | Not needed: the app uses `Australia/Sydney` itself. |
| **State** | None worth backing up. Per-session temporary files only (see *Data*). |

## Network: the two things that currently break it

1. **GoodSAM through Zscaler.** From work PCs the TLS handshake to `goodsamgateway.org` is dropped by
   Zscaler after `CONNECT` succeeds (`schannel: failed to receive handshake`). The server needs
   `goodsamgateway.org:443` allowed for non-browser traffic, ideally with **SSL inspection bypassed**
   for that host.
2. **REDCap must not go through the web proxy.** Through the NSW Health proxy, REDCap's API returns a
   bare `403 Forbidden`. Direct connections work. The app already adds the REDCap host to `NO_PROXY`.
   REDCap's server also **rejects overseas addresses** (Streamlit Community Cloud in the US was refused;
   Australian connections are accepted). An Australian-hosted or internal server is fine. If REDCap
   ever needs to allow-list the server, it will need a **fixed outbound IP**.

The app has a built-in **🔧 Connection check** (sidebar) that tests both services from the server with a
fake token, so you can confirm the network before anyone uses it.

## Settings and secrets

Provide these as environment variables (or a Streamlit `secrets.toml`), from your secret store:

| Name | What | Notes |
|---|---|---|
| `GOODSAM_USERNAME` | GoodSAM API **client ID** | Create a dedicated API client for this server in GoodSAM (Manage → Integrations → API; Read on Reporting and Responders only). Clients expire after 12 months by default. |
| `GOODSAM_PASSWORD` | GoodSAM API **client secret** (`gsk_…`) | Shown once when created. |
| `REDCAP_API_URL` | `https://nswa-redcap.ambulance.nsw.gov.au/redcap/api/` | |
| `REDCAP_API_TOKEN` | REDCap project API token | Needs API **export and import** rights on the project. High privilege: it can write to the project. |
| `APP_PASSWORD` | Shared password for the page | Interim access control (see *Access*). Required if the page is reachable by more than the intended users. |

Example `goodsam.env` for Docker (keep it out of source control):
```
GOODSAM_USERNAME=...
GOODSAM_PASSWORD=gsk_...
REDCAP_API_URL=https://nswa-redcap.ambulance.nsw.gov.au/redcap/api/
REDCAP_API_TOKEN=...
APP_PASSWORD=...
```

## Running it

**Docker (recommended):**
```bash
docker build -t goodsam-etl .
docker run -d --name goodsam-etl -p 8501:8501 --env-file goodsam.env --restart unless-stopped goodsam-etl
```
The image runs as a non-root user, contains no data or secrets, and has a health check
(`/_stcore/health`).

**Without Docker:**
```bash
pip install -r requirements-app.txt
python -m streamlit run app.py --server.port 8501 --server.address 0.0.0.0
```
Run it as a service (systemd on Linux; a scheduled task or NSSM service on Windows) with the settings above
in its environment.

**Updating:** pull the `main` branch of the GitHub repository, rebuild/restart. The page shows the app
version under the title.

## Access

- **Now:** one shared `APP_PASSWORD`. There are no individual accounts and no record of who pressed
  Upload.
- **Better:** put it behind single sign-on (Microsoft Entra ID), either at the reverse proxy
  (e.g. Azure App Service authentication, an authenticating proxy) or with Streamlit's built-in OIDC
  login. That gives named users, and the app password can then be removed.
- Limit access to the staff who do uploads and welfare follow-up.

## Data

- Processes **health and personal information**: responder names, phone numbers, emails, clinical
  details, welfare requests.
- Nothing is stored long term. Each browser session writes to its own temporary folder, which is
  deleted on **Clear files** or automatically after 12 hours. Raw API dumps are off by default.
- Users can download the generated CSVs (REDCap import, responder list, welfare list).
- The app's own log shows record IDs and counts, not names or contact details. Server logs contain no
  personal data.
- GoodSAM certificate verification is currently disabled in the code (`ssl=False`, TLS is still used);
  can be re-enabled once the network path is stable.

## Operational notes

- **One daily run at a time.** The app doesn't lock, so two people pressing **Daily run** together could
  upload the same day twice. Agree who does it, or schedule it (below).
- **Possible next step: run it on a schedule.** The upload could run automatically each night (cron /
  Task Scheduler) with only the welfare list needing a person. That would need a small headless script;
  the logic already exists.
- If GoodSAM login fails repeatedly, GoodSAM blocks the IP for 4 hours. The app deliberately doesn't
  retry logins.

## Files

| File | Purpose |
|---|---|
| `app.py` | The web app |
| `GS2RCAPI.py` | The processing engine (also usable from the command line) |
| `requirements.txt`, `requirements-app.txt` | Python packages |
| `Dockerfile`, `.dockerignore` | Container build |
| `.streamlit/config.toml` | App settings (no secrets) |
| `CLAUDE.md`, `TODO.md` | Developer notes and current issues |
