# Improvement suggestions

Longer-term ideas for the GoodSAM → REDCap pipeline. Urgent and in-progress work lives in `TODO.md`;
move an item there when you start it.

Status reviewed against the code on 21 Nov 2026.
**Done** = in the code · **Partial** = some of it exists · **Open** = not started.

## Data safety (do first)

| # | Idea | Status | Notes |
|---|---|---|---|
| 1 | **Validate before upload** — duplicate `record_id`s, blank required fields (`record_id`, `alertref`, `casedate`), bad date formats | Partial | Upload already skips rows with blank `record_id` and drops columns REDCap doesn't know. Nothing checks duplicates or formats, and dropped columns aren't reported. Reporting dropped columns is the cheapest win. |
| 2 | **Confirm before upload** — "Upload N records, IDs X–Y to production?" | Open | LITE builds and uploads in one click. A confirm dialog between build and upload, showing counts, would catch most mistakes. |
| 3 | **Audit log** — who ran what, when, record ID range, success/fail | Open | Append-only text file next to the exe. Log counts and IDs only, **no names/phones** (the log must not become a PHI store). |
| 4 | **Keep a copy of what was uploaded** | Partial | Each day's CSV stays in the output folder (`yymmdd.csv`), so this mostly exists. `welreq_followup.csv` is overwritten each run — consider dating it. Needs a retention rule, since these are PHI. |
| 5 | **Automated tests** for dedup, the 15-occurrence limit, split rows, phone normalisation, `accept_yesno` | Open | Highest-value item for safe changes. Use made-up data only. A small fixture of fake alerts/responders run through the transform functions is enough. |

## Operations

| # | Idea | Status | Notes |
|---|---|---|---|
| 6 | **Dry run** (build, don't upload) | Done | LITE "Debug mode" checkbox; ADV has separate Build and Upload buttons. |
| 7 | **Upload recovery** — know what got in if it fails midway | Partial | On HTTP 504, `_confirm_chunk_uploaded()` checks REDCap before giving up. Other failures stop the run; re-running is safe only if record IDs are recalculated (LITE does this via `get_latest_record_context()`). |
| 8 | **Retry GoodSAM downloads** on intermittent network drops | Open | Listed in `TODO.md`. Must **not** retry OAuth token failures (4-hour IP block). |
| 9 | **Proxy support for REDCap upload** | Open | GoodSAM fetch has proxy fallbacks; the `requests` upload path doesn't. See `TODO.md`. |
| 10 | **Scheduled daily run** (Windows Task Scheduler) | Open | Needs a headless mode: CLI that reads credentials from keyring/env and does what LITE's button does. Do after the proxy problem is solved. |
| 11 | **Notify on success/failure** | Open | Depends on #10. Would need an approved mail route from IT. Don't put PHI in the message. |
| 12 | **Code-sign the exe** | Open | Stops SmartScreen blocking it. Ask IT about a code-signing certificate. |

## Usability

| # | Idea | Status | Notes |
|---|---|---|---|
| 13 | Show last run info | Done | LITE shows "Last run: … Window …". |
| 14 | Keyboard shortcuts | Done | ADV: Ctrl+R build, Ctrl+U upload, Ctrl+M master list, F5 refresh welfare. Not listed anywhere in the UI. |
| 15 | Preview / summary before upload (rows, alerts, date range, duplicates, welfare count) | Partial | The console prints most of these counts. A summary in the confirm dialog (#2) would cover it. |
| 16 | Data-quality report per run (response rate, missing fields, duplicates) | Open | |
| 17 | Remember window size, recent files | Open | Low value. |
| 18 | Config file instead of hard-coded URLs and batch size | Open | Low priority while there's one site. |

## Security

| # | Issue | Status | Notes |
|---|---|---|---|
| S1 | Password and REDCap token printed in the GUI console ("Args:" line) | Open | In `TODO.md`. Mask them in both GUIs. |
| S2 | Credentials passed as command-line arguments (visible in Task Manager when running unfrozen) | Partial | OAuth client ID/secret can come from env vars (`GOODSAM_CLIENT_ID` / `_SECRET`). GUIs still pass `--password` / `--redcap-token`. Passing them via the environment of the subprocess would fix both. |
| S3 | GoodSAM certificate verification off (`ssl=False`) | Open | Now that `truststore` is in use, test whether verification can be turned back on. |
| S4 | `_debug/` JSON and output CSVs are unencrypted PHI on disk | Open | At minimum: default "Save GoodSAM API JSON dumps" to **off** in the GUIs, and set a retention rule for old output. |

## Documentation still missing

- Short user guide for LITE (install, unblock zip, first-time credentials, daily run, what to do with welfare requests).
- Troubleshooting page (proxy/Zscaler errors, SmartScreen, OAuth errors) — much of this is already in `TODO.md`.
- Field mapping table (GoodSAM field → REDCap field) generated from `amap` / `rmap`.
- Change log per release.
