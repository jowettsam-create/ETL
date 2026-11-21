# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Project overview

**GoodSAM → REDCap ETL pipeline** for NSW Ambulance.

Fetches alert and responder data from the GoodSAM API (or reads exported CSVs), reshapes it into a
REDCap import with a repeating instrument, and optionally uploads it to REDCap. Each alert becomes one
REDCap record: one **base row** plus one **repeating row** per responder.

**Data sensitivity: PHI.** Output contains responder names, phone numbers, emails and clinical data.
Never commit output CSVs, `_debug/` JSON dumps, logs, credentials or tokens (`.gitignore` blocks the
usual ones). Don't paste real data into issues, commits or chats.

Current work and open problems are tracked in `TODO.md` — read it first.

## Files

| File | What it is |
|---|---|
| `GS2RCAPI.py` | Core engine (~3,250 lines): fetch, transform, write CSV, upload. Also importable — the GUIs call `main()` directly when frozen. |
| `GS2RCAPI_GUI.py` | "ADV" GUI (Tkinter): API or CSV input, date pickers, manual Build / Upload, welfare list, master list copy. |
| `app.py` | **Streamlit web app** — stopgap replacement for both GUIs on PCs that can no longer run the `.exe`. Runs `GS2RCAPI.py` as a subprocess, credentials via env vars. |
| `.streamlit/` | `config.toml` (app settings) and `secrets.toml.example`. Real `secrets.toml` is git-ignored. |
| `GS2RCAPI_GUI_Lite.py` | "LITE" GUI: one button. Asks REDCap for the last record, fetches everything since, builds, uploads. Production daily run. |
| `build_release.py` | Builds both `.exe`s with PyInstaller and packages a release folder + zip. |
| `GS2RC-ADV.spec`, `GS2RC-LITE.spec` | **Generated** by PyInstaller during `build_release.py` (contain the building PC's absolute path). Not used as build input. |
| `requirements.txt` | Python dependencies. |
| `TODO.md` | Current to-do list. |
| `IMPROVEMENT_SUGGESTIONS.md` | Longer-term ideas, with status. |

## Pipeline

```
FETCH → FILTER → DEDUPLICATE ALERTS → DEDUPLICATE RESPONDERS → BUILD REDCAP ROWS → WRITE CSV → (UPLOAD)
```

1. **Fetch** — `load_goodsam_data()` (async, `aiohttp`) gets alerts, responders and the responder
   directory. Or `--alerts` / `--responders` CSVs.
2. **Filter** — keep only 5-digit references (NSW; drops interstate). Drop test rows
   (`ANSW test`, `stagetest`, `stage test`) via `drop_and_report()`. Responders that don't match an
   alert by Integer ID are dropped. Alerts **without** responders are kept.
3. **Deduplicate alerts** (same day + reference) → one row, `duplicate_2=1`, `times_realerted=n`, extra
   values in suffixed columns (`integerid_2`, `regtime_3`, …). See `ALERT_DUPLICATE_FIELDS`.
4. **Deduplicate responders** (same person, same job) → one row, `how_many_alerts=n`,
   `accept_yesno=1` if any alert was "Accepted" or "Accepted But Dropped Later", timeline in suffixed
   columns (`assign_2`, `gsresp_3`, …). Clinical fields come from the "best" instance (scored mainly on
   `adinfo` length). See `RESPONDER_DUPLICATE_FIELDS`.
5. **Build rows** — `record_id` assigned sequentially from `--start-id` after filtering.
6. **Write** CSV, master responder list, welfare follow-up; optional upload via `post_to_redcap()`.

### Rules that must not be broken

- **Integer ID is the only link between alerts and responders** — not String ID, not Reference.
- **Base rows:** `redcap_repeat_instrument` and `redcap_repeat_instance` both blank.
  **Responder rows:** `redcap_repeat_instrument = "responders"`, instance 1..N.
- **15-occurrence limit** per responder per record (`assign_1`…`assign_15`). Over 15 → keep the first 15
  by priority (position 1 always kept). Over 15 alert duplicates → split into extra records
  (`alertref` `12345`, `12345_2`, …).
- Clinical fields with value `FALSE` are blanked for REDCap.
- Phones: `+61` / `61` prefix → `0` (`fix_au_phone()`).
- Dates out as `dd/mm/yyyy HH:MM:SS`; GoodSAM times are `Australia/Sydney`.

### Changing REDCap fields

Update all of these in `GS2RCAPI.py`: `OUTPUT_COLUMNS` (~line 783), `ALERT_DUPLICATE_FIELDS`,
`RESPONDER_DUPLICATE_FIELDS`, `amap` / `rmap` inside `main()`, `BASE_REQUIRED_DEFAULTS` /
`RESP_REQUIRED_DEFAULTS` (~line 1670). On upload, columns not in the REDCap project are silently
dropped (`get_redcap_fieldset()`), so a typo won't error — check the upload count.

## Running

```bash
pip install -r requirements.txt
```

Build a CSV from the API (OAuth client — preferred):
```bash
python GS2RCAPI.py --client-id ID --client-secret gsk_... \
  --start-date "2026-11-01 00:00:00" --end-date "2026-11-01 23:59:59" \
  --start-id 1000 --out 261101.csv
```
Legacy login: `--username EMAIL --password PASS`. All four credentials can also come from env vars
`GOODSAM_USERNAME`, `GOODSAM_PASSWORD`, `REDCAP_API_URL`, `REDCAP_API_TOKEN`. A `gsk_...` value in `--password` is auto-detected as a
client secret. `GOODSAM_CLIENT_ID` / `GOODSAM_CLIENT_SECRET` env vars also work (keeps secrets off the
command line).

Build from CSVs: `python GS2RCAPI.py --alerts Alert.csv --responders Responder.csv --start-id 1000 --out out.csv`

Upload an existing CSV:
```bash
python GS2RCAPI.py --upload-input out.csv --out out.csv \
  --redcap-url https://SERVER/redcap/api/ --redcap-token TOKEN
```

Other flags: `--redcap-batch-size` (CLI default 100; GUIs pass 500), `--redcap-insecure`,
`--redcap-event-name`, `--no-save-api-json`. There is **no** `--verbose` flag.

GUIs: `python GS2RCAPI_GUI.py` (ADV) or `python GS2RCAPI_GUI_Lite.py` (LITE). Credentials are stored with
`keyring` (Windows Credential Manager) under `GoodSAM_ETL` and `GoodSAM_ETL_REDCAP`.

### Streamlit web app (`app.py`)

```bash
pip install -r requirements-app.txt
python -m streamlit run app.py
```
Opens at http://localhost:8501. Tabs: **Daily run** (= LITE button), **Custom date range** (= ADV build,
API or CSV), **Upload a CSV**. Credentials come from `.streamlit/secrets.toml` or env vars
(`GOODSAM_USERNAME`, `GOODSAM_PASSWORD`, `REDCAP_API_URL`, `REDCAP_API_TOKEN`); anything missing is typed
in the sidebar for that session only. Set `APP_PASSWORD` whenever others reach it over the network.

- Each browser session writes to its own temp folder; "Clear files" deletes it, and folders older than
  12 h are swept. Raw API JSON is **off** by default.
- The engine is run as a subprocess (not `main()` in-process) so concurrent sessions don't share `sys.argv`.
  Credentials go in the environment and are masked in the displayed log.
- In CSV mode the app strips GoodSAM credentials from the subprocess env — otherwise the engine would use
  the API instead of the uploaded files.
- Never use `st.stop()` inside a tab — it stops the whole script and hides the other tabs.
- "Now" is NSW time (`Australia/Sydney`) regardless of the server's timezone.
- Never deploy to Streamlit Community Cloud (public, third-party hosting; PHI). The Deploy button is hidden.

### Building the executables

```bash
python build_release.py --version 2026.11.21
```
`--skip-deps` skips the pip check; `--skip-build` re-packages existing `dist/*.exe`. Output goes to
`release/` (folder + zip). Executables are `--onefile --noconsole` and bundle `GS2RCAPI.py`.

Users must right-click the zip → Properties → **Unblock** before extracting, or SmartScreen blocks the exe.

## Output files

Written next to `--out` (GUIs: next to the `.exe`, or `Documents\GoodSAM_ETL` if that's read-only):

| File | Contents |
|---|---|
| `<name>.csv` | REDCap import (LITE names it `yymmdd.csv` for the previous day) |
| `<name>_master_responder_list.csv` | Deduplicated responder directory |
| `welreq_followup.csv` | Responders with `welreq=true` — **fixed name, overwritten each run** |
| `_debug/alerts_api.json`, `responders_api.json`, `responder_directory.json` | Raw API responses (unless `--no-save-api-json`) — full PHI |

## Networking (see `TODO.md` for current status)

- GoodSAM: `https://goodsamgateway.org/reporting/`; OAuth token at `/oauth/token`
  (override with `GOODSAM_OAUTH_TOKEN_URL`); directory URL override `GOODSAM_RESPONDER_DIR_URL`.
- **OAuth token failures are deliberately not retried** — repeated failures block the IP for 4 h.
- GoodSAM calls use `ssl=False` (cert verification off; TLS still used).
- `truststore` is injected at import so `requests` uses the Windows certificate store.
- Proxy: the GoodSAM fetch tries, in order, `GOODSAM_PROXY` → env/IE proxy → WinHTTP proxy
  (`_read_winhttp_proxy()`) → direct, logging each attempt. Python can't read PAC files.
  The REDCap upload path (`requests`) does **not** use this logic yet.

## Gotchas

- `asyncio.run()` is used inside `main()`; GUIs run it on a worker thread.
- When frozen, GUIs call `BUILDER.main()` in-process with `sys.argv` swapped and stdout captured, so output
  appears only when the step finishes. Unfrozen, they run `GS2RCAPI.py` as a subprocess and stream it.
- The GUIs echo the full command line to the console, **including the password and REDCap token**
  (open item in `TODO.md`).
- `GS2RCAPI_GUI.py` contains an unused "basic" tab code path (`basic_*` functions). Its
  `basic_run_auto_pipeline()` checks the return value of `_basic_run_cli()`, which returns `None`,
  so it would stop after starting the build. Use the LITE GUI for the automated run.
