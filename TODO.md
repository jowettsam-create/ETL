# GoodSAM ETL – To-do list

## In progress
- [ ] **Streamlit web app (`app.py`) – stopgap for PCs that can't run the exe.**
  - Found 21 Nov 2026 (Connection check in the app):
    - **Streamlit Community Cloud** (US servers): GoodSAM ✅, REDCap ❌ – REDCap's own server returns a bare
      "403 Forbidden" to overseas servers. Streamlit Cloud's outbound IPs change without notice, so allowlisting
      isn't viable. Cloud can still build the CSV; import it via REDCap's Data Import Tool (DD/MM/YYYY).
    - **Home internet (Australia):** REDCap API ✅ (answers "You do not have permissions to use the API" to a fake
      token). GoodSAM ✅.
    - **Work PC:** REDCap ✅ from Python direct; app versions before 2026.11.21-5 sent REDCap through the
      NSW Health proxy when `HTTPS_PROXY` was set → bare 403 (fixed: REDCap host added to `NO_PROXY`).
      GoodSAM ❌ via Zscaler – workaround: export Alerts/Responders CSVs in the browser → app CSV mode.
  - [x] Full Daily run works on Sam's private PC (22 Nov 2026: 68 records uploaded).
  - **Current workaround (22 Nov 2026):** app runs on Sam's private PC (`start_app.bat`, credentials + `APP_PASSWORD`
    in `%USERPROFILE%\.streamlit\secrets.toml`) and is shared through **ngrok** at
    `https://armory-simmering-entitle.ngrok-free.dev`. Works from **phones/tablets on mobile data**.
    **Zscaler blocks ngrok on work PCs and work Wi-Fi** (deliberate – don't try other tunnels).
    Requires the PC on/awake with both the app and ngrok running. One person does the daily upload.
  - [ ] Work PCs: either run the app locally with GoodSAM CSV exports (browser) → Custom date range → CSV mode,
        or raise the IT ticket to allow `goodsamgateway.org` through Zscaler (ticket text drafted in chat 22 Nov).
  - [ ] Cloud app (goodsamfix.streamlit.app): keep sharing private and `APP_PASSWORD` set; don't use Daily run there.

- [ ] **Self-hosted website on a Raspberry Pi (free, permanent fix for "go to a website and upload").**
  - Pi 4/5 (2 GB+), Raspberry Pi OS 64-bit, on home internet in Australia (REDCap + GoodSAM both reachable).
  - Run `app.py` as a systemd service (start at boot, restart on crash).
  - Public link via a free tunnel: **ngrok** (one permanent free `*.ngrok-free.app` address) or Cloudflare Tunnel
    (quick tunnels are free but the address changes; permanent needs a domain).
  - `APP_PASSWORD` mandatory; credentials in `.streamlit/secrets.toml` on the Pi only.
  - Check a work PC's browser can open the tunnel link (Zscaler may block tunnel domains).
  - Ask Claude for: Pi setup script + service file, ngrok steps, one-page user instructions.

- [ ] **Connection problems on other computers.** Fixes are in release 2026.11.15:
  - Windows certificate store via `truststore`, for networks that intercept HTTPS
  - GoodSAM download now follows the system proxy settings
  - Output files saved next to the exe instead of a temp folder
  - Full error details shown in the console

  Works on Sam's PC (both old and new builds). Still to test on the computers that failed.

  **Found 15 Nov 2026:** on a colleague's work computer, Windows SmartScreen blocked the exe
  ("Windows protected your PC", unknown publisher). **Fix:** right-click the zip → Properties →
  tick Unblock → OK, *then* extract. That worked. Put this step in the instructions for everyone.
  Longer term: sign the exe (ask IT whether they have a code-signing certificate).
  If one still fails, get the console output. If it's an intermittent drop
  ("The specified network name is no longer available"), add automatic retries to the GoodSAM download.

  **Found 17 Nov 2026 – cause identified:** work computers reach the internet through the NSW Health
  proxy, configured by a PAC file (`http://asnsw.sse.nswhealth.net/proxy.pac`, `ProxyEnable=0`).
  Python can't read PAC files, so "follows the system proxy settings" in 2026.11.15 finds nothing and
  connects directly; the firewall then drops it ("network name is no longer available").
  `Test-NetConnection` passing is misleading – the TCP handshake works, the connection is cut afterwards.
  The machine's WinHTTP proxy is `apps.swproxy.nswhealth.net:40111` (bypass `<local>;*.nswhealth.net`).
  - [x] `GS2RCAPI.py`: added `_read_winhttp_proxy()` / `get_proxy_candidates()`; the GoodSAM fetch now tries
        `GOODSAM_PROXY` env var → env/IE proxy → WinHTTP proxy → direct, logging each attempt. Not yet released.
  - [ ] On a work computer, test the proxy first:
        `curl.exe -v -k --proxy http://apps.swproxy.nswhealth.net:40111 https://goodsamgateway.org/reporting/getAlertsTriggered`
        Any HTTP status (401/405) = proxy works. `407` = proxy needs Windows login → needs NTLM/Kerberos
        support (or ask IT to allow `goodsamgateway.org` without auth).
  - [x] **Tested 17 Nov 2026:** proxy is **Zscaler 6.2**. CONNECT returns `200 Connection Established`
        (no 407 – no proxy auth demanded), but the TLS handshake is then dropped
        (`curl: (35) schannel: failed to receive handshake`). `-k` irrelevant (fails before certs).
        GoodSAM itself accepts TLS 1.2 and 1.3 from home, so **Zscaler is cutting the connection**.
        Proxy fix is necessary but not sufficient.
  - [ ] Next tests on a work computer: (1) open the GoodSAM URL in Edge; (2) curl via proxy to https://www.google.com;
        (3) curl with `--proxy-negotiate -U :` (Kerberos/Windows login to Zscaler).
        #3 works → add Windows-auth proxy support to the program. Otherwise → IT ticket.
  - [ ] IT ticket: allow `goodsamgateway.org:443` through Zscaler for non-browser apps, SSL-inspection bypass.
  - [ ] Rebuild (`python build_release.py --version <date>`) and test on a work computer.
  - [ ] If REDCap upload also fails on work computers, apply the same proxy logic to the `requests` upload path.
  - Running Claude Code on a work computer: set `$env:HTTPS_PROXY = "http://apps.swproxy.nswhealth.net:40111"` first.
    Don't copy output CSVs / `_debug\` (PHI) on a flash drive.

- [ ] **Switch GoodSAM login to an OAuth 2.0 API client** (GoodSAM release email, 17 Nov 2026). Do alongside the proxy fix
      and ship in the same release.
  - Legacy username/password still works for now, but GoodSAM recommends one API client per system.
  - [ ] Ask a GoodSAM system admin to create a client: Manage → Integrations → API. Access: **Read** on
        **Reporting** and **Responders**, None on everything else. Save the secret immediately (shown once).
  - [x] Got the OAuth docs: `POST /oauth/token`, `grant_type=client_credentials`, client id/secret as Basic,
        returns `gsat_...` Bearer token valid 1 h. Scopes needed: `reporting:read`, `responders:read`.
  - [x] Code done (17 Nov 2026, not yet released): `GoodSAMAuth` / `make_goodsam_auth()` in `GS2RCAPI.py`;
        `--client-id` / `--client-secret` (or env `GOODSAM_CLIENT_ID` / `_SECRET`). In the GUIs just put the
        client ID in Username and the secret (`gsk_...`) in Password – detected automatically, saved in keyring
        as before. Labels now read "Username / Client ID" and "Password / Secret". Basic auth still works.
        Token failures are NOT retried (repeated failures block the IP for 4 h). Tested against a local fake server
        (OAuth, gsk_ auto-detect, Basic, bad secret, missing scope); not yet tested against real GoodSAM.
  - [ ] Test with the real client, then switch the saved credentials on each computer.
  - [ ] Client expires (default 12 months) – note the expiry date; admins get an email a week before.
        Secret rotation: old secret works for 24 h.
  - Already fine: TLS 1.2/1.3 (`ssl=False` only skips cert checks); code doesn't use `dev.goodsamgateway`.

## Next up (after connection issue is sorted)
- [ ] **OHCA Metro/Rural rule (`rule` field was always blank).**
  - [x] Fixed 22 Nov 2026 (app 2026.11.22-2): `_dispatch_rule_name()` reads `dispatchRules` (a list like
        `[{"name": "NSWAOHCA"}]`) instead of the non-existent `dispatchRule`. Several rules are joined with "; ".
  - Values: `NSWAOHCA` = Metro, `NSWAOHCRural` = Rural (14 Nov 2026: 38 Metro, 19 Rural). The raw name is sent.
  - [ ] Check the REDCap `rule` field is a **text box**. If it's a dropdown with codes (e.g. 1=Metro, 2=Rural), the
        upload will be rejected – then map the names to the codes in `_dispatch_rule_name()`.
  - [ ] Backfill `rule` for records already uploaded with it blank (incl. the 68 uploaded on 22 Nov 2026).

- [ ] **Hide the password and token in the console.** The "Args:" line prints the GoodSAM password (and the REDCap token on upload) in plain text. Mask them in both GUIs.
