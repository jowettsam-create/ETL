#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
GS2RCAPI.py
=================================
Build a single REDCap-ready CSV from GoodSAM Alert and Responder data
using **Integer ID** as the ONLY linkage between alerts and responders.

OVERVIEW:
---------
This script fetches GoodSAM emergency response data (either via API or from CSV files)
and transforms it into a REDCap-compatible format with repeating instruments.
The output contains one "base row" per alert (with empty redcap_repeat_instrument) and multiple "repeating rows"
for each responder associated with that alert.

DATA FLOW:
----------
1. FETCH: Retrieve alerts & responders from GoodSAM API or read from CSV files
2. FILTER: Keep only alerts with matching responders (via Integer ID linkage)
3. DEDUPLICATE ALERTS: Collapse duplicate alerts (same day + alert reference) into single rows
4. DEDUPLICATE RESPONDERS: Collapse multiple alerts to the same responder for a job
5. BUILD REDCAP ROWS: Create base rows (alerts) and repeating rows (responders)
6. OUTPUT: Write REDCap-ready CSV and optionally upload to REDCap API

REDCAP DATABASE STRUCTURE:
---------------------------
Each alert becomes ONE record in REDCap with:
- Base row: redcap_repeat_instrument = "" (empty), contains alert information
- Repeating rows: redcap_repeat_instrument = "responders", instance 1..N for each responder

FILTERING RULES:
----------------
- Alerts: keep rows where `Reference` is exactly 5 digits (drops interstate)
- Responders: keep rows where `Alert Reference` is exactly 5 digits (drops interstate)
- Responders: drop any that don't match existing alerts by Integer ID
- Alerts WITHOUT responders are now KEPT (not dropped)
- Assign `record_id` AFTER removals, 1 per remaining alert (sequential from --start-id)

FIELD MAPPINGS (GoodSAM → REDCap):
-----------------------------------
ALERT FIELDS (base rows):
  - Integer ID → integerid
  - String ID → stringalt
  - Reference → alertref
  - Rule Used → rule
  - Registered Time → regtime, casedate
  - Cancellation Time → gscanc
  - Cancellation Type → canctype
  - Messages → messages
  - Latitude/Longitude → lat, long
  - any_responders → 1 if alert had responders, 0 if no responders (computed field)

RESPONDER FIELDS (repeating rows):
  IDENTIFICATION:
  - First Name / Last Name → name1, name2
  - Phone Number → phone (normalized: +61 → 0)
  - Email → eml
  - Category/Team → category
  - Verifying Organisation → verify
  - Registration Body → reg

  TIMELINE DATA (suffixed _1, _2, _3, etc. for multiple alerts):
  - Assigned Time → assign_1, assign_2, ...
  - Acceptance Time → accept_1, accept_2, ...
  - Rejection Time → reject_1, reject_2, ...
  - Dropped Time → drop_1, drop_2, ...
  - On Scene Time → scene_1, scene_2, ...
  - With Patient Time → pt_1, pt_2, ...
  - Defib Obtained Time → defib_1, defib_2, ...
  - Feedback Time → fdbck_1, fdbck_2, ...
  - Status → gsresp_1, gsresp_2, ...
  - Hour of Assignment → hour (calculated ONCE from first alert, NOT duplicated)

  CLINICAL/FEEDBACK DATA (populated ONCE from instance with best data):
  - Additional Info (free text) → adinfo
  - False Alarm → falsealm
  - Patient Gender → ptgen
  - Nature of Emergency → natemerg
  - Prior Care → priorcare
  - Airway Status → airway
  - Breathing Status → breathing
  - Circulation Status → circ
  - Disability Status → disability
  - Respiratory Rate → resprate
  - First Pulse → pulse
  - Jaw Thrust → jawth
  - Chin Lift → chinlft
  - Nasopharyngeal Airway → naso
  - Oropharyngeal Airway → oro
  - Intubation → intubate
  - Position → position
  - Defibrillation → defibn
  - AED ID Used → aedid
  - AED Reference → aedref
  - Number of Shocks → nshocks
  - CPR Provided → cprprov
  - CPR Duration → cprdurtn
  - Other Interventions → othint
  - Outcome → outcome
  - Responder Injury Incident → injinc
  - Welfare Request → welreq

DUPLICATE HANDLING:
-------------------
ALERT DUPLICATES (same day + alert reference):
  - Keep a single alert row with duplicate_2=1, times_realerted=count
  - Store additional alert values using suffixes: integerid_2, regtime_3, etc.
  - If >15 duplicates exist, split into multiple rows:
    * Row 1: alertref "12345" - contains alerts 1-15
    * Row 2: alertref "12345_2" - contains alerts 16-30
    * Row 3: alertref "12345_3" - contains alerts 31-45, etc.
    * Each split row gets ALL responders with filtered timeline data

RESPONDER DUPLICATES (same person alerted multiple times for one job):
  - Collapse into one responder row per job
  - how_many_alerts = count of times they were alerted (capped at 15)
  - accept_yesno = 1 if ANY alert was accepted (including "Accepted But Dropped Later"), else 0
  - Store additional responder data using suffixes: assign_2, gsresp_3, etc.
  - REDCap limit: maximum 15 occurrences per responder per row (assign_1 through assign_15)
  - For split rows (>15 alert duplicates), responders include:
    * Timeline from the FIRST time they were alerted (position 1 - baseline data)
    * PLUS timeline from alerts in this chunk (e.g., positions 16-30 for alertref_2)
    * If this exceeds 15 occurrences, keep first 15 by priority (acceptance/assignment time)
    * Position 1 (baseline) is ALWAYS included, even if it means replacing the 15th occurrence

CLINICAL DATA SELECTION (when responder alerted multiple times):
  - Clinical fields are populated ONCE (not duplicated) from the "best" instance
  - The "best" instance is chosen by scoring each alert's feedback data:
    * HEAVY PRIORITY: adinfo (additional info) text length - longer narrative = better
    * Count of other clinical fields with meaningful data (not empty, not "FALSE")
  - Example: If instance 1 has detailed adinfo text but instance 2 just has checkboxes,
    instance 1's clinical data is used because adinfo contains the most valuable information
  - FALSE values are automatically converted to blank (empty string)

SPECIAL PROCESSING:
-------------------
- Australian phone numbers: +61 / 61 prefixes → 0 (keeps surrounding text)
- Dates: normalized to dd/mm/yyyy HH:MM:SS format
- Times: hour field = HH (00-23) from Assigned Time (calculated ONCE, not duplicated)
- Test data: rows containing "ANSW test", "stagetest" are dropped
- Welfare requests: responders with welreq=true exported to welreq_followup.csv
- Clinical fields: FALSE values converted to blank (empty string)
- Base rows (alerts): redcap_repeat_instrument and redcap_repeat_instance both BLANK
  (case_details is NOT a repeating instrument)

WHERE TO MAKE CHANGES WHEN REDCAP DATABASE CHANGES:
----------------------------------------------------
1. OUTPUT_COLUMNS: Add/remove REDCap field names here
2. Alert field mappings: Update amap dictionary in main()
3. Responder field mappings: Update rmap dictionary in main()
4. ALERT_DUPLICATE_FIELDS: Fields to suffix for duplicate alerts
5. RESPONDER_DUPLICATE_FIELDS: Fields to suffix for duplicate responders
6. BASE_REQUIRED_DEFAULTS: Default values for base row fields (in apply_redcap_default_fields)
7. RESP_REQUIRED_DEFAULTS: Default values for responder row fields (in apply_redcap_default_fields)
"""

import argparse
import os
import sys
import re

# Use the Windows/macOS certificate store for SSL verification instead of
# Python's bundled certifi list. Work networks that inspect HTTPS traffic
# re-sign certificates with a corporate CA that only exists in the OS store,
# so without this every HTTPS call fails with CERTIFICATE_VERIFY_FAILED on
# those machines. Must run before requests/aiohttp/PyCap create SSL contexts.
try:
    import truststore  # type: ignore
    truststore.inject_into_ssl()
except Exception:
    pass
import numpy as np
import pandas as pd
import csv
from pathlib import Path
import json
# HTTP helpers always available (even if requests succeeds)
import urllib.request
import urllib.parse
import urllib.error
import ssl

try:
    # Preferred: python-redcap (PyCap)
    from redcap import Project as REDCapProject  # type: ignore
except ImportError:
    REDCapProject = None
try:
    import requests  # preferred HTTP client
except ImportError:
    requests = None

# ============================================================
# GOODSAM API INTEGRATION
# ============================================================
# Functions to fetch alert and responder data from the GoodSAM Reporting API
# These functions use async HTTP requests to fetch data in parallel for better performance
import aiohttp
import asyncio
from datetime import datetime
try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None

# Configure timezone for date/time parsing (GoodSAM uses Australia/Sydney)
SYDNEY_TZ = None
if ZoneInfo:
    try:
        SYDNEY_TZ = ZoneInfo("Australia/Sydney")
    except (KeyError, OSError):  # ZoneInfo raises KeyError if timezone not found
        SYDNEY_TZ = None

# GoodSAM API endpoints
# **CHANGE THIS** if GoodSAM changes their API URL structure
BASE_URL = "https://goodsamgateway.org/reporting/"

# Responder directory URL (can be overridden with GOODSAM_RESPONDER_DIR_URL environment variable)
RESPONDER_DIRECTORY_URL = os.environ.get(
    "GOODSAM_RESPONDER_DIR_URL",
    "https://goodsamgateway.org/responders/getResponders",
)

# OAuth 2.0 token endpoint (client credentials grant) for GoodSAM API clients
# **CHANGE THIS** if GoodSAM moves the token endpoint
OAUTH_TOKEN_URL = os.environ.get("GOODSAM_OAUTH_TOKEN_URL", "https://goodsamgateway.org/oauth/token")


class GoodSAMAuth:
    """
    GoodSAM credentials: either legacy Basic (API username/password) or an
    OAuth 2.0 API client (client id + secret, exchanged for a 1-hour Bearer token).
    """

    def __init__(self, username=None, password=None, client_id=None, client_secret=None):
        self.username = username
        self.password = password
        self.client_id = client_id
        self.client_secret = client_secret
        self.token = None

    @property
    def is_oauth(self):
        return bool(self.client_id and self.client_secret)

    async def ensure_token(self, session, proxy=None):
        """Get a Bearer token via the client credentials grant (no-op for Basic auth)."""
        if not self.is_oauth or self.token:
            return
        data = {"grant_type": "client_credentials"}
        auth = aiohttp.BasicAuth(self.client_id, self.client_secret)
        kw = {"proxy": proxy} if proxy else {}
        async with session.post(OAUTH_TOKEN_URL, data=data, auth=auth, ssl=False, **kw) as resp:
            text = await resp.text()
            try:
                body = json.loads(text)
            except ValueError:
                body = {}
            if resp.status != 200 or "access_token" not in body:
                err = body.get("error", "")
                hint = ""
                if err == "invalid_client":
                    hint = (" – check the client ID/secret, and that the client hasn't expired or been revoked."
                            " NOTE: repeated failures block this IP for up to 4 hours, so don't keep retrying.")
                raise RuntimeError(f"GoodSAM OAuth token request returned {resp.status} {err}{hint} {text[:200]}")
            self.token = body["access_token"]
            print(f"🔑 GoodSAM API client token obtained (scopes: {body.get('scope', '?')})")

    def request_kwargs(self):
        """aiohttp request kwargs (auth / headers) for an API call."""
        if self.is_oauth:
            return {"headers": {"Authorization": f"Bearer {self.token}"}}
        return {"auth": aiohttp.BasicAuth(self.username, self.password)}


def _merge_request_kwargs(gs_auth, headers=None):
    kw = gs_auth.request_kwargs()
    if headers:
        kw["headers"] = {**headers, **kw.get("headers", {})}
    return kw


def _scope_hint(status):
    if status == 403:
        return " (API client is missing the scope for this endpoint – give it Read on Reporting and Responders)"
    if status == 401:
        return " (credentials rejected or token expired)"
    return ""


async def fetch_goodsam_report(session, gs_auth, endpoint, headers):
    """
    Fetch data from a GoodSAM reporting API endpoint.

    Args:
        session: aiohttp ClientSession
        gs_auth: GoodSAMAuth (Basic or OAuth Bearer)
        endpoint: API endpoint name (e.g., "getAlertsTriggered")
        headers: HTTP headers including date range parameters

    Returns:
        JSON response from the API

    Raises:
        RuntimeError: If API returns non-200 status code
    """
    url = BASE_URL.rstrip("/") + "/" + endpoint.lstrip("/")
    async with session.get(url, ssl=False, **_merge_request_kwargs(gs_auth, headers)) as resp:
        text = await resp.text()
        if resp.status != 200:
            raise RuntimeError(f"API {endpoint} returned {resp.status}{_scope_hint(resp.status)}: {text[:200]}")
        return await resp.json()


async def fetch_goodsam_responder_directory(session, gs_auth):
    """
    Fetch the global responder directory from GoodSAM.

    This directory contains additional responder information including
    registrationAuthority data that may not be in the alerted responders list.
    Used to enrich responder records with missing Registration Body info.

    Args:
        session: aiohttp ClientSession
        gs_auth: GoodSAMAuth (Basic or OAuth Bearer)

    Returns:
        JSON response containing responder directory data
    """
    url = RESPONDER_DIRECTORY_URL
    async with session.get(url, ssl=False, **_merge_request_kwargs(gs_auth)) as resp:
        text = await resp.text()
        if resp.status != 200:
            raise RuntimeError(f"API getResponders returned {resp.status}{_scope_hint(resp.status)}: {text[:200]}")
        try:
            return await resp.json()
        except (ValueError, aiohttp.ContentTypeError):
            return json.loads(text)


def _read_winhttp_proxy():
    """
    Read the machine-wide WinHTTP proxy (what `netsh winhttp show proxy` reports).

    Corporate networks (e.g. NSW Health) often configure browsers via a PAC file
    with ProxyEnable=0, which Python/aiohttp cannot see. The WinHTTP proxy is
    usually set to the same outbound proxy, so we use it as a fallback.

    Returns "http://host:port" or None.
    """
    if sys.platform != "win32":
        return None
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Internet Settings\Connections",
        )
        try:
            blob, _ = winreg.QueryValueEx(key, "WinHttpSettings")
        finally:
            winreg.CloseKey(key)
        # Layout: DWORD size, DWORD counter, DWORD flags, DWORD len, proxy bytes, ...
        if len(blob) < 16:
            return None
        flags = int.from_bytes(blob[8:12], "little")
        plen = int.from_bytes(blob[12:16], "little")
        if not (flags & 0x2) or plen == 0:  # 0x2 = PROXY_TYPE_PROXY
            return None
        proxy = blob[16:16 + plen].decode("ascii", "ignore").strip()
    except (OSError, ImportError, ValueError):
        return None
    # Formats: "host:port" or "https=host:port;http=host:port"
    if "=" in proxy:
        parts = dict(p.split("=", 1) for p in proxy.split(";") if "=" in p)
        proxy = parts.get("https") or parts.get("http") or ""
    proxy = proxy.split(";")[0].strip()
    if not proxy:
        return None
    if "://" not in proxy:
        proxy = "http://" + proxy
    return proxy


def get_proxy_candidates():
    """
    Ordered list of proxies to try for the GoodSAM API. None = direct/env-based.

    1. GOODSAM_PROXY environment variable (explicit override; set to "direct" to skip proxies)
    2. HTTPS_PROXY / HTTP_PROXY / IE manual proxy (via urllib.getproxies)
    3. WinHTTP machine proxy
    4. Direct connection
    """
    override = os.environ.get("GOODSAM_PROXY", "").strip()
    if override.lower() == "direct":
        return [None]
    candidates = []
    if override:
        candidates.append(override if "://" in override else "http://" + override)
    sys_proxies = urllib.request.getproxies()
    for k in ("https", "http"):
        if sys_proxies.get(k):
            candidates.append(sys_proxies[k])
    wh = _read_winhttp_proxy()
    if wh:
        candidates.append(wh)
    candidates.append(None)
    seen, out = set(), []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


async def _load_goodsam_data_via(proxy, gs_auth, headers):
    """Fetch all three datasets using one specific proxy (None = direct)."""
    async with aiohttp.ClientSession(trust_env=(proxy is None)) as session:
        if proxy:
            # Route every GET in this session through the proxy
            orig_get = session.get

            def get_with_proxy(*a, **kw):
                kw.setdefault("proxy", proxy)
                return orig_get(*a, **kw)

            session.get = get_with_proxy
        # OAuth: exchange client id/secret for a Bearer token first (1 hour, plenty for one run)
        await gs_auth.ensure_token(session, proxy)
        task_alerts = fetch_goodsam_report(session, gs_auth, "getAlertsTriggered", headers)
        task_resps = fetch_goodsam_report(session, gs_auth, "getAlertedRespondersInfo", headers)
        task_directory = fetch_goodsam_responder_directory(session, gs_auth)
        alerts_json, resps_json, directory_json = await asyncio.gather(
            task_alerts, task_resps, task_directory, return_exceptions=True
        )
        if isinstance(alerts_json, Exception):
            raise alerts_json
        if isinstance(resps_json, Exception):
            raise resps_json
        if isinstance(directory_json, Exception):
            print(f"   ⚠ Responder directory skipped (optional): {directory_json}")
            directory_json = {}  # Directory is optional; proceed without it
        return alerts_json, resps_json, directory_json


def make_goodsam_auth(username=None, password=None, client_id=None, client_secret=None):
    """
    Build GoodSAMAuth. Explicit client id/secret → OAuth. Otherwise, if the
    "password" is an API client secret (starts with gsk_), treat username/password
    as client id/secret so the GUIs work unchanged; else legacy Basic auth.
    """
    if client_id and client_secret:
        return GoodSAMAuth(client_id=client_id, client_secret=client_secret)
    if password and password.startswith("gsk_"):
        return GoodSAMAuth(client_id=username, client_secret=password)
    return GoodSAMAuth(username=username, password=password)


async def load_goodsam_data(username, password, start_date, end_date, client_id=None, client_secret=None):
    """
    Fetch alerts, responders, and responder directory in parallel from GoodSAM API.

    This is the main entry point for fetching GoodSAM data via API.
    Uses async to fetch all three datasets simultaneously for better performance.

    Args:
        username: GoodSAM API username (email), or API client id
        password: GoodSAM API password, or API client secret (gsk_...)
        start_date: Start date/time string (format: "yyyy-MM-dd HH:mm:ss")
        end_date: End date/time string (format: "yyyy-MM-dd HH:mm:ss")
        client_id / client_secret: OAuth 2.0 API client credentials (preferred)

    Returns:
        Tuple of (alerts_json, responders_json, directory_json)

    Note:
        Date range is interpreted in Australia/Sydney timezone (datesAreInUtc=false)
    """
    headers = {
        "Accept": "application/json",
        "startDate": start_date,
        "endDate": end_date,
        "datesAreInUtc": "false",  # Dates are in Australia/Sydney timezone
        "includeAlertsFromOtherOrgsWhereYourRespondersBeenNotifiedTo": "true",
        "includeAlertedRespondersTimingInformation": "true",
        "includeTimingInformation": "true",
    }
    # Try each proxy candidate in turn (corporate proxy first, then direct).
    # Only connection-level failures fall through; HTTP errors (e.g. 401 bad
    # password) are raised immediately since another route won't fix them.
    # A rejected token request raises RuntimeError and is NOT retried on another
    # route – repeated OAuth failures get the IP blocked for up to 4 hours.
    gs_auth = make_goodsam_auth(username, password, client_id, client_secret)
    print("🔐 GoodSAM auth: " + ("OAuth API client" if gs_auth.is_oauth else "legacy API username/password"))
    last_err = None
    for proxy in get_proxy_candidates():
        label = proxy or "direct connection"
        try:
            print(f"🌐 Connecting to GoodSAM via {label}...")
            return await _load_goodsam_data_via(proxy, gs_auth, headers)
        except (aiohttp.ClientConnectionError, aiohttp.ClientProxyConnectionError,
                asyncio.TimeoutError, OSError) as e:
            print(f"   ⚠ {label} failed: {e}")
            last_err = e
        except aiohttp.ClientResponseError as e:
            if e.status == 407:
                print(f"   ⚠ {label} requires proxy authentication (407)")
                last_err = e
                continue
            raise
    raise last_err

# ============================================================
# GOODSAM DATA FLATTENING
# ============================================================
# Functions to convert nested JSON API responses into flat DataFrames
# with column names matching the expected downstream processing

def flatten_goodsam_alerts(alerts_json: list | dict | None) -> pd.DataFrame:
    """
    Convert GoodSAM alerts JSON to a flat DataFrame.

    Extracts alert information from the nested JSON structure and creates
    a DataFrame with column names matching the expected CSV format.

    Args:
        alerts_json: JSON response from getAlertsTriggered API endpoint

    Returns:
        DataFrame with columns:
        - Integer ID: Unique numeric identifier for the alert
        - String ID: String identifier (UUID)
        - Reference: Alert reference number
        - Rule Used: Dispatch rule name
        - Latitude/Longitude: GPS coordinates
        - Registered Time(Australia/Sydney): When alert was created
        - Cancellation Time: When alert was cancelled (if applicable)
        - Cancellation Type: Type of cancellation
        - Messages: Chat messages formatted as "<UtcMillis>timestamp<UtcMillis> : sender > message"

    Note:
        Messages are joined with double spaces to match legacy CSV format
    """
    info = alerts_json.get("alertsInformation", []) or []
    rows = []
    for a in info:
        # Flatten alert messages into a single string
        # Format: "<UtcMillis>timestamp<UtcMillis> : sender > message  <UtcMillis>..."
        msgs = a.get("alertMessages", []) or []
        msg_strs = []
        for m in msgs:
            t = m.get("messageTimeUtcMillis", "")
            s = m.get("sender", "")
            msg = m.get("message", "")
            msg_strs.append(f"<UtcMillis>{t}<UtcMillis> : {s} > {msg}")
        messages = "  ".join(msg_strs)  # Double space separator

        # Map API fields to expected CSV column names
        rows.append({
            "Integer ID": a.get("alertUniqueIntegerId", ""),
            "String ID": a.get("ID", ""),
            "Reference": a.get("reference", ""),
            "Rule Used": a.get("dispatchRule", ""),
            "Latitude": a.get("alertLatitude", ""),
            "Longitude": a.get("alertLongitude", ""),
            "Registered Time(Australia/Sydney)": a.get("alertTimeFormattedDate", ""),
            "Cancellation Time": a.get("cancellationTimeFormattedDate", ""),
            "Cancellation Type": a.get("cancellationType", ""),
            "Messages": messages,
        })
    return pd.DataFrame(rows, dtype=str)


def flatten_goodsam_responders(resps_json: list | dict | None) -> pd.DataFrame:
    """
    Convert GoodSAM responders JSON to a flat DataFrame.

    Extracts responder and timing information from nested JSON and normalizes
    various date/time fields from multiple possible sources (FormattedDate, epoch millis, etc.)

    Args:
        resps_json: JSON response from getAlertedRespondersInfo API endpoint

    Returns:
        DataFrame with columns for:
        - Responder identification (Integer Alert ID, Alert Reference, names, contact info)
        - Timeline data (Activity Trigger Time, Assigned Time, Acceptance/Rejection/Dropped times, etc.)
        - Clinical data (if present: falseAlarm, patientGender, airway, breathing, etc.)
        - Registration info (Registration Body, Category/Team, Verifying Organisation)

    Note:
        This function handles multiple naming variations for the same field
        (e.g., "Assigned Time" vs "Notification Time") and normalizes them.
        It also enriches timing fields from the embedded alertedRespondersTimingInformation object.
    """
    info = resps_json.get("alertedRespondersInfo", []) or []
    if not info:
        return pd.DataFrame(dtype=str)

    df = pd.DataFrame(info)

    # Capture a copy of the registration description before we rename/drop columns
    reg_source = None
    for cand in (
        "registrationBody",
        "registrationAuthority",
        "registrationAuthorityName",
        "registrationAuthorityText",
    ):
        if cand in df.columns:
            reg_source = df[cand].copy()
            break

    timing_df = None
    if "alertedRespondersTimingInformation" in df.columns:
        timing_df = df["alertedRespondersTimingInformation"].apply(pd.Series)

    def _fill_time_column(target: str, sources: list[str]):
        if target not in df.columns:
            df[target] = pd.NA
        mask = _is_blank(df[target])
        if not mask.any():
            return
        for src in sources:
            source_series = None
            if timing_df is not None and src in timing_df.columns:
                source_series = timing_df[src]
            elif src in df.columns:
                source_series = df[src]
            if source_series is None:
                continue
            normalized = _normalise_time_values(source_series, src)
            if normalized is None:
                continue
            df.loc[mask, target] = normalized
            mask = _is_blank(df[target])
            if not mask.any():
                break

    _fill_time_column("Activity Trigger Time", [
        "alertRegistrationTimeFormattedDate",
        "alertRegistrationTimeUtcFormattedDate",
        "alertRegistrationTime",
        "alertRegistrationTimeUtcMillis",
    ])
    _fill_time_column("Assigned Time", [
        "assignedTimeFormattedDate",
        "assignedTime",
        "assignedTimeUtcMillis",
        "notificationTimeFormattedDate",
        "notificationTime",
        "notificationTimeUtcMillis",
        "alertedResponderAssignedTimeFormattedDate",
        "alertedResponderNotificationTimeFormattedDate",
    ])
    _fill_time_column("Acceptance Time", [
        "acceptanceTimeFormattedDate",
        "acceptanceTime",
        "acceptanceTimeUtcMillis",
    ])
    _fill_time_column("Rejection Time", [
        "rejectionTimeFormattedDate",
        "rejectionTime",
        "rejectionTimeUtcMillis",
    ])
    _fill_time_column("Dropped Time", [
        "droppedTimeFormattedDate",
        "droppedTime",
        "droppedTimeUtcMillis",
    ])
    _fill_time_column("On Scene Time", [
        "onSceneTimeFormattedDate",
        "onSceneTime",
        "onSceneTimeUtcMillis",
    ])
    _fill_time_column("With Patient Time", [
        "withPatientTimeFormattedDate",
        "withPatientTime",
        "withPatientTimeUtcMillis",
    ])
    _fill_time_column("Defib Obtained Time", [
        "defibObtainedTimeFormattedDate",
        "defibObtainedTime",
        "defibObtainedTimeUtcMillis",
    ])
    _fill_time_column("Feedback Time", [
        "feedbackTimeFormattedDate",
        "feedbackTime",
        "feedbackTimeUtcMillis",
    ])

    # Rename to your legacy headers used by the build
    df = df.rename(columns={
        "alertUniqueIntegerId": "Integer Alert ID",
        "alertReference": "Alert Reference",
        "respondersLatitude": "Responders Lat",
        "respondersLongitude": "Responders Lng",
        "respondersOrganisation": "Verifying Organisation",
        "respondersTeamName": "Category/Team",
        "respondersEmail": "Email",
        "respondersPhoneNumber": "Phone Number",
        "firstName": "First Name",
        "lastName": "Last Name",
        # If present in payload:
        "registrationBody": "Registration Body",
        "registrationAuthority": "Registration Body",
        "responderCallStatus": "Status",
        "falseAlarm": "falseAlarm",
        "patientGender": "patientGender",
        "natureOfEmergency": "natureOfEmergency",
        "priorCare": "priorCare",
        "airway": "airway",
        "breathing": "breathing",
        "circulation": "circulation",
        "disability": "disability",
        "respiratoryRate": "respiratoryRate",
        "firstPulse": "firstPulse",
        "jawThurst": "jawThurst",
        "chinLift": "chinLift",
        "nasopharyngeal": "nasopharyngeal",
        "oropharngeal": "oropharngeal",
        "intubation": "intubation",
        "position": "position",
        "defibrillation": "defibrillation",
        "usedAedId": "usedAedId",
        "usedAedReference": "usedAedReference",
        "numberOfShocks": "numberOfShocks",
        "cprProvided": "cprProvided",
        "CPRDuration": "CPRDuration",
        "otherInterventions": "otherInterventions",
        "outcome": "outcome",
        "additionalInfo": "additionalInfo",
        "responderInjuryIncident": "responderInjuryIncident",
        "responderWelfareRequest": "responderWelfareRequest",
    })

    if "Registration Body" not in df.columns:
        df["Registration Body"] = ""
    if reg_source is not None:
        df["Registration Body"] = reg_source

    return df.astype(str)


def flatten_goodsam_responder_directory(directory_json: list | dict | None) -> pd.DataFrame:
    """Return a DataFrame for the global responder directory."""
    rows: list[dict] = []
    if isinstance(directory_json, list):
        rows = directory_json
    elif isinstance(directory_json, dict):
        for key in (
            "responders",
            "responderDetails",
            "responderList",
            "respondersList",
            "items",
            "data",
        ):
            val = directory_json.get(key)
            if isinstance(val, list):
                rows = val
                break
        else:
            # if dict values are lists, pick the first list
            for val in directory_json.values():
                if isinstance(val, list):
                    rows = val
                    break
    return pd.DataFrame(rows or [], dtype=str)




# ============================================================
# REDCAP FIELD CONFIGURATION
# ============================================================
# **IMPORTANT**: When REDCap database schema changes, update these constants
#
# OUTPUT_COLUMNS: Defines ALL possible REDCap fields in their output order
# This list may be dynamically extended if more duplicate alerts/responders
# are encountered than the pre-allocated slots below (e.g., >8 duplicate alerts)
OUTPUT_COLUMNS = [
    # REDCap system fields
    "record_id",                    # Unique identifier for each alert (assigned sequentially)
    "redcap_repeat_instrument",     # "" (empty) for base row, "responders" for repeating rows
    "redcap_repeat_instance",       # Instance number for repeating instruments (1, 2, 3, ...)

    # Base alert fields (populated on base rows only)
    "alertref",                     # GoodSAM Alert Reference number
    "casedate",                     # Alert date (dd/mm/yyyy) from Registered Time
    "lat","long",                   # Alert GPS coordinates
    "messages",                     # Alert messages (chat log)
    "rule",                         # Dispatch rule used
    "duplicate_2",                  # Flag: 1 if duplicate alerts exist, 0 otherwise
    "times_realerted",              # Count of how many times this alert was re-triggered
    "any_responders",               # Flag: 1 if alert had responders, 0 if no responders

    # Primary alert data
    "integerid","stringalt","regtime","gscanc","canctype","nosam_1",

    # Duplicate alert slots (suffixed _2 through _15 for up to 15 duplicate alerts)
    # If more than 15 duplicates exist, additional columns are added dynamically
    "integerid_2","stringalt_2","regtime_2","gscanc_2","canctype_2","nosam_1_2","messages_2",
    "integerid_3","stringalt_3","regtime_3","gscanc_3","canctype_3","messages_3",
    "integerid_4","stringalt_4","regtime_4","gscanc_4","canctype_4","messages_4",
    "integerid_5","stringalt_5","regtime_5","gscanc_5","canctype_5","messages_5",
    "integerid_6","stringalt_6","regtime_6","gscanc_6","canctype_6","messages_6",
    "integerid_7","stringalt_7","regtime_7","gscanc_7","canctype_7","messages_7",
    "integerid_8","stringalt_8","regtime_8","gscanc_8","canctype_8","messages_8",

    # Responder identification fields (populated on responder rows)
    "name1","name2",                # First and last name
    "phone","eml",                  # Contact info (phone normalized to Australian format)
    "verify","reg",                 # Verifying organisation and registration body
    "category",                     # Category/Team
    "resplat","resplong",           # Responder GPS coordinates

    # Responder duplicate tracking
    "how_many_alerts",              # How many times this responder was alerted for this job
    "accept_yesno",                 # 1 if responder accepted ANY alert, 0 otherwise

    # Clinical/feedback fields (populated from instance with most complete data)
    # **IMPORTANT**: These fields are NOT duplicated (no _1, _2, _3 suffixes)
    # When a responder is alerted multiple times, we automatically pick the instance
    # with the most valuable clinical data (prioritizing adinfo text content)
    # **CHANGE THIS**: Add/remove clinical fields as needed for your REDCap database
    "adinfo",                       # Additional info (free text - HEAVILY PRIORITIZED in selection)
    "falsealm",                     # False alarm flag
    "ptgen",                        # Patient gender
    "natemerg",                     # Nature of emergency
    "priorcare",                    # Prior care provided
    "airway",                       # Airway status
    "breathing",                    # Breathing status
    "circ",                         # Circulation status
    "disability",                   # Disability status
    "resprate",                     # Respiratory rate
    "pulse",                        # First pulse
    "jawth",                        # Jaw thrust
    "chinlft",                      # Chin lift
    "naso",                         # Nasopharyngeal airway
    "oro",                          # Oropharyngeal airway
    "intubate",                     # Intubation
    "position",                     # Position
    "defibn",                       # Defibrillation
    "aedid",                        # AED ID used
    "aedref",                       # AED reference
    "nshocks",                      # Number of shocks
    "cprprov",                      # CPR provided
    "cprdurtn",                     # CPR duration
    "othint",                       # Other interventions
    "outcome",                      # Outcome
    "injinc",                       # Responder injury incident
    "welreq",                       # Welfare request flag

    # Primary responder timeline data (suffixed _1, except hour which is calculated once)
    "gsresp_1","assign_1","hour","accept_1","reject_1","drop_1","scene_1","pt_1","defib_1","fdbck_1",

    # Duplicate responder slots (suffixed _2 through _15 for up to 15 times alerted)
    # If a responder is alerted >15 times for one job, additional columns are added dynamically
    # Note: hour is not duplicated - only calculated once for the first alert
    "gsresp_2","assign_2","accept_2","reject_2","drop_2","scene_2","pt_2","defib_2","fdbck_2",
    "gsresp_3","assign_3","accept_3","reject_3","drop_3","scene_3","pt_3","defib_3","fdbck_3",
    "gsresp_4","assign_4","accept_4","reject_4","drop_4","scene_4","pt_4","defib_4","fdbck_4",
    "gsresp_5","assign_5","accept_5","reject_5","drop_5","scene_5","pt_5","defib_5","fdbck_5",
    "gsresp_6","assign_6","accept_6","reject_6","drop_6","scene_6","pt_6","defib_6","fdbck_6",
    "gsresp_7","assign_7","accept_7","reject_7","drop_7","scene_7","pt_7","defib_7","fdbck_7",
    "gsresp_8","assign_8","accept_8","reject_8","drop_8","scene_8","pt_8","defib_8","fdbck_8",
]

# ============================================================
# DUPLICATE HANDLING CONFIGURATION
# ============================================================
# When the same alert is triggered multiple times (same day + alert reference),
# we collapse them into ONE base row and store additional data using suffixed fields

# Flag field that indicates whether duplicates exist (1=yes, 0=no)
# **CHANGE THIS** if REDCap renames this field
DUPLICATE_FLAG_COLUMN = "duplicate_2"

# Field that stores the total count of duplicate alerts
# **CHANGE THIS** if REDCap renames this field
DUPLICATE_TOTAL_COLUMN = "times_realerted"

# Alert fields to duplicate with suffixes (_2, _3, etc.) when duplicates exist
# **CHANGE THIS** if you add/remove alert fields that should be preserved for duplicates
ALERT_DUPLICATE_FIELDS = [
    "integerid",    # Integer ID of the duplicate alert
    "stringalt",    # String ID of the duplicate alert
    "regtime",      # Registered time of the duplicate alert
    "gscanc",       # Cancellation time of the duplicate alert
    "canctype",     # Cancellation type of the duplicate alert
    "nosam_1",      # Additional field
    "messages"      # Alert messages (chat log) for duplicate alert
]

# ============================================================
# RESPONDER DUPLICATE CONFIGURATION
# ============================================================
# When the same responder is alerted multiple times for ONE job,
# we collapse them into ONE responder row and store timeline data using suffixed fields

# Field that stores how many times the responder was alerted for this job
# **CHANGE THIS** if REDCap renames this field
RESP_DUPLICATE_TOTAL_COLUMN = "how_many_alerts"

# Field that indicates if responder accepted ANY of the alerts (1=yes, 0=no)
# **CHANGE THIS** if REDCap renames this field
RESP_DUPLICATE_ACCEPT_COLUMN = "accept_yesno"

# Responder timeline fields to duplicate with suffixes (_2, _3, etc.)
# **CHANGE THIS** if you add/remove responder timeline fields
# Note: These are base field names WITHOUT the _1 suffix (it's added automatically)
RESPONDER_DUPLICATE_FIELDS = [
    "gsresp",   # Response status (Accepted/Rejected/NotSeen/etc.)
    "assign",   # Assigned time
    "accept",   # Acceptance time
    "reject",   # Rejection time
    "drop",     # Dropped time
    "scene",    # On-scene time
    "pt",       # With patient time
    "defib",    # Defib obtained time
    "fdbck"     # Feedback time
]
# Normalise messages to match the hand-prepared CSV style
# - <UtcMillis> (no spaces inside tag)
# - one space around ":" and ">"
# - exactly two spaces between consecutive <UtcMillis>…<UtcMillis> blocks
# - convert unicode spaces to ASCII space
# - keep two trailing spaces at the end (to match the hand file)
# Force 'messages' to the hand-prepared style:
# - convert unicode spaces to ASCII
# - ensure **two spaces** before every '<UtcMillis>' that is **not** at the very start
# - keep exactly two trailing spaces at end
# keep this once (near the top with imports)
def uppercase_bool_strings(s: pd.Series) -> pd.Series:
    def norm(v):
        txt = str(v)
        t = txt.strip().lower()
        if t == "true":
            return "TRUE"
        if t == "false":
            return "FALSE"
        return txt  # leave anything else exactly as-is
    return s.map(norm)


def blank_false_like_strings(df: pd.DataFrame | None, column_basenames: list[str]) -> None:
    """Replace case-insensitive 'FALSE' strings with blanks for given columns (incl. suffixed variants)."""
    if df is None or df.empty or not column_basenames:
        return
    base_set = list(column_basenames)
    targets = [
        col
        for col in df.columns
        if any(col == base or col.startswith(f"{base}_") for base in base_set)
    ]
    for col in targets:
        series = df[col]
        try:
            mask = series.astype(str).str.strip().str.upper().eq("FALSE")
        except (AttributeError, TypeError):
            mask = pd.Series([False] * len(series), index=series.index)
        if mask.any():
            df.loc[mask, col] = ""
def _get_col(df, name):
    return df[name].astype(str) if name in df.columns else pd.Series([""] * len(df), dtype=str)

debug_dir = None  # global placeholder
LAST_MASTER_PATH = None  # global placeholder for GUI integration

MISSING_VALUE_TOKENS = {"", "unknown", "n/a", "na", "none", "null", "not provided", "<na>", "<nan>"}


def _is_blank(series: pd.Series) -> pd.Series:
    if series is None or series.empty:
        return pd.Series([], dtype=bool)
    s = series.astype(str).str.strip()
    lowered = s.str.lower()
    return series.isna() | lowered.isin(MISSING_VALUE_TOKENS)


def _format_millis_series(series: pd.Series) -> pd.Series:
    if series is None or series.empty:
        return pd.Series([], dtype=str)
    nums = pd.to_numeric(series, errors="coerce")
    valid_mask = nums.notna() & (nums > 0)
    out = pd.Series([""] * len(series), index=series.index, dtype=object)
    if not valid_mask.any():
        return out
    subset = nums[valid_mask]
    dt = pd.to_datetime(subset, unit="ms", errors="coerce", utc=True)
    if SYDNEY_TZ:
        try:
            dt = dt.dt.tz_convert(SYDNEY_TZ)
        except (TypeError, AttributeError):  # No timezone info or already localized
            pass
    dt = dt.dt.tz_localize(None)
    formatted = dt.dt.strftime("%d/%m/%Y %H:%M:%S").fillna("")
    out.loc[valid_mask] = formatted
    return out


def _normalise_time_values(series: pd.Series | None, source_name: str = "") -> pd.Series | None:
    if series is None:
        return None
    work = series.copy()
    if work.empty:
        return work
    # Detect epoch millis either by column name or numeric content
    lower_name = source_name.lower()
    is_millis_col = "millis" in lower_name or "epoch" in lower_name
    # We also treat numeric-only columns as millis candidates
    numeric = pd.to_numeric(work, errors="coerce")
    numeric_mask = numeric.notna()
    millis_mask = numeric_mask & ((is_millis_col) | (numeric.abs() > 1e10))
    result = pd.Series([""] * len(work), index=work.index, dtype=object)
    if millis_mask.any():
        result.loc[millis_mask] = _format_millis_series(numeric[millis_mask])
    text_mask = ~millis_mask
    if text_mask.any():
        text_series = work[text_mask].astype(str)
        result.loc[text_mask] = to_ddmmyyyy_hhmmss(text_series).astype(str)
    result = result.fillna("")
    return result

def drop_and_report(df: pd.DataFrame, label: str, patterns: tuple = ("ANSW test", "stagetest", "stage test")) -> pd.DataFrame:
    """Drop rows that look like test data and, if debug_dir is set, write them to a CSV.

    **CHANGE THIS** patterns parameter if you need to filter different test data patterns.
    """
    global debug_dir
    if df is None or df.empty:
        safe_print(f"[TEST-DROP] {label}: no rows to check.")
        return df

    rx = re.compile("|".join(re.escape(p) for p in patterns), flags=re.IGNORECASE)
    mask = df.astype(str).apply(lambda col: col.str.contains(rx, na=False)).any(axis=1)
    dropped = df[mask]

    if not dropped.empty:
        if debug_dir is not None:
            try:
                debug_dir.mkdir(parents=True, exist_ok=True)
                dropped_path = debug_dir / f"dropped_{label.lower()}_test_rows.csv"
                dropped.to_csv(dropped_path, index=False, encoding="utf-8")
                safe_print(f"[TEST-DROP] Dropped {len(dropped)} {label} rows → {dropped_path.name}")
            except Exception as e:
                safe_print(f"[TEST-DROP] Dropped {len(dropped)} {label} rows (could not write file: {e})")
        else:
            safe_print(f"[TEST-DROP] Dropped {len(dropped)} {label} rows (debug_dir not set; not writing file).")
    else:
        safe_print(f"[TEST-DROP] No test rows found in {label}")

    return df[~mask].copy()


def build_master_responder_list(
    resps_source: pd.DataFrame,
    alerts_source: pd.DataFrame | None = None,
    string_id_map: dict[str, str] | None = None,
) -> pd.DataFrame:
    """
    Build the 'Master Responder List' directly from the original responders CSV.
    - Keeps interstate rows (no 5-digit Alert Reference filter)
    - Drops test rows (NSWA TEST in Category/Team) if present
    - Preserves lat/lng exactly if available, otherwise blank
    - Normalises datetime columns to dd/mm/yyyy hh:mm:ss
    - Phone numbers normalised (+61/61 -> 0) but free text preserved
    - Activity Trigger Time pulled from alert registration time in timing information
    """
    # Remove responder tests (keep this consistent with your main build)
    if "Category/Team" in resps_source.columns:
        resps_use = resps_source[~resps_source["Category/Team"].astype(str)
                                 .str.contains("NSWA TEST", case=False, na=False)].copy()
    else:
        resps_use = resps_source.copy()

    resps_use = normalize_responder_columns(resps_use)

    # Pick lat/lng source column names (same robust logic as the main build)
    lat_src = pick_first_column(resps_use, [
        "Responders Lat", "Resonders Lat", "Responder Lat", "Responder Latitude", "Responders Latitude",
    ])
    lng_src = pick_first_column(resps_use, [
        "Responders Lng", "Responders Long", "Resonders Lng",
        "Responder Lng", "Responder Longitude", "Responders Longitude",
    ])

    # Columns (in the exact order you want)
    master_cols = [
        "Integer Alert ID","String Alert ID","Responders Lat","Responders Lng","Alert Reference",
        "Category/Team","Activity Trigger Time","Assigned Time","Acceptance Time","Rejection Time",
        "Dropped Time","On Scene Time","With Patient Time","Defib Obtained Time","Feedback Time",
        "First Name","Last Name","Verifying Organisation","Registration Body","Email","Phone Number",
        "Status","falseAlarm","patientGender","natureOfEmergency","priorCare","airway","breathing",
        "circulation","disability","respiratoryRate","firstPulse","jawThurst","chinLift",
        "nasopharyngeal","oropharngeal","intubation","position","defibrillation","usedAedId",
        "usedAedReference","numberOfShocks","cprProvided","CPRDuration","otherInterventions",
        "outcome","additionalInfo","responderInjuryIncident","responderWelfareRequest"
    ]

    df = pd.DataFrame({c: _get_col(resps_use, c) for c in master_cols})

    # Override lat/lng into the final column names (exact pass-through)
    if lat_src:
        df["Responders Lat"] = _get_col(resps_use, lat_src)
    if lng_src:
        df["Responders Lng"] = _get_col(resps_use, lng_src)

    # Normalise date/time fields to dd/mm/yyyy hh:mm:ss (only if there's content)
    time_cols = [
        "Activity Trigger Time","Assigned Time","Acceptance Time","Rejection Time",
        "Dropped Time","On Scene Time","With Patient Time","Defib Obtained Time","Feedback Time"
    ]
    for c in time_cols:
        if c in df.columns:
            df[c] = to_ddmmyyyy_hhmmss(df[c])

    # Populate String Alert ID from provided map if column missing/blank
    if "String Alert ID" not in df.columns:
        df["String Alert ID"] = ""
    if string_id_map:
        norm_int = _get_col(df, "Integer Alert ID").str.strip()
        mapped = norm_int.map(lambda x: string_id_map.get(x, ""))
        mask_blank = df["String Alert ID"].astype(str).str.strip().eq("")
        df.loc[mask_blank, "String Alert ID"] = mapped[mask_blank]

    # Phone normalisation (keep free text)
    if "Phone Number" in df.columns:
        df["Phone Number"] = df["Phone Number"].map(lambda x: fix_au_phone(x) if isinstance(x, str) else x)

    # Do NOT force welreq case; pass through exactly
    # No further filtering (we already removed NSWA TEST above)

    # Sort chronologically by Assigned Time (earliest first)
    # Convert to datetime for sorting, handling blanks/invalid values
    if "Assigned Time" in df.columns:
        df["_sort_assigned"] = pd.to_datetime(df["Assigned Time"], format="%d/%m/%Y %H:%M:%S", errors="coerce")
        df = df.sort_values("_sort_assigned", na_position="last").drop(columns=["_sort_assigned"])

    return df[master_cols]




def read_csv_text(path: str) -> pd.DataFrame:
    try:
        return pd.read_csv(path, dtype=str, keep_default_na=False, na_filter=False, encoding="utf-8-sig")
    except UnicodeDecodeError:
        return pd.read_csv(path, dtype=str, keep_default_na=False, na_filter=False, encoding="latin-1")

def normalize_text_series(s: pd.Series) -> pd.Series:
    """NBSP -> space, collapse whitespace to single spaces, strip ends."""
    return (
        s.astype(str)
         .str.replace("\u00A0", " ", regex=False)   # NBSP to space
         .str.replace(r"\s+", " ", regex=True)      # collapse whitespace
         .str.strip()
    )


def normalize_responder_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Map legacy responder CSV columns (e.g., Notification Time) to expected names."""
    if df is None or df.empty:
        return df

    assign_col = "Assigned Time"
    if assign_col not in df.columns:
        df[assign_col] = ""

    notif_col = pick_first_column(df, [
        "Notification Time",
        "notificationTime",
        "Notification time",
    ])
    if notif_col:
        assign_series = df[assign_col].astype(str)
        mask = assign_series.str.strip().eq("")
        if mask.any():
            df.loc[mask, assign_col] = df.loc[mask, notif_col].astype(str)

    return df


def safe_print(msg: str, file=None) -> None:
    """Print safely on Windows consoles that aren't UTF-8."""
    target = file or sys.stdout
    try:
        print(msg, file=target)
    except UnicodeEncodeError:
        enc = (target.encoding or "ascii") if hasattr(target, "encoding") else "ascii"
        buffer = getattr(target, "buffer", None)
        data = msg.encode(enc, errors="replace") + b"\n"
        if buffer is not None:
            buffer.write(data)
            buffer.flush()
        else:
            target.write(msg + "\n")


# ============================================================
# REDCAP API INTEGRATION
# ============================================================
# Functions to upload data to REDCap via the REST API
# Supports both PyCap library and direct HTTP requests (urllib/requests)

def post_to_redcap(
    df: pd.DataFrame,
    api_url: str,
    api_token: str,
    verify: bool = True,
    batch_size: int = 100,
    force_auto_number: bool = False,
) -> int:
    """
    Import records to REDCap using the 'flat' format with repeating instruments.

    This function handles:
    - Batching large uploads into smaller chunks
    - Filtering fields to only those defined in the REDCap project
    - Fallback from PyCap to direct HTTP if needed
    - Error handling for 504 timeouts (confirms upload actually succeeded)

    Args:
        df: DataFrame with REDCap-formatted data (must include record_id, redcap_repeat_instrument, etc.)
        api_url: REDCap API URL (e.g., "https://server/redcap/api/")
        api_token: REDCap API token for the project
        verify: Whether to verify SSL certificates (set False for self-signed certs)
        batch_size: Number of records to upload per batch (default 100)
        force_auto_number: Let REDCap auto-assign record_ids (usually False)

    Returns:
        Total number of records REDCap reports as imported

    Raises:
        RuntimeError: If API returns error or unexpected response
    """
    if df is None or df.empty:
        return 0

    # Ensure no NaN and cast to basic Python types
    # Filter to only fields that exist in project (plus REDCap reserved fields)
    reserved = {"record_id", "redcap_repeat_instrument", "redcap_repeat_instance", "redcap_event_name", "redcap_data_access_group"}
    try:
        allowed = get_redcap_fieldset(api_url, api_token, verify)
    except Exception as _e:
        allowed = set()

    cols = list(df.columns)
    if allowed:
        keep = [c for c in cols if (c in allowed or c in reserved)]
        work_df = df[keep].copy()
    else:
        work_df = df.copy()

    # Drop redcap_data_access_group to avoid invalid DAG errors unless user truly wants it
    if "redcap_data_access_group" in work_df.columns:
        try:
            work_df = work_df.drop(columns=["redcap_data_access_group"])  # safer default
        except KeyError:  # Column doesn't exist
            pass

    payload_rows = work_df.replace({np.nan: ""}).to_dict(orient="records")

    total_imported = 0

    # Try PyCap first if available (lets REDCap handle chunking server-side where possible)
    if REDCapProject is not None:
        try:
            safe_print("[REDCap] Using PyCap library")
            # Some versions accept verify_ssl kw; fall back silently if not
            try:
                proj = REDCapProject(api_url, api_token, verify_ssl=verify)
            except TypeError:
                proj = REDCapProject(api_url, api_token)

            records = payload_rows
            for i in range(0, len(records), max(1, int(batch_size))):
                chunk = records[i:i + max(1, int(batch_size))]
                base_kwargs = dict(
                    format='json',
                    overwrite='normal',
                    return_content='count',
                    type='flat',
                    date_format='DMY',
                )

                def _call_import(param_name: str):
                    kw = base_kwargs.copy()
                    kw[param_name] = chunk
                    try:
                        return proj.import_records(**kw, force_auto_number=force_auto_number)
                    except TypeError:
                        return proj.import_records(**kw)

                try:
                    res = _call_import("data")
                except TypeError:
                    res = _call_import("records")
                # PyCap may return {'count': N}
                if isinstance(res, dict) and 'count' in res:
                    total_imported += int(res['count'])
                else:
                    # Attempt to parse text
                    m = re.search(r'\bcount\b\D*(\d+)', str(res))
                    total_imported += int(m.group(1)) if m else len(chunk)
            return total_imported
        except Exception as e:
            safe_print(f"[REDCap] PyCap import failed, falling back to direct POST: {e}")
    for i in range(0, len(payload_rows), max(1, int(batch_size))):
        chunk = payload_rows[i:i + max(1, int(batch_size))]
        chunk_record_ids = [
            str(row.get("record_id", "")).strip()
            for row in chunk
            if str(row.get("record_id", "")).strip()
        ]
        data = {
            "token": api_token,
            "content": "record",
            "format": "json",
            "type": "flat",
            "overwriteBehavior": "normal",
            "data": json.dumps(chunk, ensure_ascii=False),
            "returnContent": "count",
            "returnFormat": "json",
            "dateFormat": "DMY",
        }
        if force_auto_number:
            data["forceAutoNumber"] = "1"

        # Send using requests if available; otherwise fall back to urllib
        if requests is not None:
            resp = requests.post(api_url, data=data, timeout=120, verify=verify)
            if resp.status_code != 200:
                body = resp.text or ""
                if resp.status_code == 504 and not body.strip():
                    safe_print("[REDCap] HTTP 504 with empty body; polling REDCap to confirm chunk status...")
                    if _confirm_chunk_uploaded(chunk, api_url, api_token, verify):
                        safe_print("[REDCap] Chunk confirmed in REDCap after 504; continuing.")
                        total_imported += len(chunk)
                        continue
                raise RuntimeError(f"HTTP {resp.status_code}: {body[:500]}")

            # Parse count from JSON; some servers return text/json hybrids
            count = None
            try:
                j = resp.json()
                if isinstance(j, dict) and "count" in j:
                    count = int(j["count"])  # expected successful response
            except (ValueError, KeyError, TypeError):
                pass
            if count is None:
                m = re.search(r'"count"\s*:\s*(\d+)', resp.text)
                if m:
                    count = int(m.group(1))
        else:
            ctx = None
            if not verify:
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
            encoded = urllib.parse.urlencode(data).encode("utf-8")
            req = urllib.request.Request(api_url, data=encoded, method="POST")
            try:
                with urllib.request.urlopen(req, context=ctx) as r:
                    body = r.read().decode("utf-8", errors="replace")
            except urllib.error.HTTPError as e:
                err_body = e.read().decode("utf-8", errors="replace")
                if e.code == 504 and not err_body.strip():
                    safe_print("[REDCap] HTTP 504 with empty body; polling REDCap to confirm chunk status...")
                    if _confirm_chunk_uploaded(chunk, api_url, api_token, verify):
                        safe_print("[REDCap] Chunk confirmed in REDCap after 504; continuing.")
                        total_imported += len(chunk)
                        continue
                raise RuntimeError(f"HTTP {e.code}: {err_body[:500]}") from e
            # parse count from body
            count = None
            try:
                j = json.loads(body)
                if isinstance(j, dict) and "count" in j:
                    count = int(j["count"])  # expected successful response
            except (ValueError, KeyError, TypeError):
                pass
            if count is None:
                m = re.search(r'"count"\s*:\s*(\d+)', body)
                if m:
                    count = int(m.group(1))

        if count is None:
            # As a fallback, assume success and add chunk length
            count = len(chunk)
        total_imported += count

    return total_imported


def export_record_id_map_by_integerid(api_url: str, api_token: str, verify: bool, integerids: list[str]) -> dict[str, str]:
    """Return a map from integerid -> record_id by exporting from REDCap.

    Uses filterLogic to limit to the provided integer IDs. Falls back to full export if logic is too large.
    """
    if not integerids:
        return {}

    # Build filter logic: ([integerid] = 'X') OR ([integerid] = 'Y') ...
    terms = [f"[integerid] = '{str(v).replace("'", "\\'")}'" for v in integerids if str(v).strip()]
    logic = " or ".join(terms)

    # PyCap path
    if REDCapProject is not None:
        try:
            try:
                proj = REDCapProject(api_url, api_token, verify_ssl=verify)
            except TypeError:
                proj = REDCapProject(api_url, api_token)
            try:
                recs = proj.export_records(fields=['record_id', 'integerid'], filter_logic=logic, format='json')
            except TypeError:
                # Older versions may use different keyword; try without logic as a fallback
                recs = proj.export_records(fields=['record_id', 'integerid'], format='json')
            mapping = {}
            for r in recs:
                iid = str(r.get('integerid', '')).strip()
                rid = str(r.get('record_id', '')).strip()
                if iid and rid:
                    mapping[iid] = rid
            return mapping
        except Exception as e:
            safe_print(f"[REDCap] PyCap export failed, falling back to HTTP: {e}")

    # HTTP path
    data = {
        'token': api_token,
        'content': 'record',
        'format': 'json',
        'type': 'flat',
        'fields[0]': 'record_id',
        'fields[1]': 'integerid',
    }
    if logic:
        data['filterLogic'] = logic

    if requests is not None:
        resp = requests.post(api_url, data=data, timeout=120, verify=verify)
        resp.raise_for_status()
        recs = resp.json()
    else:
        encoded = urllib.parse.urlencode(data).encode('utf-8')
        ctx = None
        try:
            import ssl as _ssl
            ctx = _ssl.create_default_context()
            if not verify:
                ctx.check_hostname = False
                ctx.verify_mode = _ssl.CERT_NONE
        except (ImportError, AttributeError):
            ctx = None
        with urllib.request.urlopen(urllib.request.Request(api_url, data=encoded, method='POST'), context=ctx) as r:
            body = r.read().decode('utf-8', errors='replace')
        try:
            recs = json.loads(body)
        except (ValueError, json.JSONDecodeError):
            recs = []

    mapping = {}
    for r in recs or []:
        iid = str(r.get('integerid', '')).strip()
        rid = str(r.get('record_id', '')).strip()
        if iid and rid:
            mapping[iid] = rid
    return mapping


def get_redcap_fieldset(api_url: str, api_token: str, verify: bool = True) -> set[str]:
    """Fetch project metadata and return a set of field_names in the REDCap project."""
    # Try PyCap first
    if REDCapProject is not None:
        try:
            try:
                proj = REDCapProject(api_url, api_token, verify_ssl=verify)
            except TypeError:
                proj = REDCapProject(api_url, api_token)
            meta = proj.export_metadata(format='json')
            return {str(m.get('field_name', '')).strip() for m in (meta or []) if m.get('field_name')}
        except (ValueError, AttributeError, RuntimeError):  # REDCap API errors
            pass
    # HTTP fallback
    data = {
        'token': api_token,
        'content': 'metadata',
        'format': 'json',
    }
    if requests is not None:
        r = requests.post(api_url, data=data, timeout=60, verify=verify)
        r.raise_for_status()
        meta = r.json()
    else:
        encoded = urllib.parse.urlencode(data).encode('utf-8')
        with urllib.request.urlopen(urllib.request.Request(api_url, data=encoded, method='POST')) as rr:
            body = rr.read().decode('utf-8', errors='replace')
        try:
            meta = json.loads(body)
        except Exception:
            meta = []
    return {str(m.get('field_name', '')).strip() for m in (meta or []) if m.get('field_name')}


def get_next_record_id(api_url: str, api_token: str, verify: bool = True) -> int:
    """
    Return the next numeric record_id (max existing numeric id + 1),
    or 1 if none found. Uses minimal export of record_id values.
    """
    data = {
        'token': api_token,
        'content': 'record',
        'format': 'json',
        'type': 'flat',
        'fields[0]': 'record_id',
    }

    recs = []
    if requests is not None:
        r = requests.post(api_url, data=data, timeout=60, verify=verify)
        r.raise_for_status()
        try:
            recs = r.json() or []
        except (ValueError, json.JSONDecodeError):
            recs = []
    else:
        encoded = urllib.parse.urlencode(data).encode('utf-8')
        ctx = None
        try:
            import ssl as _ssl
            ctx = _ssl.create_default_context()
            if not verify:
                ctx.check_hostname = False
                ctx.verify_mode = _ssl.CERT_NONE
        except (ImportError, AttributeError):
            ctx = None
        with urllib.request.urlopen(urllib.request.Request(api_url, data=encoded, method='POST'), context=ctx) as rr:
            body = rr.read().decode('utf-8', errors='replace')
        try:
            recs = json.loads(body) or []
        except (ValueError, json.JSONDecodeError):
            recs = []

    nums = []
    for r in recs:
        rid = str(r.get('record_id', '')).strip()
        if rid.isdigit():
            try:
                nums.append(int(rid))
            except ValueError:
                pass
    return (max(nums) + 1) if nums else 1


def _export_redcap_records(
    api_url: str,
    api_token: str,
    fields: list[str],
    records: list[str] | None = None,
    verify: bool = True,
) -> list[dict]:
    """Helper to export specific fields/records via the REDCap API."""
    data = {
        'token': api_token,
        'content': 'record',
        'format': 'json',
        'type': 'flat',
    }
    for idx, field in enumerate(fields):
        data[f'fields[{idx}]'] = field
    if records:
        for idx, rec in enumerate(records):
            data[f'records[{idx}]'] = str(rec)

    if requests is not None:
        resp = requests.post(api_url, data=data, timeout=120, verify=verify)
        resp.raise_for_status()
        try:
            return resp.json() or []
        except (ValueError, json.JSONDecodeError):
            return []
    encoded = urllib.parse.urlencode(data).encode('utf-8')
    ctx = None
    if not verify:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    with urllib.request.urlopen(urllib.request.Request(api_url, data=encoded, method='POST'), context=ctx) as rr:
        body = rr.read().decode('utf-8', errors='replace')
    try:
        return json.loads(body) or []
    except (ValueError, json.JSONDecodeError):
        return []


def _confirm_chunk_uploaded(
    chunk: list[dict],
    api_url: str,
    api_token: str,
    verify: bool,
) -> bool:
    """Best-effort confirmation that a chunk reached REDCap (used after HTTP 504)."""
    if not chunk:
        return False
    base_rows: dict[str, str] = {}
    record_ids: list[str] = []
    for row in chunk:
        rid = str(row.get("record_id", "")).strip()
        if not rid:
            continue
        record_ids.append(rid)
        inst = str(row.get("redcap_repeat_instrument", "")).strip()
        if not inst and rid not in base_rows:
            base_rows[rid] = str(row.get("regtime", "")).strip()
    record_ids = sorted(set(record_ids))
    if not record_ids or not base_rows:
        return False
    try:
        exported = _export_redcap_records(
            api_url=api_url,
            api_token=api_token,
            fields=["record_id", "regtime"],
            records=record_ids,
            verify=verify,
        )
    except (ValueError, RuntimeError, OSError):  # API/network errors
        return False
    lookup = {str(r.get("record_id", "")).strip(): str(r.get("regtime", "")).strip() for r in exported}
    for rid, expected_reg in base_rows.items():
        seen_reg = lookup.get(rid)
        if not seen_reg:
            return False
        if expected_reg and seen_reg != expected_reg:
            return False
    return True


def get_latest_record_context(api_url: str, api_token: str, verify: bool = True) -> dict[str, int | str | None]:
    """
    Return a dict with the next record_id, the most recent record_id, and that record's regtime.
    Useful for deriving start-id/start-time for automated runs.
    """
    next_id = get_next_record_id(api_url, api_token, verify)
    last_id = next_id - 1 if next_id and next_id > 1 else None
    last_regtime = None
    if last_id and last_id > 0:
        recs = _export_redcap_records(
            api_url=api_url,
            api_token=api_token,
            fields=['record_id', 'regtime'],
            records=[str(last_id)],
            verify=verify,
        )
        if recs:
            last_regtime = str(recs[0].get('regtime', '')).strip()
    return {
        "next_record_id": next_id,
        "last_record_id": last_id,
        "last_regtime": last_regtime,
    }


# Default values for required REDCap fields (currently empty - add defaults here if REDCap requires them)
# **CHANGE THIS** if REDCap database starts requiring default values for base row fields
# Example: BASE_REQUIRED_DEFAULTS = {"some_field": "default_value"}
BASE_REQUIRED_DEFAULTS: dict[str, str] = {}

# Default values for required responder fields (currently empty - add defaults here if REDCap requires them)
# **CHANGE THIS** if REDCap database starts requiring default values for responder row fields
# Example: RESP_REQUIRED_DEFAULTS = {"some_field": "default_value"}
RESP_REQUIRED_DEFAULTS: dict[str, str] = {
    "resplat": "",   # Responder latitude (blank if not provided)
    "resplong": "",  # Responder longitude (blank if not provided)
}


def _map_gsresp_value(row: dict) -> str:
    val = str(row.get("gsresp_1", "")).strip().lower()
    mapping = {
        "accepted": "Accepted",
        "accept": "Accepted",
        "accepted_true": "Accepted",
        "rejected": "Rejected",
        "reject": "Rejected",
        "notseen": "NotSeen",
        "not seen": "NotSeen",
        "unseen": "NotSeen",
        "acceptedbutdroppedlater": "AcceptedButDroppedLater",
        "accepted_but_dropped_later": "AcceptedButDroppedLater",
        "dropped": "AcceptedButDroppedLater",
    }
    if val in mapping:
        return mapping[val]
    try:
        drop_time = str(row.get("drop_1", "")).strip()
        accept_time = str(row.get("accept_1", "")).strip()
        if drop_time:
            return "AcceptedButDroppedLater"
        if accept_time:
            return "Accepted"
    except (KeyError, AttributeError, TypeError):
        pass
    return "NotSeen"


# Alternative column names for Registration Body field in GoodSAM data
# The script will check these column names in order and use the first one found
# **CHANGE THIS** if GoodSAM adds new column name variations
REGISTRATION_ALT_KEYS = [
    "Registration Body",
    "registrationBody",
    "registrationAuthority",
    "registeringBody",
    "registration_body",
    "RegistrationBody",
    "registrationbody",
    "respondersRegistrationBody",
    "respondersRegistrationBodyName",
    "registrationBodyName",
]


def populate_registration_body(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure the 'Registration Body' column is populated if alternate fields exist."""
    if df is None or df.empty:
        return df

    work = df
    if "Registration Body" not in work.columns:
        work["Registration Body"] = ""

    reg_series = work["Registration Body"].astype(str)
    mask = reg_series.str.strip().eq("")

    for key in REGISTRATION_ALT_KEYS:
        if key == "Registration Body":
            continue
        if key in work.columns:
            source = work[key].astype(str).str.strip()
            work.loc[mask, "Registration Body"] = source[mask]
            mask = work["Registration Body"].astype(str).str.strip().eq("")
            if not mask.any():
                break

    return work


def enrich_registration_from_directory(
    responders_df: pd.DataFrame, directory_df: pd.DataFrame
) -> pd.DataFrame:
    """Fill missing Registration Body values using the responder directory data."""
    if responders_df is None or responders_df.empty:
        return responders_df
    if directory_df is None or directory_df.empty:
        return responders_df

    fillable_fields = [
        "Registration Body",
        "First Name",
        "Last Name",
        "Verifying Organisation",
        "Email",
        "Phone Number",
    ]
    resp_work = responders_df
    for col in fillable_fields:
        if col not in resp_work.columns:
            resp_work[col] = ""

    def _clean_text(series: pd.Series | None, lower: bool = False) -> pd.Series:
        if series is None:
            return pd.Series([""] * len(directory_df), index=directory_df.index)
        base = (
            series.astype(str)
            .fillna("")
            .str.strip()
        )
        lowered = base.str.lower()
        base = base.mask(lowered.isin(MISSING_VALUE_TOKENS), "")
        if lower:
            return base.str.lower()
        return base

    def _clean_phone(series: pd.Series | None) -> pd.Series:
        if series is None:
            return pd.Series([""] * len(directory_df), index=directory_df.index)
        base = _clean_text(series, lower=False)
        return base.map(lambda v: fix_au_phone(v) if v else "")

    dir_work = directory_df.copy()
    dir_lookup = pd.DataFrame(index=dir_work.index)

    reg_col = pick_first_column(dir_work, [
        "registrationAuthority",
        "registration_authority",
        "registrationAuthorityName",
        "registrationAuthorityText",
    ])
    dir_lookup["Registration Body"] = _clean_text(dir_work[reg_col]) if reg_col else ""

    first_col = pick_first_column(dir_work, ["firstName", "First Name"])
    last_col = pick_first_column(dir_work, ["lastName", "Last Name"])
    org_col = pick_first_column(dir_work, ["organisationsName", "organisationName", "organizationName", "organisation"])
    email_col = pick_first_column(dir_work, ["email", "Email", "respondersEmail"])
    phone_col = pick_first_column(dir_work, ["mobileNumber", "phoneNumber", "mobile", "phone"])

    dir_lookup["First Name"] = _clean_text(dir_work[first_col]) if first_col else ""
    dir_lookup["Last Name"] = _clean_text(dir_work[last_col]) if last_col else ""
    dir_lookup["Verifying Organisation"] = _clean_text(dir_work[org_col]) if org_col else ""
    dir_lookup["Email"] = _clean_text(dir_work[email_col]) if email_col else ""
    dir_lookup["Phone Number"] = _clean_phone(dir_work[phone_col]) if phone_col else ""

    # Drop rows where we have nothing to contribute
    if not dir_lookup[fillable_fields].apply(lambda row: any(row.astype(str).str.strip()), axis=1).any():
        return resp_work

    dir_lookup["_email_key"] = _clean_text(dir_work[email_col], lower=True) if email_col else ""
    dir_lookup["_phone_key"] = _clean_phone(dir_work[phone_col]) if phone_col else ""

    def _build_lookup(key_col: str) -> dict[str, dict[str, str]]:
        if not key_col or key_col not in dir_lookup.columns:
            return {}
        subset = dir_lookup.loc[dir_lookup[key_col].astype(str).str.strip() != ""]
        if subset.empty:
            return {}
        subset = subset.drop_duplicates(key_col, keep="first")
        return subset.set_index(key_col)[fillable_fields].to_dict("index")

    email_lookup = _build_lookup("_email_key")
    phone_lookup = _build_lookup("_phone_key")

    if not email_lookup and not phone_lookup:
        return resp_work

    def _is_missing(series: pd.Series) -> pd.Series:
        base = series.astype(str).fillna("").str.strip()
        return base.eq("") | base.str.lower().isin(MISSING_VALUE_TOKENS)

    email_resp_col = pick_first_column(resp_work, ["Email", "email"])
    phone_resp_col = pick_first_column(resp_work, ["Phone Number", "phone", "PhoneNumber"])

    resp_email_keys = (
        _clean_text(resp_work[email_resp_col], lower=True)
        if email_resp_col
        else None
    )
    resp_phone_keys = (
        _clean_phone(resp_work[phone_resp_col])
        if phone_resp_col
        else None
    )

    def _apply_lookup(lookup: dict[str, dict[str, str]], key_series: pd.Series | None) -> None:
        if not lookup or key_series is None:
            return
        match_series = key_series.map(lambda k: lookup.get(k, None))
        if match_series.isna().all():
            return
        for field in fillable_fields:
            missing_mask = _is_missing(resp_work[field])
            if not missing_mask.any():
                continue
            fill_values = match_series.map(lambda data: (data or {}).get(field, ""))
            fill_mask = missing_mask & fill_values.astype(str).str.strip().ne("")
            if fill_mask.any():
                resp_work.loc[fill_mask, field] = fill_values[fill_mask]

    _apply_lookup(email_lookup, resp_email_keys)
    _apply_lookup(phone_lookup, resp_phone_keys)

    return resp_work


def apply_redcap_default_fields(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure required REDCap fields exist / have defaults for base and responder rows."""
    if df is None or df.empty:
        return df

    repeat_col = df.get("redcap_repeat_instrument")
    if repeat_col is None:
        mask_base = pd.Series([True] * len(df))
        mask_resp = pd.Series([False] * len(df))
    else:
        repeat_series = repeat_col.astype(str).str.strip()
        mask_base = repeat_series.eq("")  # Base rows have empty redcap_repeat_instrument
        mask_resp = repeat_series.eq("responders")

    for col, default in BASE_REQUIRED_DEFAULTS.items():
        if col not in df.columns:
            df[col] = ""
        series = df[col].astype(str)
        df.loc[mask_base & series.str.strip().eq(""), col] = default

    for col, default in RESP_REQUIRED_DEFAULTS.items():
        if col not in df.columns:
            df[col] = ""
        series = df[col].astype(str)
        df.loc[mask_resp & series.str.strip().eq(""), col] = default

    if "gsresp_1" in df.columns and mask_resp.any():
        sub = df.loc[mask_resp]
        mapped = []
        for _, row in sub.iterrows():
            mapped.append(_map_gsresp_value(row.to_dict()))
        df.loc[mask_resp, "gsresp_1"] = mapped

    return df


def _handle_no_responder_rows(args, resps_all: pd.DataFrame | None) -> None:
    safe_print("[INFO] GoodSAM returned no responder rows. Nothing to import.")
    empty_cols = ["record_id"] + [c for c in OUTPUT_COLUMNS if c != "record_id"]
    out = pd.DataFrame(columns=empty_cols)
    out.to_csv(
        args.out,
        index=False,
        encoding="utf-8-sig",
        quoting=csv.QUOTE_MINIMAL,
        lineterminator="\r\n",
    )
    follow_cols = [
        "record_id", "redcap_repeat_instance", "name1", "name2", "phone", "eml",
        "category"
    ]
    follow_path = os.path.join(os.path.dirname(os.path.abspath(args.out)), "welreq_followup.csv")
    pd.DataFrame(columns=follow_cols).to_csv(
        follow_path,
        index=False,
        encoding="utf-8-sig",
        quoting=csv.QUOTE_ALL,
        lineterminator="\r\n",
    )
    safe_print(f"[WELREQ] Wrote welfare follow-up list (0 rows): {follow_path}")
    master_path = os.path.splitext(args.out)[0] + "_master_responder_list.csv"
    master_df = resps_all if resps_all is not None else pd.DataFrame()
    master_df.to_csv(master_path, index=False, encoding="utf-8-sig", lineterminator="\r\n")
    safe_print("Master responder rows: 0")
    safe_print(f"Master responder CSV:  {master_path}")
    global LAST_MASTER_PATH
    LAST_MASTER_PATH = master_path
    safe_print("=== REDCap build (Integer ID linkage + alertref de-dupe + phone normalisation) ===")
    safe_print("Alerts kept:     0")
    safe_print("Responders kept: 0")
    safe_print("Distinct IDs:    0")
    safe_print("Total rows:      0")
    safe_print(f"Output:          {args.out}")
    sys.exit(0)


def upload_csv_to_redcap(csv_path: Path, args) -> None:
    if not args.redcap_token:
        safe_print("[ERROR] --redcap-token is required to upload to REDCap.")
        sys.exit(2)
    if not csv_path.exists():
        safe_print(f"[ERROR] Upload CSV not found: {csv_path}")
        sys.exit(2)

    safe_print(f"[UPLOAD] Loading CSV for REDCap import: {csv_path}")
    upload_df = read_csv_text(str(csv_path))
    if upload_df.empty:
        safe_print("[INFO] CSV has no rows. Nothing to upload.")
        sys.exit(0)
    upload_df = upload_df.dropna(how="all")
    if "record_id" in upload_df.columns:
        rid_mask = upload_df["record_id"].astype(str).str.strip() != ""
        missing = int((~rid_mask).sum())
        if missing:
            safe_print(f"[WARN] Skipping {missing} CSV rows with empty record_id before upload.")
        upload_df = upload_df.loc[rid_mask]
    if upload_df.empty:
        safe_print("[INFO] CSV has no valid rows after cleaning. Nothing to upload.")
        sys.exit(0)

    upload_df = apply_redcap_default_fields(upload_df)
    if args.redcap_event_name:
        upload_df["redcap_event_name"] = args.redcap_event_name

    rc_url = args.redcap_url or "https://nswa-redcap.ambulance.nsw.gov.au/redcap/api/"
    try:
        imported_count = post_to_redcap(
            upload_df,
            api_url=rc_url,
            api_token=args.redcap_token,
            verify=not args.redcap_insecure,
            batch_size=max(1, int(args.redcap_batch_size or 100)),
        )
        safe_print(f"[REDCap] Upload complete: {imported_count} records imported.")
    except Exception as e:
        safe_print(f"[REDCap] Upload failed: {e}")
        sys.exit(2)
    sys.exit(0)


def _parse_datetime_series(series: pd.Series) -> pd.Series:
    if series is None:
        return pd.Series(dtype="datetime64[ns]")
    s = series.astype(str)
    iso_mask = s.str.match(r"^\d{4}-\d{2}-\d{2}")
    result = pd.Series(pd.NaT, index=s.index, dtype="datetime64[ns]")
    if iso_mask.any():
        result.loc[iso_mask] = pd.to_datetime(s.loc[iso_mask], errors="coerce", dayfirst=False)
    if (~iso_mask).any():
        result.loc[~iso_mask] = pd.to_datetime(s.loc[~iso_mask], errors="coerce", dayfirst=True)
    return result


def norm_series(s: pd.Series) -> pd.Series:
    if s is None:
        return pd.Series(dtype=str)
    return s.astype(str).str.strip()

def to_ddmmyyyy_hhmmss(s: pd.Series) -> pd.Series:
    """
    Parse a pandas Series of datetimes and output strings as dd/mm/yyyy hh:mm:ss.
    Blank if parsing fails.
    """
    dt = _parse_datetime_series(s)
    return dt.dt.strftime("%d/%m/%Y %H:%M:%S").fillna("")
def pick_first_column(df: pd.DataFrame, candidates: list[str]) -> str | None:
    """Return the first column name from candidates that exists in df, else None."""
    for name in candidates:
        if name in df.columns:
            return name
    return None



def to_casedate_ddmmyyyy(s: pd.Series) -> pd.Series:
    dt = _parse_datetime_series(s)
    return dt.dt.strftime("%d/%m/%Y").fillna("")


def to_hour_hh(s: pd.Series) -> pd.Series:
    dt = _parse_datetime_series(s)
    h = dt.dt.hour.astype("Int64").astype(str).replace("<NA>", "")
    h = h.apply(lambda x: f"{int(x):02d}" if x.isdigit() else (x if len(x)==2 else ""))
    return h


# Convert Australian country-code numbers to local format while preserving any free text.
# Examples:
#   "+61 412 345 678" -> "0412 345 678"
#   "61-2-9876 1234"  -> "02-9876 1234"
#   "dont call +61 412 345 678 before 11am" -> "dont call 0412 345 678 before 11am"
# Australian phone number normalization pattern
# Converts +61 or 61 prefixes to 0 (e.g., "+61 412 345 678" → "0412 345 678")
# **CHANGE THIS** if phone number format requirements change
PHONE_CC_RE = re.compile(r'(?<!\d)\+?61[\s\-\.\(\)]*0?(\d)')

def fix_au_phone(text: str) -> str:
    if not text:
        return text
    return PHONE_CC_RE.sub(r'0\1', text)

def read_csv_forgiving(path: Path) -> pd.DataFrame:
    """
    Read CSV robustly:
      - forces all columns to string
      - ignores bad lines or encoding issues
      - replaces NaN with empty string
    """
    try:
        df = pd.read_csv(path, dtype=str, keep_default_na=False, na_values=[], encoding_errors="ignore")
        return df
    except Exception as e:
        safe_print(f"⚠️  Could not read {path.name}: {e}")
        return pd.DataFrame()




def main():
    """
    Main entry point for GoodSAM to REDCap data pipeline.

    PROCESSING FLOW:
    ----------------
    1. Parse command-line arguments
    2. Either:
       a) Fetch data from GoodSAM API (if --username/--password provided), OR
       b) Read from CSV files (if --alerts/--responders provided), OR
       c) Upload existing CSV to REDCap (if --upload-input provided)
    3. Filter and clean data:
       - Drop test rows (containing "ANSW test", "stagetest", etc.)
       - Keep only 5-digit Reference alerts (NSW only, drops interstate)
       - Keep only 5-digit Alert Reference responders (NSW only, drops interstate)
       - Filter responders to match existing alerts (alerts without responders are kept)
    4. Build REDCap rows:
       - Create base rows (alerts) with deduplication by (casedate, alertref)
       - Create repeating rows (responders) with deduplication by responder identity
    5. Apply data transformations:
       - Normalize phone numbers (+61 → 0)
       - Format dates as dd/mm/yyyy HH:MM:SS
       - Extract hour from Assigned Time
       - Clean boolean fields (TRUE/FALSE uppercase)
    6. Write output files:
       - Main REDCap CSV
       - Master responder list (includes interstate)
       - Welfare request follow-up CSV
    7. Optionally upload to REDCap via API

    USAGE EXAMPLES:
    ---------------
    # Fetch from API and build CSV:
    python GS2RCAPI.py --username user@example.com --password xxx \\
        --start-date "2024-01-01 00:00:00" --end-date "2024-01-31 23:59:59" \\
        --out output.csv --start-id 1000

    # Build from CSV files:
    python GS2RCAPI.py --alerts Alert.csv --responders Responder.csv \\
        --out output.csv --start-id 1000

    # Upload existing CSV to REDCap:
    python GS2RCAPI.py --upload-input output.csv \\
        --redcap-token YOUR_TOKEN --redcap-url https://server/redcap/api/
    """
    ap = argparse.ArgumentParser(description="Combine Alert.csv and Responder.csv (Integer ID linkage only).")
    ap.add_argument("--alerts", help="Path to Alert.csv (optional if using API mode)")
    ap.add_argument("--responders", help="Path to Responder.csv (optional if using API mode)")
    ap.add_argument("--out", help="Output CSV path")
    ap.add_argument("--start-id", type=int, help="Starting REDCap record_id (required when building)")
    ap.add_argument("--username", help="GoodSAM API username (email)")
    ap.add_argument("--password", help="GoodSAM API password (or an API client secret gsk_..., with the client id as --username)")
    ap.add_argument("--client-id", default=os.environ.get("GOODSAM_CLIENT_ID"),
                    help="GoodSAM OAuth API client id (or env GOODSAM_CLIENT_ID)")
    ap.add_argument("--client-secret", default=os.environ.get("GOODSAM_CLIENT_SECRET"),
                    help="GoodSAM OAuth API client secret (or env GOODSAM_CLIENT_SECRET)")
    ap.add_argument("--start-date", help="Start date (yyyy-MM-dd HH:mm:ss)")
    ap.add_argument("--end-date", help="End date (yyyy-MM-dd HH:mm:ss)")
    # REDCap API import options
    # **CHANGE THIS** if your REDCap server URL changes
    ap.add_argument("--redcap-url", help="REDCap API URL (e.g. https://server/redcap/api/")
    # REDCap API token (get this from your REDCap project's API settings page)
    ap.add_argument("--redcap-token", help="REDCap API token")
    ap.add_argument("--redcap-batch-size", type=int, default=100, help="REDCap import batch size (default 100)")
    ap.add_argument("--redcap-insecure", action="store_true", help="Disable TLS verification for REDCap requests")
    # **CHANGE THIS** if your longitudinal project event name changes
    ap.add_argument("--redcap-event-name", help="REDCap event unique name (for longitudinal projects); applies to all rows")
    ap.add_argument("--upload-input", help="Existing CSV to upload to REDCap (skips build phase)")
    ap.add_argument("--no-save-api-json", action="store_true", help="Skip saving raw GoodSAM API JSON dumps")

    args = ap.parse_args()

    if args.upload_input:
        if not args.out:
            args.out = args.upload_input
        upload_csv_to_redcap(Path(args.upload_input), args)
        return
    if not args.out:
        print("?? --out is required when building a new CSV.")
        sys.exit(1)
    # Enforce one valid mode: API or CSV
    have_api_creds = bool((args.username and args.password) or (args.client_id and args.client_secret))
    if not have_api_creds and not (args.alerts and args.responders):
        print("?? You must provide either GoodSAM API credentials or both Alert and Responder CSV paths.")
        sys.exit(1)

    if args.start_id is None:
        print("?? --start-id is required when building a new CSV.")
        sys.exit(1)
    # ... inside main(), right after argparse & basic validation:

    global debug_dir
    # Resolve output path to absolute, then get parent for debug dir
    out_path = Path(args.out).resolve()
    debug_dir = out_path.parent / "_debug"
    try:
        debug_dir.mkdir(parents=True, exist_ok=True)
    except (PermissionError, OSError) as e:
        safe_print(f"⚠️  Warning: Cannot create debug directory ({e}). Debug files will be skipped.")
        debug_dir = None

    # ============================================================
    # FETCH DATA - either from API or CSV
    # ============================================================
    if have_api_creds:
        try:
            start_date = args.start_date or datetime.now().strftime("%Y-%m-%d 00:00:00")
            end_date   = args.end_date   or datetime.now().strftime("%Y-%m-%d 23:59:59")

            alerts_json, resps_json, directory_json = asyncio.run(
                load_goodsam_data(args.username, args.password, start_date, end_date,
                                  client_id=args.client_id, client_secret=args.client_secret)
            )

            if not args.no_save_api_json and debug_dir:
                try:
                    (debug_dir / "alerts_api.json").write_text(json.dumps(alerts_json, indent=2), encoding="utf-8")
                    (debug_dir / "responders_api.json").write_text(json.dumps(resps_json, indent=2), encoding="utf-8")
                    (debug_dir / "responder_directory.json").write_text(json.dumps(directory_json, indent=2), encoding="utf-8")
                except (OSError, IOError):  # File write errors
                    pass

            alerts = flatten_goodsam_alerts(alerts_json)
            resps_raw = flatten_goodsam_responders(resps_json)
            directory_df = flatten_goodsam_responder_directory(directory_json)
            resps  = populate_registration_body(resps_raw)
            resps  = normalize_responder_columns(resps)
            resps  = enrich_registration_from_directory(resps, directory_df)
            resps_all = resps.copy()

            safe_print(f"✅ Alerts received: {len(alerts)}")
            safe_print(f"✅ Responders received: {len(resps)}")

            # mirror dataframes used by your later drop/log helpers
            df_trig = alerts.copy()
            df_resp = resps.copy()

        except Exception as e:
            safe_print(f"❌ GoodSAM API fetch failed: {e}")
            safe_print("🔁 Attempting CSV fallback...")

            # Only fallback if BOTH CSVs were supplied. Otherwise, stop gracefully.
            if not (args.alerts and args.responders):
                safe_print(
                    "❌ API failed and no CSV files were provided.\n"
                    "   Please either:\n"
                    "   • fix network/DNS to use the API, OR\n"
                    "   • select both Alert.csv and Responder.csv in the GUI."
                )
                sys.exit(2)

            alerts = read_csv_text(args.alerts)
            resps  = populate_registration_body(read_csv_text(args.responders))
            resps  = normalize_responder_columns(resps)
            resps_all = resps.copy()

            df_trig = read_csv_forgiving(Path(args.alerts))
            df_resp = read_csv_forgiving(Path(args.responders))

    else:
        safe_print("📂 Reading from CSV files…")
        alerts = read_csv_text(args.alerts)
        resps  = populate_registration_body(read_csv_text(args.responders))
        resps  = normalize_responder_columns(resps)
        resps_all = resps.copy()

        df_trig = read_csv_forgiving(Path(args.alerts))
        df_resp = read_csv_forgiving(Path(args.responders))
        # --- Drop and report any test rows (ANSW test / stagetest) -------------------

        

    df_trig = drop_and_report(df_trig, "Alert")
    df_resp = drop_and_report(df_resp, "Responder")

    # ============================================================
    # DATA VALIDATION AND FILTERING
    # ============================================================
    # Link alerts to responders using Integer ID (the ONLY linkage key)
    # Strategy:
    # 1. Keep only alerts with 5-digit Reference (filters out interstate cases)
    # 2. Keep only responders with 5-digit Alert Reference (filters out interstate cases)
    # 3. Keep only responders that match the remaining alerts
    # Note: Alerts without responders are now KEPT (not dropped)

    # Handle case where no alerts were received
    if alerts.empty:
        safe_print("ℹ️  No alerts found in the specified date/time range.")
        safe_print(f"ℹ️  Creating empty output file: {args.out}")
        # Create empty output with just headers
        empty_output = pd.DataFrame(columns=OUTPUT_COLUMNS)
        empty_output.to_csv(args.out, index=False, encoding="utf-8-sig")
        safe_print("✅ Empty output file created successfully.")
        sys.exit(0)

    # Validate required linkage columns exist
    if "Integer ID" not in alerts.columns:
        safe_print("[ERROR] 'Integer ID' column missing from Alert.csv", file=sys.stderr); sys.exit(2)

    # Filter alerts to 5-digit Reference (keeps NSW, drops interstate)
    # Interstate alerts have different reference formats
    # **CHANGE THIS** regex pattern if the reference format changes (currently: exactly 5 digits)
    if "Reference" in alerts.columns:
        alerts = alerts[alerts["Reference"].str.match(r"^\d{5}$", na=False)]

    # Only validate responder columns if we have responders
    if not resps.empty:
        if "Integer Alert ID" not in resps.columns:
            safe_print("[ERROR] 'Integer Alert ID' column missing from Responder.csv", file=sys.stderr); sys.exit(2)

        # Filter responders to 5-digit Alert Reference (keeps NSW, drops interstate)
        # Interstate alerts have different reference formats
        # **CHANGE THIS** regex pattern if the reference format changes (currently: exactly 5 digits)
        if "Alert Reference" in resps.columns:
            resps = resps[resps["Alert Reference"].str.match(r"^\d{5}$", na=False)]

    # Normalize Integer IDs as strings for comparison
    alert_int = norm_series(alerts["Integer ID"])

    # Filter responders to only keep those matching existing alerts
    if not resps.empty:
        resp_int = norm_series(resps["Integer Alert ID"])
        valid_alert_ids = set(alert_int[alert_int != ""])
        resps = resps[resp_int.isin(valid_alert_ids)].copy().reset_index(drop=True)
        resp_int = norm_series(resps["Integer Alert ID"])
    else:
        resp_int = pd.Series([], dtype=str)




    if alerts.empty:
        safe_print("[INFO] After cleaning, there are no alerts to import. Nothing to import.")
        out = pd.DataFrame(columns=["record_id"] + [c for c in OUTPUT_COLUMNS if c != "record_id"])
        out.to_csv(args.out, index=False, encoding="utf-8-sig")
        safe_print(f"Output:          {args.out}")
        safe_print(
            "To upload this CSV later, run: python GS2RCAPI.py --upload-input "
            f"\"{args.out}\" --redcap-token <TOKEN> [--redcap-url <URL>]"
        )
        sys.exit(0)

    

    # ============================================================
    # BUILD BASE (ALERT) ROWS
    # ============================================================
    # Create one row per alert with empty redcap_repeat_instrument
    # These will be deduplicated later if multiple alerts share the same (date, alertref)

    base = pd.DataFrame({c: [""] * len(alerts) for c in OUTPUT_COLUMNS})
    base["record_id"] = 0  # Placeholder; real IDs assigned after deduplication
    # case_details is no longer a repeating instrument
    base["redcap_repeat_instrument"] = ""
    base["redcap_repeat_instance"] = ""  # Empty for base rows (not a repeating instance)

    # Set any_responders field: 1 if alert has responders, 0 if no responders
    # Check if each alert's Integer ID appears in the responder Integer Alert IDs
    if not resps.empty:
        responder_alert_ids = set(resp_int[resp_int != ""])
        base["any_responders"] = alert_int.isin(responder_alert_ids).astype(int).astype(str)
    else:
        base["any_responders"] = "0"

    # ============================================================
    # ALERT FIELD MAPPING: GoodSAM → REDCap
    # ============================================================
    # **CHANGE THIS** when REDCap database adds/removes alert fields
    #
    # Maps GoodSAM CSV column names to REDCap field names
    # Note: Messages field is handled separately (needs exact preservation)
    amap = {
        "Integer ID": "integerid",                          # Unique numeric alert ID
        "String ID": "stringalt",                           # UUID-style alert ID
        "Reference": "alertref",                            # 5-digit alert reference number
        "Rule Used": "rule",                                # Dispatch rule name
        "Registered Time(Australia/Sydney)": "regtime",     # Alert creation timestamp
        "Cancellation Time": "gscanc",                      # Alert cancellation timestamp
        "Cancellation Type": "canctype",                    # Cancellation reason
        # "Messages": "messages",  # Handled separately - MUST preserve exact format
    }
    for src, dst in amap.items():
        if src in alerts.columns:
            base[dst] = norm_series(alerts[src]).to_numpy()

    # Copy Messages EXACTLY as in Alert.csv (no stripping, no normalising)
    if "Messages" in alerts.columns:
        base["messages"] = alerts["Messages"].astype(str).to_numpy()
    # RAW pass-through for alert lat/long (no strip/formatting)
    if "Latitude" in alerts.columns:
        base["lat"] = alerts["Latitude"].astype(str).to_numpy()
    if "Longitude" in alerts.columns:
        base["long"] = alerts["Longitude"].astype(str).to_numpy()




    # casedate from Registered Time as dd/mm/yyyy
    if "Registered Time(Australia/Sydney)" in alerts.columns:
        base["casedate"] = to_casedate_ddmmyyyy(alerts["Registered Time(Australia/Sydney)"])

    # Force alert times to dd/mm/yyyy hh:mm:ss
    if "Registered Time(Australia/Sydney)" in alerts.columns:
        base["regtime"] = to_ddmmyyyy_hhmmss(alerts["Registered Time(Australia/Sydney)"])
    if "Cancellation Time" in alerts.columns:
        base["gscanc"] = to_ddmmyyyy_hhmmss(alerts["Cancellation Time"])

    # ============================================================
    # ALERT DUPLICATE HANDLING
    # ============================================================
    # Collapse multiple alerts with the same (casedate, alertref) into ONE base row.
    # This handles cases where the same incident triggers multiple alerts.
    #
    # Strategy:
    # 1. Group alerts by (casedate, alertref) key
    # 2. Keep the FIRST alert as the primary row
    # 3. Store additional alert data using suffixed columns (e.g., integerid_2, regtime_3)
    # 4. Set duplicate_2=1 and times_realerted=count when duplicates exist
    # 5. If >9 duplicates exist, split into multiple rows with alertref_2, alertref_3, etc.
    #
    # Example:
    #   Input: 3 alerts with alertref "12345" on same day
    #   Output: 1 row with:
    #     - integerid = first alert's ID
    #     - integerid_2 = second alert's ID
    #     - integerid_3 = third alert's ID
    #     - duplicate_2 = "1"
    #     - times_realerted = "3"
    #
    #   Input: 15 alerts with alertref "12345" on same day
    #   Output: 2 rows:
    #     Row 1 (alertref "12345"): alerts 1-9
    #     Row 2 (alertref "12345_2"): alerts 10-15
    #     Both rows share the same responders with full timeline data

    # Initialize duplicate tracking fields
    base[DUPLICATE_FLAG_COLUMN] = "0"  # Will be set to "1" if duplicates exist
    base[DUPLICATE_TOTAL_COLUMN] = "1"  # Will be set to count of alerts
    base["_row_idx"] = np.arange(len(base))  # Track original row order

    # Remove _N suffix from alertref for grouping (some alert refs have suffixes like "12345_2")
    base["_alertref_root"] = base["alertref"].astype(str).str.replace(r"_(\d+)$", "", regex=True)

    # Create grouping key: "casedate||alertref" or unique row key if missing
    casedate_clean = base["casedate"].astype(str).str.strip()
    alertref_clean = base["_alertref_root"].astype(str).str.strip()
    key_mask = casedate_clean.ne("") & alertref_clean.ne("")
    base["_gk"] = np.where(
        key_mask,
        casedate_clean + "||" + alertref_clean,  # Group by date+ref
        "__ROW__" + base["_row_idx"].astype(str),  # Unique key for rows without date/ref
    )
    base["__aid"] = alert_int.to_numpy()  # Store Integer IDs for later responder linking

    # Group alerts and collapse duplicates
    # If a group has >15 duplicates, split into multiple rows to avoid too many columns
    # **CHANGE THIS** to match the value at the top of this file (currently 15)
    # This controls how many duplicate alerts fit in one REDCap row before splitting
    MAX_DUPLICATES_PER_ROW = 15
    grouped = base.groupby("_gk", sort=False)
    collapsed_rows = []
    dynamic_pairs = set()  # Track which suffixed fields we create
    alert_position_map = {}  # Maps alert Integer ID → position in duplicate sequence (1-indexed)

    for _, group in grouped:
        group = group.sort_values("_row_idx", kind="stable")  # Preserve input order
        size = len(group)
        all_alert_ids = group["__aid"].astype(str).tolist()  # All Integer IDs in this group

        # Track the position (1, 2, 3...) of each alert in the duplicate sequence
        for pos, aid in enumerate(all_alert_ids, start=1):
            alert_position_map[aid] = pos

        # If group has ≤15 alerts, use current behavior (one row)
        if size <= MAX_DUPLICATES_PER_ROW:
            first = group.iloc[0].copy()  # Keep first alert as primary
            first[DUPLICATE_FLAG_COLUMN] = "1" if size > 1 else "0"
            first[DUPLICATE_TOTAL_COLUMN] = str(size)
            first["_row_idx"] = int(group["_row_idx"].min())
            first["_group_alert_ids"] = all_alert_ids
            first["_chunk_start"] = 1  # This row covers positions 1-15
            first["_chunk_end"] = size

            # For duplicates (2nd, 3rd, etc.), copy their data to suffixed columns
            if size > 1:
                dup_part = group.iloc[1:]
                for dup_idx, (_, dup_row) in enumerate(dup_part.iterrows(), start=2):
                    for field in ALERT_DUPLICATE_FIELDS:
                        col_name = f"{field}_{dup_idx}"
                        first[col_name] = dup_row.get(field, "")
                        dynamic_pairs.add((field, dup_idx))

            collapsed_rows.append(first)

        # If group has >15 alerts, split into multiple rows
        else:
            # Split alerts into chunks of MAX_DUPLICATES_PER_ROW
            for chunk_num, start_idx in enumerate(range(0, size, MAX_DUPLICATES_PER_ROW), start=1):
                end_idx = min(start_idx + MAX_DUPLICATES_PER_ROW, size)
                chunk = group.iloc[start_idx:end_idx]
                chunk_size = len(chunk)

                # Create a new row based on the first alert in the ORIGINAL group
                new_row = group.iloc[0].copy()

                # Modify alertref to add suffix for chunks after the first
                if chunk_num > 1:
                    original_ref = str(new_row["alertref"])
                    new_row["alertref"] = f"{original_ref}_{chunk_num}"

                # Set duplicate tracking fields for this chunk
                new_row[DUPLICATE_FLAG_COLUMN] = "1" if chunk_size > 1 else "0"
                new_row[DUPLICATE_TOTAL_COLUMN] = str(chunk_size)
                new_row["_row_idx"] = int(group["_row_idx"].min()) + (chunk_num - 1) * 0.01  # Slight offset to maintain order

                # Store ALL alert IDs from the entire original group
                new_row["_group_alert_ids"] = all_alert_ids

                # Track which positions this chunk covers (e.g., chunk 2 covers positions 10-18)
                new_row["_chunk_start"] = start_idx + 1  # Position numbers are 1-indexed
                new_row["_chunk_end"] = end_idx

                # Copy data from first alert in this chunk to base fields
                chunk_first = chunk.iloc[0]
                for field in ALERT_DUPLICATE_FIELDS:
                    new_row[field] = chunk_first.get(field, "")

                # For remaining alerts in this chunk, copy to suffixed columns
                if chunk_size > 1:
                    for dup_idx, (_, dup_row) in enumerate(chunk.iloc[1:].iterrows(), start=2):
                        for field in ALERT_DUPLICATE_FIELDS:
                            col_name = f"{field}_{dup_idx}"
                            new_row[col_name] = dup_row.get(field, "")
                            dynamic_pairs.add((field, dup_idx))

                collapsed_rows.append(new_row)

    base = pd.DataFrame(collapsed_rows).reset_index(drop=True)
    object_cols = [
        c for c in base.select_dtypes(include=["object"]).columns if c != "_group_alert_ids"
    ]
    if object_cols:
        base[object_cols] = base[object_cols].fillna("")

    # Extend OUTPUT_COLUMNS if we created more duplicate fields than pre-allocated
    # (e.g., if we have >8 duplicate alerts, we need integerid_9, integerid_10, etc.)
    if dynamic_pairs:
        field_order = {name: idx for idx, name in enumerate(ALERT_DUPLICATE_FIELDS)}
        dynamic_map = {}
        for field, dup_idx in sorted(dynamic_pairs, key=lambda item: (field_order.get(item[0], 999), item[1])):
            dynamic_map.setdefault(field, []).append(f"{field}_{dup_idx}")

        template_cols = list(OUTPUT_COLUMNS)
        new_cols = []
        for suffixes in dynamic_map.values():
            for col_name in suffixes:
                if col_name not in template_cols and col_name not in new_cols:
                    new_cols.append(col_name)
        if new_cols:
            # Insert new alert duplicate columns right after the pre-allocated ones (after integerid_8, etc.)
            # Find the insertion point: after the last pre-allocated alert duplicate field
            insert_after = None
            for field in ALERT_DUPLICATE_FIELDS:
                last_preallocated = f"{field}_8"
                if last_preallocated in template_cols:
                    idx = template_cols.index(last_preallocated)
                    if insert_after is None or idx > insert_after:
                        insert_after = idx

            if insert_after is not None:
                # Insert new columns right after the last pre-allocated duplicate field
                OUTPUT_COLUMNS[:] = template_cols[:insert_after+1] + new_cols + template_cols[insert_after+1:]
            else:
                # Fallback: append to end if we can't find the insertion point
                OUTPUT_COLUMNS[:] = template_cols + new_cols

            additions = pd.DataFrame({c: [""] * len(base) for c in new_cols})
            base = pd.concat([base, additions], axis=1)

    # Sort by original row order and assign record_ids sequentially
    base = base.sort_values("_row_idx", kind="stable").reset_index(drop=True)
    base["record_id"] = np.arange(len(base), dtype=int) + int(args.start_id)
    base["redcap_repeat_instance"] = ""  # Keep blank for base rows (not a repeating instrument)

    # Build Integer ID → record_id lookup for responder linking
    # IMPORTANT: Each duplicate alert's Integer ID maps to record_id(s) of the collapsed row(s)
    # For split rows (when >9 duplicates), one alert ID can map to MULTIPLE record_ids
    id_map = {}  # Maps alert Integer ID → list of record_ids
    for ids, rid in zip(base["_group_alert_ids"], base["record_id"]):
        if isinstance(ids, list):
            for aid in ids:
                aid_txt = str(aid).strip()
                if aid_txt:
                    # Store as list to handle split rows (multiple record_ids per alert ID)
                    if aid_txt not in id_map:
                        id_map[aid_txt] = []
                    if int(rid) not in id_map[aid_txt]:
                        id_map[aid_txt].append(int(rid))
    base.drop(columns=["_group_alert_ids"], inplace=True, errors="ignore")

    # ============================================================
    # RESPONDER PROCESSING - BUILD REPEATING INSTRUMENT ROWS
    # ============================================================
    # Each responder becomes a "repeating row" linked to their alert's record_id
    # BUT: If the same responder is alerted MULTIPLE TIMES for the SAME JOB,
    # we collapse them into ONE repeating row with timeline data in suffixed columns

    # Choose responder lat/lng column names robustly (handles typos and variations)
    rsp_lat_col = pick_first_column(resps, [
        "Responders Lat", "Resonders Lat",          # common & known typo
        "Responder Lat", "Responder Latitude", "Responders Latitude",
    ])
    rsp_lng_col = pick_first_column(resps, [
        "Responders Lng", "Responders Long", "Resonders Lng",
        "Responder Lng", "Responder Longitude", "Responders Longitude",
    ])

    # Group responders by Integer Alert ID (which alert they were alerted for)
    groups = {}
    for idx, r in resps.iterrows():
        k = str(r.get("Integer Alert ID", "")).strip()
        if not k:
            continue
        r_copy = r.copy()
        r_copy["_source_row_idx"] = idx
        groups.setdefault(k, []).append(r_copy)

    # Map responders to their final record_id(s) using the Integer ID → record_id lookup
    # Remember: Multiple alert Integer IDs may map to the SAME record_id (due to alert deduplication)
    # For split rows (>9 duplicates), one alert ID maps to MULTIPLE record_ids
    # Each responder record also needs to track which alert position it came from
    record_responder_entries = {}
    for aid, rec_ids in id_map.items():
        rsp_list = groups.get(aid, [])
        if rsp_list:
            # Get the position of this alert in the duplicate sequence
            alert_position = alert_position_map.get(aid, 1)

            # Add position information to each responder record
            for rsp in rsp_list:
                rsp["_alert_position"] = alert_position

            # rec_ids is now a list; add responders to all associated record_ids
            for rec_id in rec_ids:
                record_responder_entries.setdefault(rec_id, []).extend(rsp_list)

    repeat_rows = []
    responder_dynamic_pairs = set()  # Track which suffixed responder fields we create

    # Helper to parse datetime-like strings safely while avoiding pandas warnings.
    # Accepts both ISO (YYYY-MM-DD ...) and AU (dd/mm/yyyy ...) formats.
    def _parse_dt_for_sort(x):
        try:
            s = "" if pd.isna(x) else str(x).strip()
            if not s:
                return pd.NaT
            # If string looks ISO-like, do not set dayfirst=True (silences warnings)
            if re.match(r"^\d{4}-\d{2}-\d{2}", s):
                return pd.to_datetime(s, errors="coerce", dayfirst=False)
            # Try explicit AU formats first to avoid inference warnings
            for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M"):
                try:
                    return pd.to_datetime(s, format=fmt, errors="raise")
                except (ValueError, TypeError):
                    pass
            # Fallback: general parse with dayfirst=True for other dd/mm variants
            return pd.to_datetime(s, errors="coerce", dayfirst=True)
        except (ValueError, TypeError):
            return pd.NaT

    def _responder_sort_key(sr):
        t_accept = _parse_dt_for_sort(sr.get("Acceptance Time", ""))
        t_assign = _parse_dt_for_sort(sr.get("Assigned Time", ""))
        missing_accept = pd.isna(t_accept)
        missing_assign = pd.isna(t_assign)
        fn = str(sr.get("First Name", "")).strip().lower()
        ln = str(sr.get("Last Name", "")).strip().lower()
        ph = str(sr.get("Phone Number", "")).strip()
        em = str(sr.get("Email", "")).strip().lower()
        row_idx = sr.get("_source_row_idx", 0)
        return (
            missing_accept, t_accept or pd.Timestamp.max,
            missing_assign, t_assign or pd.Timestamp.max,
            fn, ln, ph, em, row_idx,
        )

    def _build_responder_row(r_series, rec_id):
        """
        Convert a raw responder record into a REDCap repeating row.

        Args:
            r_series: Pandas Series from responders DataFrame
            rec_id: record_id to link this responder to

        Returns:
            Dictionary representing one responder repeating row
        """
        row = {c: "" for c in OUTPUT_COLUMNS}
        row["record_id"] = rec_id
        # **CHANGE THIS** if your REDCap repeating instrument name changes from "responders"
        row["redcap_repeat_instrument"] = "responders"
        row["redcap_repeat_instance"] = ""  # Set later during deduplication

        # ============================================================
        # RESPONDER FIELD MAPPING: GoodSAM → REDCap
        # ============================================================
        # **CHANGE THIS** when REDCap database adds/removes responder fields
        #
        # Maps GoodSAM responder CSV columns to REDCap field names
        # Timeline fields are suffixed with _1 (primary alert)
        # Additional alerts to the same responder use _2, _3, etc. (added during deduplication)
        rmap = {
            # Responder identification
            "Category/Team": "category",                    # Responder category (e.g., "Off Duty Paramedic")
            "First Name": "name1",
            "Last Name": "name2",
            "Email": "eml",
            "Phone Number": "phone",                        # Will be normalized to Australian format
            "Verifying Organisation": "verify",
            "Registration Body": "reg",
            "Responders Lat": "resplat",                    # Responder latitude
            "Responders Lng": "resplong",                   # Responder longitude

            # Timeline data (suffixed with _1 for primary, _2+ for duplicates)
            "Assigned Time": "assign_1",                    # When responder was assigned/notified
            "Acceptance Time": "accept_1",                  # When they accepted
            "Rejection Time": "reject_1",                   # When they rejected
            "Dropped Time": "drop_1",                       # When they dropped the alert
            "On Scene Time": "scene_1",                     # When they arrived on scene
            "With Patient Time": "pt_1",                    # When they reached the patient
            "Defib Obtained Time": "defib_1",               # When they obtained defibrillator
            "Feedback Time": "fdbck_1",                     # When they submitted feedback
            "Status": "gsresp_1",                           # Response status (Accepted/Rejected/NotSeen/etc.)

            # Clinical data fields (if responder submitted feedback)
            "falseAlarm": "falsealm",
            "patientGender": "ptgen",
            "natureOfEmergency": "natemerg",
            "priorCare": "priorcare",
            "airway": "airway",
            "breathing": "breathing",
            "circulation": "circ",
            "disability": "disability",
            "respiratoryRate": "resprate",
            "firstPulse": "pulse",
            "jawThurst": "jawth",
            "chinLift": "chinlft",
            "nasopharyngeal": "naso",
            "oropharngeal": "oro",
            "intubation": "intubate",
            "position": "position",
            "defibrillation": "defibn",
            "usedAedId": "aedid",
            "usedAedReference": "aedref",
            "numberOfShocks": "nshocks",
            "cprProvided": "cprprov",
            "CPRDuration": "cprdurtn",
            "otherInterventions": "othint",
            "outcome": "outcome",
            "additionalInfo": "adinfo",
            "responderInjuryIncident": "injinc",
            "responderWelfareRequest": "welreq",
        }
        for src, dst in rmap.items():
            if src in resps.columns:
                row[dst] = str(r_series.get(src, "")).strip()

        if row.get("phone"):
            row["phone"] = fix_au_phone(row["phone"])

        if row.get("gsresp_1"):
            s = str(row["gsresp_1"]).replace("\u00a0", " ")
            row["gsresp_1"] = re.sub(r"\s+", "", s)

        for _col in ("assign_1","accept_1","reject_1","drop_1","scene_1","pt_1","defib_1","fdbck_1"):
            if row.get(_col):
                row[_col] = to_ddmmyyyy_hhmmss(pd.Series([row[_col]])).iloc[0]

        row["hour"] = to_hour_hh(pd.Series([r_series.get("Assigned Time","")])).iloc[0]
        return row

    # Find responder identifier column (various naming conventions)
    resp_identifier_col = pick_first_column(resps, [
        "Responders ID","Responder ID","ResponderId","responderId","Responder Guid","responderGuid",
    ])

    def _responder_identity(row_dict, raw_series):
        """
        Determine a unique identity key for a responder.

        Uses a priority hierarchy to identify the same responder:
        1. Email (most reliable)
        2. Phone number (digits only, ignoring formatting)
        3. Responder ID/GUID (if available in data)
        4. Name + Registration Body + Verifying Org (less reliable, but sometimes needed)
        5. Row index (fallback if nothing else available)

        Returns:
            Tuple representing the responder's identity
        """
        # Priority 1: Email
        eml = str(row_dict.get("eml", "")).strip().lower()
        if eml:
            return ("eml", eml)

        # Priority 2: Phone (digits only to handle different formatting)
        phone_raw = str(row_dict.get("phone", "")).strip()
        phone_digits = re.sub(r"\D+", "", phone_raw)
        if phone_digits:
            return ("phone", phone_digits)

        # Priority 3: Responder ID/GUID
        if resp_identifier_col:
            identifier = str(raw_series.get(resp_identifier_col, "")).strip().lower()
            if identifier:
                return ("id", identifier)

        # Priority 4: Name + org (less reliable but better than nothing)
        first = str(row_dict.get("name1", "")).strip().lower()
        last = str(row_dict.get("name2", "")).strip().lower()
        if first or last:
            reg_body = str(row_dict.get("reg", "")).strip().lower()
            verify = str(row_dict.get("verify", "")).strip().lower()
            return ("name", first, last, reg_body, verify)

        # Fallback: Use row index (each row is unique)
        idx = str(raw_series.get("_source_row_idx", ""))
        return ("row", idx)

    def _responder_accepts(row_dict):
        """
        Check if a responder accepted the alert.

        Returns True if the responder accepted the alert, including cases where
        they accepted but later dropped the call. A responder who initially accepted
        showed intent to respond, even if they ultimately couldn't complete it.
        """
        val = str(row_dict.get("gsresp_1", "")).strip().lower()
        return val in ("accepted", "acceptedbutdroppedlater")

    def _score_clinical_data(row_dict):
        """
        Score a responder instance to find which one has the best clinical data.

        WHAT THIS DOES:
        When a responder is alerted multiple times for the same job, they might submit
        feedback for multiple alerts. We want to use the feedback that has the most
        valuable information. This function gives each instance a "score" and we pick
        the highest scoring one.

        HOW SCORING WORKS:
        - adinfo (additional info) is HEAVILY WEIGHTED because it's free-text where
          responders write detailed narratives about what happened
        - Other clinical fields (checkboxes, dropdowns) each add 1 point if filled
        - Higher score = better clinical data

        SCORING BREAKDOWN:
        - Empty adinfo: 0 points
        - Short adinfo (1-50 chars): 10-15 points
        - Medium adinfo (100 chars): 20 points
        - Long adinfo (500+ chars): 60 points (maxed out)
        - Each other clinical field with data: +1 point

        **CHANGE THIS**: Adjust the adinfo_bonus formula if you want to change
        how heavily adinfo text is prioritized over checkbox fields
        """
        score = 0

        # List of all clinical fields we check (except adinfo which gets special scoring)
        # **CHANGE THIS**: Update this list if you add/remove clinical fields
        clinical_fields = [
            "falsealm", "ptgen", "natemerg", "priorcare", "airway", "breathing",
            "circ", "disability", "resprate", "pulse", "jawth", "chinlft",
            "naso", "oro", "intubate", "position", "defibn", "aedid", "aedref",
            "nshocks", "cprprov", "cprdurtn", "othint", "outcome", "injinc", "welreq"
        ]

        # HEAVY WEIGHT: Score the adinfo field (free-text narrative field)
        # This gets 10-60 points depending on how much text the responder wrote
        adinfo = str(row_dict.get("adinfo", "")).strip()
        if adinfo and adinfo.lower() not in ("", "false", "n/a", "na", "none"):
            # Give 10 base points plus bonus for longer text (1 point per 10 characters)
            # Cap the bonus at 50 points so adinfo can contribute 10-60 points total
            # **CHANGE THIS**: Modify the formula to adjust adinfo priority
            adinfo_bonus = min(50, len(adinfo) // 10)
            score += 10 + adinfo_bonus

        # LIGHT WEIGHT: Count other clinical fields that have meaningful data
        # Each field with real data adds just 1 point
        for field in clinical_fields:
            value = str(row_dict.get(field, "")).strip().lower()
            # Only count it if it has real data (not empty, not "false", not "n/a", etc.)
            if value and value not in ("", "false", "n/a", "na", "none", "0"):
                score += 1

        return score

    # Build a lookup for chunk ranges per record_id (for filtering responders in split rows)
    chunk_ranges = {}
    for _, row in base.iterrows():
        rec_id = row["record_id"]
        chunk_ranges[rec_id] = {
            "start": row.get("_chunk_start", 1),
            "end": row.get("_chunk_end", 999)
        }

    # ============================================================
    # RESPONDER DUPLICATE COLLAPSING
    # ============================================================
    # For each alert (record_id), group responders by identity and collapse duplicates
    #
    # Example scenario:
    #   Alert #1234 triggered 3 times, same responder alerted each time
    #   → Create ONE responder row with:
    #     - assign_1 = first alert's assignment time
    #     - assign_2 = second alert's assignment time
    #     - assign_3 = third alert's assignment time
    #     - how_many_alerts = "3"
    #     - accept_yesno = "1" (if they accepted ANY of the alerts, including "Accepted But Dropped Later")
    #
    # For SPLIT ROWS (alertref_2, alertref_3, etc. when >9 duplicates):
    #   - Only include responders from position 1 (first alert) + positions in this chunk
    #   - This gives baseline data while avoiding duplicate timeline entries

    for rec_id in base["record_id"]:
        rsp_list = record_responder_entries.get(rec_id, [])
        if not rsp_list:
            continue

        # For split rows (chunk_start > 1), filter responders to:
        # - Position 1 (first alert, for baseline data)
        # - Positions within this chunk's range
        chunk_info = chunk_ranges.get(rec_id, {"start": 1, "end": 999})
        chunk_start = chunk_info["start"]
        chunk_end = chunk_info["end"]

        if chunk_start > 1:
            # This is a split row (e.g., alertref_2), filter responders
            filtered_rsp_list = []
            for rsp in rsp_list:
                pos = rsp.get("_alert_position", 1)
                # Keep if position is 1 OR within this chunk's range
                if pos == 1 or (chunk_start <= pos <= chunk_end):
                    filtered_rsp_list.append(rsp)
            rsp_list = filtered_rsp_list

        # Sort responders by acceptance time, then assignment time (prioritize acceptances)
        try:
            rsp_list = sorted(rsp_list, key=_responder_sort_key)
        except (TypeError, KeyError, AttributeError):  # Sort key errors
            pass

        # Group by responder identity (same person may appear multiple times)
        identity_map = {}
        identity_order = []  # Preserve first-seen order
        for r in rsp_list:
            prepared = _build_responder_row(r, rec_id)
            # Preserve the alert position for later filtering
            prepared["_alert_position"] = r.get("_alert_position", 1)
            ident = _responder_identity(prepared, r)
            if ident not in identity_map:
                identity_map[ident] = []
                identity_order.append(ident)
            identity_map[ident].append(prepared)

        # Build one repeating row per unique responder
        instance_counter = 1
        for ident in identity_order:
            rows = identity_map.get(ident, [])
            if not rows:
                continue

            # REDCap limit: only accept up to _9 suffixes (assign_1 through assign_9)
            # If responder was alerted >9 times, truncate to first 9 occurrences
            MAX_RESPONDER_OCCURRENCES = 9
            count = len(rows)

            if count > MAX_RESPONDER_OCCURRENCES:
                # For split rows (chunk_start > 1), ensure position 1 (baseline) is always included
                if chunk_start > 1:
                    # Find if position 1 (baseline) is in the first 9 rows
                    first_9 = rows[:MAX_RESPONDER_OCCURRENCES]
                    has_pos_1 = any(row.get("_alert_position") == 1 for row in first_9)

                    if not has_pos_1:
                        # Position 1 is not in the first 9, find it and swap with the 9th position
                        pos1_row = None
                        pos1_idx = None
                        for idx, row in enumerate(rows):
                            if row.get("_alert_position") == 1:
                                pos1_row = row
                                pos1_idx = idx
                                break

                        if pos1_row is not None:
                            # Replace the 9th position with position 1 to ensure baseline is included
                            first_9[MAX_RESPONDER_OCCURRENCES - 1] = pos1_row

                    rows = first_9
                else:
                    # For Row 1, just truncate normally
                    rows = rows[:MAX_RESPONDER_OCCURRENCES]
                count = MAX_RESPONDER_OCCURRENCES

            # Use first occurrence as primary row (after any truncation)
            # This has all the timeline data (assign_1, accept_1, etc.) from the first alert
            base_row = rows[0]

            # ============================================================
            # SELECT BEST CLINICAL DATA FROM ALL INSTANCES
            # ============================================================
            # When a responder was alerted multiple times, they may have submitted feedback
            # for multiple alerts. We want to use whichever feedback has the most valuable
            # clinical information (prioritizing free-text adinfo content).
            #
            # This scores each instance and picks the highest scoring one.
            # The scoring heavily favors instances with detailed adinfo (additional info) text.
            # **CHANGE THIS**: Modify _score_clinical_data() function to change scoring logic
            best_clinical_row = max(rows, key=_score_clinical_data, default=rows[0])

            # List of all clinical fields we'll copy from the best instance
            # **CHANGE THIS**: Update this list if you add/remove clinical fields
            clinical_fields = [
                "adinfo", "falsealm", "ptgen", "natemerg", "priorcare", "airway", "breathing",
                "circ", "disability", "resprate", "pulse", "jawth", "chinlft",
                "naso", "oro", "intubate", "position", "defibn", "aedid", "aedref",
                "nshocks", "cprprov", "cprdurtn", "othint", "outcome", "injinc", "welreq"
            ]

            # Copy clinical data from the best instance to the base row
            # Also convert any "FALSE" values to blank (empty string)
            for field in clinical_fields:
                value = str(best_clinical_row.get(field, "")).strip()
                # If the value is "FALSE" (case-insensitive), leave the field blank
                # **CHANGE THIS**: Modify the condition if you want different FALSE handling
                if value.lower() == "false":
                    base_row[field] = ""
                else:
                    base_row[field] = value

            # Set duplicate tracking fields
            base_row[RESP_DUPLICATE_TOTAL_COLUMN] = str(count)  # how_many_alerts
            base_row[RESP_DUPLICATE_ACCEPT_COLUMN] = "1" if any(_responder_accepts(rw) for rw in rows) else "0"

            # For 2nd, 3rd, etc. alerts to this responder, copy timeline data to suffixed columns
            # Only goes up to position 9 (assign_9) due to REDCap limit
            for dup_idx, dup_row in enumerate(rows[1:], start=2):
                for field in RESPONDER_DUPLICATE_FIELDS:
                    source_col = f"{field}_1"  # Get the _1 field from the duplicate row
                    col_name = f"{field}_{dup_idx}"  # Store in _2, _3, etc.
                    base_row[col_name] = dup_row.get(source_col, "")
                    responder_dynamic_pairs.add((field, dup_idx))

            base_row["redcap_repeat_instance"] = str(instance_counter)
            repeat_rows.append(base_row)
            instance_counter += 1

    if responder_dynamic_pairs:
        field_order = {name: idx for idx, name in enumerate(RESPONDER_DUPLICATE_FIELDS)}
        resp_dynamic_map = {}
        for field, dup_idx in sorted(responder_dynamic_pairs, key=lambda item: (field_order.get(item[0], 999), item[1])):
            base_col = f"{field}_1"
            resp_dynamic_map.setdefault(base_col, []).append(f"{field}_{dup_idx}")

        template_cols = list(OUTPUT_COLUMNS)
        new_cols = []
        for cols in resp_dynamic_map.values():
            for col in cols:
                if col not in template_cols and col not in new_cols:
                    new_cols.append(col)
        if new_cols:
            # Insert new responder duplicate columns right after the pre-allocated ones (after gsresp_8, etc.)
            # Find the insertion point: after the last pre-allocated responder duplicate field
            insert_after = None
            for field in RESPONDER_DUPLICATE_FIELDS:
                last_preallocated = f"{field}_8"
                if last_preallocated in template_cols:
                    idx = template_cols.index(last_preallocated)
                    if insert_after is None or idx > insert_after:
                        insert_after = idx

            if insert_after is not None:
                # Insert new columns right after the last pre-allocated responder duplicate field
                OUTPUT_COLUMNS[:] = template_cols[:insert_after+1] + new_cols + template_cols[insert_after+1:]
            else:
                # Fallback: append to end if we can't find the insertion point
                OUTPUT_COLUMNS[:] = template_cols + new_cols

            additions = pd.DataFrame({c: [""] * len(base) for c in new_cols})
            base = pd.concat([base, additions], axis=1)
            for row in repeat_rows:
                for col_name in new_cols:
                    row.setdefault(col_name, "")

    # Combine while preserving the alert row order; responders follow their alert
    # Guard against any accidental duplicate column labels before concatenation
    OUTPUT_COLUMNS[:] = list(dict.fromkeys(OUTPUT_COLUMNS))
    base = base.loc[:, ~base.columns.duplicated()]
    helper_cols = [c for c in base.columns if c.startswith("_")]
    desired_cols = helper_cols + ["record_id"] + [c for c in OUTPUT_COLUMNS if c != "record_id"]
    out = base.reindex(columns=desired_cols)
    repeats_df = (
        pd.DataFrame(repeat_rows).reindex(columns=desired_cols, fill_value="")
        if repeat_rows else pd.DataFrame(columns=desired_cols)
    )
    out = out.loc[:, ~out.columns.duplicated()]
    repeats_df = repeats_df.loc[:, ~repeats_df.columns.duplicated()]

    # Carry the alert row order index to repeats via record_id mapping
    row_idx_map = dict(zip(base["record_id"], base["_row_idx"]))
    if not repeats_df.empty:
        repeats_df["_row_idx"] = repeats_df["record_id"].astype(int).map(row_idx_map)

    out["_row_idx"] = out["_row_idx"]  # already set on base
    out = pd.concat([out, repeats_df], ignore_index=True)

    # Order: alert row first, then its repeats by instance
    out = out.assign(
        _is_repeat=(out["redcap_repeat_instrument"] == "responders").astype(int),
        _instance_num=pd.to_numeric(out["redcap_repeat_instance"], errors="coerce").fillna(0).astype(int),
    )
    out = out.sort_values(by=["_row_idx", "_is_repeat", "_instance_num"], kind="stable")

    # Clean up helpers
    out = out.drop(columns=["_row_idx", "_is_repeat", "_instance_num", "_gk", "_alertref_root", "__aid", "_chunk_start", "_chunk_end", "_alert_position"], errors="ignore")

    # Ensure final column order
    out = out[["record_id"] + [c for c in OUTPUT_COLUMNS if c != "record_id"]]
    # Final pass: clean gsresp across the whole output, in case anything slipped through
    gsresp_cols = [c for c in out.columns if c.startswith("gsresp")]
    for col in gsresp_cols:
        out[col] = (
            out[col]
            .astype(str)
            .str.replace("\u00a0", " ", regex=False)   # NBSP -> space
            .str.replace(r"\s+", "", regex=True)       # remove all whitespace
        )
    
    # --- Welfare requests: find responders with welreq true-ish ---
    flagged = pd.DataFrame()
    if not repeats_df.empty and "welreq" in repeats_df.columns:
        # Accept booleans and common string variants
        wel_raw = repeats_df["welreq"]
        wel_norm = wel_raw.map(lambda v: str(v).strip().lower())
        is_true = wel_norm.isin({"true", "yes", "1"})
        flagged = repeats_df.loc[is_true].copy()

        # Log a concise summary
        true_count = int(is_true.sum())
        safe_print(f"[WELREQ] True-like values: {true_count} / {len(repeats_df)}")
        if true_count:
            # Show the first few to verify mapping worked
            preview_cols = ["record_id", "redcap_repeat_instance", "name1", "name2", "phone", "eml", "category", "assign_1", "accept_1", "gsresp_1", "welreq"]
            _cols = [c for c in preview_cols if c in flagged.columns]
            safe_print("[WELREQ] Sample (up to 5):")
            safe_print(flagged[_cols].head(5).to_string(index=False))

        # Emit follow-up CSV next to main output (always refresh for this run)
        try:
            follow_cols = [
                "record_id", "redcap_repeat_instance", "name1", "name2", "phone", "eml",
                "category", "assign_1", "accept_1", "gsresp_1", "welreq"
            ]
            follow_cols = [c for c in follow_cols if c in repeats_df.columns]
            follow_path = os.path.join(os.path.dirname(os.path.abspath(args.out)), "welreq_followup.csv")

            if true_count and follow_cols:
                follow_df = flagged[follow_cols]
            else:
                # Write headers only to indicate no welfare requests in this run
                follow_df = pd.DataFrame(columns=follow_cols)

            follow_df.to_csv(
                follow_path,
                index=False,
                encoding="utf-8-sig",
                quoting=csv.QUOTE_ALL,
                lineterminator="\r\n",
            )
            safe_print(f"[WELREQ] Wrote welfare follow-up list ({len(follow_df)} rows): {follow_path}")
        except Exception as e:
            safe_print(f"[WELREQ] Could not write follow-up CSV: {e}")

 

   
    # Uppercase welreq booleans on responder rows only
    if "welreq" in out.columns:
        mask = out["redcap_repeat_instrument"].eq("responders")
        out.loc[mask, "welreq"] = uppercase_bool_strings(out.loc[mask, "welreq"])
    
    # Blank out specific responder fields when they are 'FALSE' (case-insensitive)
    # Keep any other non-FALSE values as-is
    _false_blank_cols_out = ["falsealm", "jawth", "chinlft", "naso", "oro", "intubate"]
    blank_false_like_strings(out, _false_blank_cols_out)
    # === Master Responder List (keeps interstate; no 5-digit filter) ===
    string_id_map = None
    if {"Integer ID", "String ID"}.issubset(set(alerts.columns)):
        sid = alerts["String ID"].astype(str).str.strip()
        iid = alerts["Integer ID"].astype(str).str.strip()
        string_id_map = dict(zip(iid, sid))

    master_df = build_master_responder_list(resps_all, alerts_source=alerts, string_id_map=string_id_map)
    # Apply the same FALSE->blank rule to master list long-form columns
    _false_blank_cols_master = [
        "falseAlarm", "jawThurst", "chinLift", "nasopharyngeal", "oropharngeal", "intubation"
    ]
    blank_false_like_strings(master_df, _false_blank_cols_master)
    master_path = os.path.splitext(args.out)[0] + "_master_responder_list.csv"
    master_df.to_csv(master_path, index=False, encoding="utf-8-sig", lineterminator="\r\n")
    safe_print(f"Master responder rows: {len(master_df)}")
    safe_print(f"Master responder CSV:  {master_path}")
    # === expose to GUI ===
    global LAST_MASTER_PATH
    LAST_MASTER_PATH = master_path

    # If event name provided, set redcap_event_name on all rows
    try:
        if args.redcap_event_name:
            out = out.copy()
            out['redcap_event_name'] = args.redcap_event_name
    except (AttributeError, KeyError):
        pass
    out = apply_redcap_default_fields(out)

    # Guard against stray blank rows (e.g. legacy CSV edits) that lack record_id
    try:
        rid_series = out["record_id"].astype(str).str.strip()
        valid_mask = rid_series != ""
        dropped = int((~valid_mask).sum())
        if dropped:
            safe_print(f"[WARN] Dropped {dropped} rows with blank record_id before writing output.")
        out = out.loc[valid_mask].copy()
    except (KeyError, AttributeError, TypeError):
        pass

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    out.to_csv(
        args.out,
        index=False,
        encoding="utf-8-sig",
        quoting=csv.QUOTE_MINIMAL,
        lineterminator="\r\n",
    )



    # Summary
    safe_print("=== REDCap build (Integer ID linkage + alertref de-dupe + phone normalisation) ===")
    safe_print(f"Alerts kept:     {len(base)}")
    safe_print(f"Responders kept: {len(out) - len(base)}")
    safe_print(f"Distinct IDs:    {len(set(out['record_id']))}")
    safe_print(f"Total rows:      {len(out)}")
    safe_print(f"Output:          {args.out}")
    safe_print(
        "To upload this CSV later, run: python GS2RCAPI.py --upload-input "
        f"\"{args.out}\" --redcap-token <TOKEN> [--redcap-url <URL>]"
    )


if __name__ == "__main__":
    pd.set_option("display.max_columns", 200)
    pd.set_option("display.width", 200)
    safe_print("🚀 Starting GoodSAM → REDCap builder")
    main()
    safe_print("✅ Done.")
