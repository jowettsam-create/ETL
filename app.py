#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
app.py — Streamlit front-end for the GoodSAM → REDCap pipeline.

Stopgap replacement for the Tkinter GUIs (GS2RC-ADV / GS2RC-LITE) for people whose
computers can no longer run the .exe. The pipeline itself is unchanged: this page
runs GS2RCAPI.py exactly as the GUIs do, with credentials passed through environment
variables (never on the command line or in the console output).

Run:
    python -m streamlit run app.py

Credentials:
    Put them in .streamlit/secrets.toml (see .streamlit/secrets.toml.example) or in
    environment variables of the same names. Anything not configured can be typed into
    the sidebar; typed values live only in this browser session.

Files:
    Each browser session gets its own temporary folder. Outputs are offered as
    downloads and deleted with "Clear files", or automatically after 12 hours.
"""

from __future__ import annotations

import hmac
import io
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from datetime import date, datetime, timedelta

import pandas as pd
import streamlit as st

try:
    from zoneinfo import ZoneInfo
    SYDNEY = ZoneInfo("Australia/Sydney")
except Exception:  # pragma: no cover - tzdata missing
    SYDNEY = None

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.join(HERE, "GS2RCAPI.py")
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import GS2RCAPI as engine  # noqa: E402  (used for the REDCap "next record" lookups)

# Shown on the page so people can check they're running the latest download.
# **Bump this on every change you push** (date + number for that day).
APP_VERSION = "2026.11.21-5"

# **CHANGE THIS** if the REDCap server moves
DEFAULT_REDCAP_URL = "https://nswa-redcap.ambulance.nsw.gov.au/redcap/api/"
# Same batch size the desktop GUIs use
REDCAP_BATCH = 500
WORKDIR_PREFIX = "goodsam_etl_"
WORKDIR_MAX_AGE_HOURS = 12

def bypass_proxy_for(url: str) -> None:
    """Connect to REDCap directly, never through a web proxy.

    REDCap is an internal NSW server. When HTTPS_PROXY is set in the window that
    started the app (e.g. so pip could install packages), every REDCap request went
    through the NSW Health proxy, which answers with a bare "403 Forbidden" page.
    Adding the host to NO_PROXY fixes that for this process and the engine
    subprocesses (they inherit os.environ). Set REDCAP_USE_PROXY=1 to turn this off.
    """
    from urllib.parse import urlparse

    host = urlparse(url or "").hostname
    if not host or os.environ.get("REDCAP_USE_PROXY") == "1":
        return
    for key in ("NO_PROXY", "no_proxy"):
        current = [h.strip() for h in os.environ.get(key, "").split(",") if h.strip()]
        if host not in current:
            os.environ[key] = ",".join(current + [host])


bypass_proxy_for(DEFAULT_REDCAP_URL)

st.set_page_config(page_title="GoodSAM → REDCap", page_icon="🚑", layout="wide")


# ---------------------------------------------------------------------------
# Settings / secrets
# ---------------------------------------------------------------------------
def setting(name: str, default: str = "") -> str:
    """Read a value from .streamlit/secrets.toml, then the environment."""
    try:
        if name in st.secrets:
            return str(st.secrets[name]).strip()
    except Exception:  # no secrets file at all
        pass
    return os.environ.get(name, default).strip()


def now_sydney() -> datetime:
    """Local NSW time as a naive datetime, whatever timezone the server is in."""
    if SYDNEY is not None:
        return datetime.now(SYDNEY).replace(tzinfo=None)
    return datetime.now()


# ---------------------------------------------------------------------------
# Optional access password (set APP_PASSWORD when the page is shared on a network)
# ---------------------------------------------------------------------------
def require_app_password() -> None:
    expected = setting("APP_PASSWORD")
    if not expected or st.session_state.get("authed"):
        return
    st.title("GoodSAM → REDCap")
    st.caption(f"App version {APP_VERSION}")
    pw = st.text_input("Access password", type="password")
    if st.button("Sign in", type="primary"):
        if hmac.compare_digest(pw.encode(), expected.encode()):
            st.session_state.authed = True
            st.rerun()
        else:
            st.error("Incorrect password.")
    st.stop()


# ---------------------------------------------------------------------------
# Per-session working folder
# ---------------------------------------------------------------------------
def _sweep_old_workdirs() -> None:
    """Delete working folders from old sessions (they hold PHI)."""
    cutoff = time.time() - WORKDIR_MAX_AGE_HOURS * 3600
    tmp = tempfile.gettempdir()
    for name in os.listdir(tmp):
        if not name.startswith(WORKDIR_PREFIX):
            continue
        path = os.path.join(tmp, name)
        try:
            if os.path.isdir(path) and os.path.getmtime(path) < cutoff:
                shutil.rmtree(path, ignore_errors=True)
        except OSError:
            pass


def workdir() -> str:
    wd = st.session_state.get("workdir")
    if not wd or not os.path.isdir(wd):
        _sweep_old_workdirs()
        wd = tempfile.mkdtemp(prefix=WORKDIR_PREFIX)
        st.session_state.workdir = wd
    return wd


def clear_workdir() -> None:
    wd = st.session_state.pop("workdir", None)
    if wd:
        shutil.rmtree(wd, ignore_errors=True)
    for key in ("last_output", "last_log", "last_label"):
        st.session_state.pop(key, None)


# ---------------------------------------------------------------------------
# Running the engine
# ---------------------------------------------------------------------------
def engine_env(creds: dict) -> dict:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"  # the engine prints emoji; Windows consoles choke otherwise
    env["PYTHONUNBUFFERED"] = "1"
    mapping = {
        "GOODSAM_USERNAME": creds.get("gs_user", ""),
        "GOODSAM_PASSWORD": creds.get("gs_pass", ""),
        "REDCAP_API_URL": creds.get("rc_url", ""),
        "REDCAP_API_TOKEN": creds.get("rc_token", ""),
    }
    for key, value in mapping.items():
        if value:
            env[key] = value
        else:
            env.pop(key, None)
    return env


def _mask(text: str, creds: dict) -> str:
    for key in ("gs_pass", "rc_token"):
        secret = creds.get(key) or ""
        if len(secret) >= 4:
            text = text.replace(secret, "********")
    return text


def run_engine(args: list[str], creds: dict, label: str) -> tuple[int, str]:
    """Run GS2RCAPI.py with live output. Returns (exit code, full log)."""
    st.markdown(f"**{label}**")
    box = st.empty()
    lines: list[str] = []
    try:
        proc = subprocess.Popen(
            [sys.executable, "-u", ENGINE, *args],
            cwd=workdir(),
            env=engine_env(creds),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except Exception as exc:  # pragma: no cover
        st.error(f"Could not start the pipeline: {exc}")
        return 1, str(exc)

    assert proc.stdout is not None
    for line in proc.stdout:
        lines.append(_mask(line.rstrip("\n"), creds))
        box.code("\n".join(lines[-400:]), language=None)
    proc.wait()
    log = "\n".join(lines)
    if proc.returncode == 0:
        st.success(f"{label}: finished.")
    else:
        st.error(f"{label}: failed (exit code {proc.returncode}). See the output above.")
    return proc.returncode, log


def build_args(out_path: str, start_id: int, start: str | None = None, end: str | None = None,
               alerts: str | None = None, responders: str | None = None,
               save_json: bool = False) -> list[str]:
    args = ["--out", out_path, "--start-id", str(start_id)]
    if alerts and responders:
        args += ["--alerts", alerts, "--responders", responders]
    else:
        args += ["--start-date", start, "--end-date", end]
    if not save_json:
        args.append("--no-save-api-json")
    return args


def upload_args(csv_path: str) -> list[str]:
    return ["--upload-input", csv_path, "--out", csv_path, "--redcap-batch-size", str(REDCAP_BATCH)]


def _parse_regtime(value: str | None) -> datetime | None:
    """Same parsing as the LITE GUI (REDCap regtime → datetime)."""
    if not value:
        return None
    txt = value.strip().replace("  ", " ")
    if not txt:
        return None
    if " " in txt and ":" in txt:
        date_part, time_part = txt.split(" ", 1)
        segs = time_part.split(":")
        if len(segs) == 2:
            segs.append("00")
        if segs and len(segs[0]) == 1:
            segs[0] = f"0{segs[0]}"
        txt = f"{date_part} {':'.join(segs[:3])}"
    for fmt in ("%d/%m/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(txt, fmt)
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# Results (downloads + welfare list)
# ---------------------------------------------------------------------------
def output_files(out_path: str) -> dict[str, str]:
    base, _ = os.path.splitext(out_path)
    folder = os.path.dirname(out_path)
    candidates = {
        "REDCap import CSV": out_path,
        "Master responder list": base + "_master_responder_list.csv",
        "Welfare follow-up": os.path.join(folder, "welreq_followup.csv"),
    }
    return {k: v for k, v in candidates.items() if os.path.isfile(v)}


def show_results() -> None:
    out_path = st.session_state.get("last_output")
    if not out_path or not os.path.isfile(out_path):
        return
    st.divider()
    st.subheader(f"Results — {st.session_state.get('last_label', os.path.basename(out_path))}")

    files = output_files(out_path)
    cols = st.columns(max(1, len(files)))
    for col, (label, path) in zip(cols, files.items()):
        with open(path, "rb") as fh:
            col.download_button(f"⬇ {label}", fh.read(), file_name=os.path.basename(path),
                                mime="text/csv", use_container_width=True)

    debug_dir = os.path.join(os.path.dirname(out_path), "_debug")
    if os.path.isdir(debug_dir) and os.listdir(debug_dir):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for name in os.listdir(debug_dir):
                zf.write(os.path.join(debug_dir, name), arcname=name)
        st.download_button("⬇ Raw API JSON (debug, contains PHI)", buf.getvalue(),
                           file_name="goodsam_debug.zip", mime="application/zip")

    wel_path = files.get("Welfare follow-up")
    st.markdown("#### Welfare requests")
    if not wel_path:
        st.info("No welfare requests in this run.")
    else:
        wel = pd.read_csv(wel_path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
        if wel.empty:
            st.info("No welfare requests in this run.")
        else:
            st.warning(f"{len(wel)} responder(s) requested a welfare check.")
            st.dataframe(wel, use_container_width=True, hide_index=True)
            lines = [
                f"Record ID: {r.get('record_id', '')} {r.get('name1', '')} {r.get('name2', '')} "
                f"has requested a welfare check {r.get('phone', '')} {r.get('eml', '')}".strip()
                for r in wel.to_dict("records")
            ]
            st.caption("Copy text (use the copy icon at the top right of the box):")
            st.code("\n".join(lines), language=None)

    with st.expander("Full log"):
        st.code(st.session_state.get("last_log", ""), language=None)


def describe_error(exc: Exception) -> str:
    """Error text plus what the server actually said (REDCap explains 403s in the body)."""
    msg = str(exc)
    resp = getattr(exc, "response", None)
    if resp is None:
        return msg
    body = (getattr(resp, "text", "") or "").strip()
    if not body:
        return msg
    if "<html" in body[:500].lower():
        import re
        title = re.search(r"<title[^>]*>(.*?)</title>", body, re.I | re.S)
        text = re.sub(r"<[^>]+>", " ", body)
        text = re.sub(r"\s+", " ", text).strip()
        detail = f"a web page{' titled “' + title.group(1).strip() + '”' if title else ''}: {text[:300]}"
        hint = ("\n\nThat's a web page rather than a REDCap API reply, so something between this computer and "
                "REDCap (e.g. a proxy or firewall) probably blocked the request.")
    else:
        detail = body[:300]
        hint = ""
        if "permission" in body.lower() or "token" in body.lower():
            hint = ("\n\nREDCap rejected the API token. Check it's copied exactly (no spaces), belongs to this "
                    "project, and that your REDCap user still has API Export and Import rights.")
    return f"{msg}\n\nServer said {detail}{hint}"


def connection_check(rc_url: str) -> None:
    """Test REDCap and GoodSAM from the Python that runs this app (fake token, no real data)."""
    import platform
    import requests

    st.write(f"**Python:** `{sys.executable}` ({platform.python_version()})")
    import re

    def _hide_login(v: str) -> str:  # proxy URLs can carry user:password@
        return re.sub(r"//[^/@\s]+@", "//***@", str(v))

    env_proxies = {k: _hide_login(v) for k, v in os.environ.items() if "proxy" in k.lower()}
    st.write(f"**Proxy environment variables:** `{env_proxies or 'none'}`")
    try:
        import urllib.request
        used = {k: _hide_login(v) for k, v in urllib.request.getproxies().items()}
        st.write(f"**Proxies Python will use:** `{used or 'none'}`")
    except Exception:
        pass

    def probe(label: str, method: str, url: str, trust_env: bool, **kw) -> None:
        s = requests.Session()
        s.trust_env = trust_env
        try:
            r = s.request(method, url, timeout=30, **kw)
            body = " ".join((r.text or "").split())[:200]
            st.write(f"**{label}:** HTTP {r.status_code} — `{body}`")
        except Exception as exc:
            st.write(f"**{label}:** FAILED — `{exc}`")

    fake = {"token": "0" * 32, "content": "version"}
    probe("REDCap (normal)", "POST", rc_url, True, data=fake)
    probe("REDCap (ignoring proxies)", "POST", rc_url, False, data=fake)
    probe("GoodSAM (normal)", "GET", engine.BASE_URL, True)
    st.caption("For REDCap, “You do not have permissions to use the API” is the expected reply (the test uses a "
               "fake token) and means REDCap was reached. A bare “403 Forbidden” page means something in between "
               "blocked it.")


def daily_run(creds: dict, dry_run: bool, save_json: bool) -> None:
    """What the LITE app's button does. Returns early (never st.stop) so the other tabs still render."""
    try:
        with st.spinner("Asking REDCap for the latest record…"):
            ctx = engine.get_latest_record_context(creds["rc_url"], creds["rc_token"], verify=True)
    except Exception as exc:
        st.error(f"Could not read the latest record from REDCap: {describe_error(exc)}")
        return

    next_id = int(ctx.get("next_record_id") or 1)
    last_reg = ctx.get("last_regtime") or ""
    last_dt = _parse_regtime(last_reg)
    end_dt = now_sydney().replace(hour=0, minute=0, second=0, microsecond=0)
    prev_day = end_dt - timedelta(days=1)
    start_dt = last_dt + timedelta(seconds=1) if last_dt else prev_day

    st.write(f"Last record in REDCap: **{ctx.get('last_record_id')}** (regtime {last_reg or 'n/a'}). "
             f"Next record ID: **{next_id}**.")
    if start_dt >= end_dt:
        st.info(f"Nothing new to fetch: REDCap is already up to date to {end_dt:%d/%m/%Y %H:%M}.")
        return

    start_s = start_dt.strftime("%Y-%m-%d %H:%M:%S")
    end_s = end_dt.strftime("%Y-%m-%d %H:%M:%S")
    st.write(f"Fetching **{start_s} → {end_s}**")
    out_path = os.path.join(workdir(), prev_day.strftime("%y%m%d") + ".csv")

    rc, log = run_engine(build_args(out_path, next_id, start_s, end_s, save_json=save_json), creds, "Build")
    st.session_state.update(last_output=out_path, last_log=log,
                            last_label=f"{os.path.basename(out_path)} ({start_s} → {end_s})")
    if rc != 0:
        return
    if dry_run:
        st.info("Debug mode: upload skipped.")
        return
    rc2, log2 = run_engine(upload_args(out_path), creds, "REDCap upload")
    st.session_state.last_log = log + "\n\n" + log2
    if rc2 == 0:
        st.balloons()


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------
require_app_password()

st.title("🚑 GoodSAM → REDCap")
st.caption(f"App version {APP_VERSION}")

with st.sidebar:
    st.header("Credentials")
    cfg = {
        "gs_user": setting("GOODSAM_USERNAME"),
        "gs_pass": setting("GOODSAM_PASSWORD"),
        "rc_url": setting("REDCAP_API_URL", DEFAULT_REDCAP_URL) or DEFAULT_REDCAP_URL,
        "rc_token": setting("REDCAP_API_TOKEN"),
    }
    creds = dict(cfg)

    if cfg["gs_user"] and cfg["gs_pass"]:
        st.success("GoodSAM: using saved server credentials")
    else:
        creds["gs_user"] = st.text_input("GoodSAM username / client ID", key="gs_user").strip()
        creds["gs_pass"] = st.text_input("GoodSAM password / secret", type="password", key="gs_pass").strip()

    if cfg["rc_token"]:
        st.success("REDCap: using saved server token")
    else:
        creds["rc_url"] = st.text_input("REDCap API URL", value=cfg["rc_url"], key="rc_url").strip()
        creds["rc_token"] = st.text_input("REDCap API token", type="password", key="rc_token").strip()

    st.caption("Typed credentials are kept only for this browser session.")
    st.divider()
    if st.button("🗑 Clear files from this session", use_container_width=True):
        clear_workdir()
        st.rerun()
    st.caption(f"Output files are deleted automatically after {WORKDIR_MAX_AGE_HOURS} hours.")
    st.divider()
    with st.expander("🔧 Connection check"):
        st.caption("Tests whether this computer can reach REDCap and GoodSAM. Sends no real credentials.")
        if st.button("Run connection check", use_container_width=True):
            connection_check(creds.get("rc_url") or DEFAULT_REDCAP_URL)
    st.caption(f"Version {APP_VERSION}")

bypass_proxy_for(creds.get("rc_url", ""))  # in case a different REDCap URL was entered

have_goodsam = bool(creds["gs_user"] and creds["gs_pass"])
have_redcap = bool(creds["rc_url"] and creds["rc_token"])

tab_daily, tab_custom, tab_upload = st.tabs(["Daily run", "Custom date range", "Upload a CSV"])

# --- Daily run (what the LITE app does) -------------------------------------
with tab_daily:
    st.write("Fetches everything since the last record in REDCap up to midnight today (NSW time), "
             "builds the REDCap file and uploads it.")
    dry_run = st.checkbox("Build only — don't upload to REDCap (debug mode)", key="daily_dry")
    save_json_daily = st.checkbox("Keep raw GoodSAM API JSON (debugging only, contains PHI)", key="daily_json")

    if st.button("▶ Build + upload latest", type="primary", disabled=not (have_goodsam and have_redcap)):
        daily_run(creds, dry_run, save_json_daily)

# --- Custom range (what the ADV app does) -----------------------------------
with tab_custom:
    c1, c2 = st.columns(2)
    today = now_sydney().date()
    start_day = c1.date_input("Start day", value=today - timedelta(days=1), format="DD/MM/YYYY")
    end_day = c2.date_input("End day", value=today - timedelta(days=1), format="DD/MM/YYYY")

    c3, c4 = st.columns([2, 1])
    if "custom_start_id" not in st.session_state:
        st.session_state.custom_start_id = 1
    c4.write("")
    c4.write("")
    if c4.button("Get next ID from REDCap", disabled=not have_redcap):
        try:
            st.session_state.custom_start_id = int(
                engine.get_next_record_id(creds["rc_url"], creds["rc_token"], verify=True))
        except Exception as exc:
            st.error(f"Could not get the next record ID: {describe_error(exc)}")
    start_id = c3.number_input("Starting record_id", min_value=1, step=1, key="custom_start_id")

    source = st.radio("Data source", ["GoodSAM API", "CSV files exported from GoodSAM"], horizontal=True)
    alerts_file = responders_file = None
    if source.startswith("CSV"):
        alerts_file = st.file_uploader("Alert CSV", type=["csv"], key="alerts_csv")
        responders_file = st.file_uploader("Responder CSV", type=["csv"], key="responders_csv")
    save_json_custom = st.checkbox("Keep raw GoodSAM API JSON (debugging only, contains PHI)", key="custom_json")
    out_name = st.text_input("Output file name", value=f"{start_day:%y%m%d}-{end_day:%y%m%d}.csv")

    ready = (have_goodsam if source == "GoodSAM API" else bool(alerts_file and responders_file))
    build_clicked = st.button("▶ Build CSV", type="primary", disabled=not ready)
    if build_clicked and start_day > end_day:
        st.error("Start day must be on or before end day.")
    elif build_clicked:
        name =os.path.basename(out_name.strip() or "output.csv")
        if not name.lower().endswith(".csv"):
            name += ".csv"
        out_path = os.path.join(workdir(), name)
        kwargs = {}
        if alerts_file and responders_file:
            a_path = os.path.join(workdir(), "input_alerts.csv")
            r_path = os.path.join(workdir(), "input_responders.csv")
            with open(a_path, "wb") as fh:
                fh.write(alerts_file.getvalue())
            with open(r_path, "wb") as fh:
                fh.write(responders_file.getvalue())
            kwargs = {"alerts": a_path, "responders": r_path}
        start_s = f"{start_day:%Y-%m-%d} 00:00:00"
        end_s = f"{end_day:%Y-%m-%d} 23:59:59"
        # The engine prefers the API whenever GoodSAM credentials are present, so leave
        # them out when building from uploaded CSVs.
        run_creds = dict(creds, gs_user="", gs_pass="") if kwargs else creds
        rc, log = run_engine(build_args(out_path, int(start_id), start_s, end_s,
                                        save_json=save_json_custom, **kwargs), run_creds, "Build")
        st.session_state.update(last_output=out_path, last_log=log, last_label=name)

    last = st.session_state.get("last_output")
    if last and os.path.isfile(last):
        st.divider()
        st.write(f"Upload **{os.path.basename(last)}** to REDCap?")
        confirm = st.checkbox("I've checked the file and want to upload it to the live REDCap project",
                              key="custom_confirm")
        if st.button("⬆ Upload to REDCap", disabled=not (confirm and have_redcap)):
            rc, log = run_engine(upload_args(last), creds, "REDCap upload")
            st.session_state.last_log = st.session_state.get("last_log", "") + "\n\n" + log

# --- Upload an existing CSV -------------------------------------------------
with tab_upload:
    st.write("Upload a REDCap import CSV that was built earlier.")
    up = st.file_uploader("REDCap import CSV", type=["csv"], key="upload_csv")
    confirm_up = st.checkbox("Upload this file to the live REDCap project", key="upload_confirm")
    if st.button("⬆ Upload to REDCap", key="upload_btn", disabled=not (up and confirm_up and have_redcap)):
        path = os.path.join(workdir(), "upload_" + os.path.basename(up.name))
        with open(path, "wb") as fh:
            fh.write(up.getvalue())
        run_engine(upload_args(path), creds, "REDCap upload")

if not (have_goodsam and have_redcap):
    st.sidebar.warning("Enter GoodSAM and REDCap credentials to enable the buttons.")

show_results()
