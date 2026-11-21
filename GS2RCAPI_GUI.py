#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
GS2RCAPI_GUI.py
-----------------------------------------
Tkinter front-end for GS2RCAPI.py
- Left: inputs & actions
- Right: live console
- API mode uses simple date pickers (YYYY-MM-DD) -> 00:00:00 to 23:59:59
- CSV mode ignores dates
- Keyring for credentials
- Copy Master Responder List to clipboard as TSV (clean paste to Excel)
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import subprocess
import keyring
import os
import csv
import sys
import traceback
import io
import contextlib
import threading
import queue
import shutil
from datetime import datetime, timedelta
try:
    import GS2RCAPI as BUILDER
except ImportError:
    import BUILDER as BUILDER

# Optional calendar support
try:
    from tkcalendar import DateEntry  # conda install -c conda-forge tkcalendar OR pip install tkcalendar
except ImportError:  # module not installed or unavailable
    DateEntry = None

# Application name for keyring storage
# **CHANGE THIS** if you need a different keyring identifier
APP_NAME = "GoodSAM_ETL"

# Default REDCap batch size for imports
# **CHANGE THIS** if you need to adjust the batch size for your REDCap server
REDCAP_BATCH_DEFAULT = 500

# Default REDCap API URL
# **CHANGE THIS** to match your REDCap server URL
DEFAULT_REDCAP_URL = "https://nswa-redcap.ambulance.nsw.gov.au/redcap/api/"

SCRIPT_PATH = os.path.join(os.path.dirname(__file__), "GS2RCAPI.py")


def _resolve_output_dir() -> str:
    """Pick a writable folder for output CSVs.

    In a PyInstaller --onefile exe, __file__ points into a temporary _MEI
    folder that is deleted when the app closes, so outputs must go next to
    the .exe instead (or Documents if that folder is read-only, e.g. a
    network share or Program Files).
    """
    if getattr(sys, "frozen", False):
        candidates = [os.path.dirname(os.path.abspath(sys.executable))]
    else:
        candidates = [os.path.dirname(os.path.abspath(SCRIPT_PATH))]
    candidates.append(os.path.join(os.path.expanduser("~"), "Documents", "GoodSAM_ETL"))
    for d in candidates:
        try:
            os.makedirs(d, exist_ok=True)
            probe = os.path.join(d, ".write_test")
            with open(probe, "w") as fh:
                fh.write("ok")
            os.remove(probe)
            return d
        except OSError:
            continue
    return candidates[-1]


DEFAULT_OUTPUT_DIR = _resolve_output_dir()
LAST_OUTPUT_PATH = ""

# ---------------------------------------------------------------------
# Clipboard TSV Copy (no extra blank lines)
# ---------------------------------------------------------------------
def copy_master_list_to_clipboard():
    """Copy the master responder list as TSV (tab-separated) for clean Excel paste."""
    path = getattr(BUILDER, "LAST_MASTER_PATH", None)

    # Derive from current Output file if needed
    if (not path or not os.path.exists(path)) and ent_out.get().strip():
        base, _ = os.path.splitext(ent_out.get().strip())
        candidate = base + "_master_responder_list.csv"
        if os.path.exists(candidate):
            path = candidate

    if not path or not os.path.exists(path):
        messagebox.showwarning("Not available", "No master responder list found.\nRun a build and try again.")
        return

    try:
        import csv
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            reader = list(csv.reader(f))
        if not reader:
            messagebox.showwarning("Empty", "Master responder list is empty.")
            return
        data_rows = reader[1:] if len(reader) > 1 else []
        rows = []
        for row in data_rows:
            safe = []
            for c in row:
                c = "" if c is None else str(c)
                c = c.replace("\t", "    ").replace("\r", " ").replace("\n", " ")
                safe.append(c)
            rows.append("\t".join(safe))
        if not rows:
            messagebox.showinfo("Copied", "No data rows to copy (header skipped).")
            return
        # Use '\n' only; Tk on Windows will normalize to CRLF
        tsv_text = "\n".join(rows)

        r = tk.Tk(); r.withdraw()
        r.clipboard_clear()
        r.clipboard_append(tsv_text)
        r.update(); r.destroy()

        messagebox.showinfo(
            "Copied",
            f"Copied {len(rows)} row(s) (header skipped) from:\n{path}\n\nPaste into Excel with Ctrl+V.",
        )
    except Exception as e:
        messagebox.showerror("Copy failed", f"Failed to copy to clipboard:\n{str(e)}")


# ---------------------------------------------------------------------
# Welfare Requests (welreq=True) helpers
# ---------------------------------------------------------------------
WELREQ_PATH = None  # resolved after a run or from current Output file


def _resolve_welreq_path():
    """Find welreq_followup.csv next to the current output file."""
    global WELREQ_PATH
    # Prefer previously computed path
    if WELREQ_PATH and os.path.exists(WELREQ_PATH):
        return WELREQ_PATH
    # Derive from Output file entry
    out_val = ent_out.get().strip() if 'ent_out' in globals() else ""
    if out_val:
        base, _ = os.path.splitext(out_val)
        candidate = os.path.join(os.path.dirname(base), "welreq_followup.csv")
        if os.path.exists(candidate):
            WELREQ_PATH = candidate
            return WELREQ_PATH
    if LAST_OUTPUT_PATH:
        base, _ = os.path.splitext(LAST_OUTPUT_PATH)
        candidate = os.path.join(os.path.dirname(base), "welreq_followup.csv")
        if os.path.exists(candidate):
            WELREQ_PATH = candidate
            return WELREQ_PATH
    return None


def copy_welreq_to_clipboard():
    """Copy welreq follow-up list as TSV for Excel."""
    path = _resolve_welreq_path()
    if not path:
        messagebox.showwarning("Not available", "No welreq_followup.csv found.\nRun a build and try again.")
        return

    try:
        # Format: "Record ID: <record_id> <name1> <name2> has requested a welfare check <phone> <eml>"
        lines = []
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rec_id = (row.get("record_id") or "").strip()
                name1 = (row.get("name1") or "").strip()
                name2 = (row.get("name2") or "").strip()
                phone = (row.get("phone") or "").strip()
                eml = (row.get("eml") or "").strip()

                def _clean(x: str) -> str:
                    return x.replace("\t", " ").replace("\r", " ").replace("\n", " ")

                rec_id, name1, name2, phone, eml = map(_clean, [rec_id, name1, name2, phone, eml])
                line = f"Record ID: {rec_id} {name1} {name2} has requested a welfare check {phone} {eml}"
                lines.append(line.strip())

        if not lines:
            messagebox.showwarning("No rows", "No welfare request rows to copy.")
            return

        text = "\n".join(lines)

        r = tk.Tk(); r.withdraw()
        r.clipboard_clear()
        r.clipboard_append(text)
        r.update(); r.destroy()

        messagebox.showinfo("Copied", f"Copied {len(lines)} welfare request(s) from:\n{path}")
    except Exception as e:
        messagebox.showerror("Copy failed", f"Failed to copy to clipboard:\n{str(e)}")


def clear_welreq_view():
    """Clear the Treeview and reset headers."""
    try:
        for i in wel_tree.get_children():
            wel_tree.delete(i)
        # keep columns to avoid flicker; they will be updated on load
    except Exception:
        pass
    if 'wel_count' in globals():
        wel_count.configure(text="No welfare requests loaded")


def load_welreq_into_view(path=None):
    """Load welreq_followup.csv into the Treeview and highlight rows."""
    global WELREQ_PATH
    clear_welreq_view()

    p = path or _resolve_welreq_path()
    if not p or not os.path.exists(p):
        wel_count.configure(text="No welfare follow-up file found")
        return

    WELREQ_PATH = p
    try:
        with open(p, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        if not rows:
            wel_count.configure(text="Welfare follow-up is empty")
            return
        headers = rows[0]
        data_rows = rows[1:]

        # Configure columns dynamically
        wel_tree["columns"] = headers
        wel_tree["show"] = "headings"
        for col in headers:
            wel_tree.heading(col, text=col)
            wel_tree.column(col, width=120, anchor="w")

        # Insert rows with a highlight tag
        for r in data_rows:
            # Pad/trim to headers length
            vals = (r + [""] * len(headers))[:len(headers)]
            wel_tree.insert("", tk.END, values=vals, tags=("welrow",))

        # Soft amber background to draw attention
        try:
            wel_tree.tag_configure("welrow", background="#fff4cc")
        except tk.TclError:  # Theme doesn't support custom colors
            pass

        wel_count.configure(text=f"Welfare requests: {len(data_rows)} shown")
    except Exception as e:
        wel_count.configure(text="Failed to load welfare list")
        messagebox.showerror("Load failed", f"Failed to load data:\n{str(e)}")


# ---------------------------------------------------------------------
# Basic-mode welfare helpers
# ---------------------------------------------------------------------
basic_wel_tree = None
basic_wel_count = None
basic_text_status = None
basic_progress_bar = None
basic_ent_user = None
basic_ent_pass = None
basic_ent_redcap_url = None
basic_ent_redcap_token = None
basic_var_debug_mode = None
basic_var_save_api_json = None
basic_btn_run = None
basic_lbl_run_info = None


def basic_clear_welreq_view():
    if basic_wel_tree is not None:
        for i in basic_wel_tree.get_children():
            basic_wel_tree.delete(i)
    if basic_wel_count is not None:
        basic_wel_count.configure(text="No welfare requests loaded")


def basic_load_welreq_into_view(path=None):
    basic_clear_welreq_view()
    p = path or _resolve_welreq_path()
    if not p or not os.path.exists(p):
        if basic_wel_count is not None:
            basic_wel_count.configure(text="No welfare follow-up file found")
        return
    try:
        with open(p, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        if not rows:
            if basic_wel_count is not None:
                basic_wel_count.configure(text="Welfare follow-up is empty")
            return
        headers = rows[0]
        data_rows = rows[1:]
        basic_wel_tree["columns"] = headers
        basic_wel_tree["show"] = "headings"
        for col in headers:
            basic_wel_tree.heading(col, text=col)
            basic_wel_tree.column(col, width=120, anchor="w")
        for r in data_rows:
            vals = (r + [""] * len(headers))[:len(headers)]
            basic_wel_tree.insert("", tk.END, values=vals, tags=("basicwelrow",))
        try:
            basic_wel_tree.tag_configure("basicwelrow", background="#fff4cc")
        except tk.TclError:  # Theme doesn't support custom colors
            pass
        if basic_wel_count is not None:
            basic_wel_count.configure(text=f"Welfare requests: {len(data_rows)} shown")
    except Exception as e:
        if basic_wel_count is not None:
            basic_wel_count.configure(text="Failed to load welfare list")
        messagebox.showerror("Load failed", f"Failed to load data:\n{str(e)}")


# ---------------------------------------------------------------------
# Input Validation Helpers
# ---------------------------------------------------------------------
def validate_record_id(value):
    """Validate that record ID is a positive integer."""
    if not value or not value.strip():
        return False, "Record ID is required"
    try:
        rid = int(value.strip())
        if rid <= 0:
            return False, "Record ID must be a positive number"
        return True, ""
    except ValueError:
        return False, "Record ID must be a number"

def validate_file_exists(path):
    """Validate that a file path exists."""
    if not path or not path.strip():
        return False, "File path is required"
    if not os.path.exists(path.strip()):
        return False, f"File not found: {path}"
    if not os.path.isfile(path.strip()):
        return False, f"Path is not a file: {path}"
    return True, ""

def validate_date_range(start_date, end_date):
    """Validate that start date is before end date."""
    try:
        if start_date > end_date:
            return False, "Start date must be before end date"
        return True, ""
    except Exception as e:
        return False, f"Invalid date range: {str(e)}"

def validate_url(url):
    """Validate that URL looks reasonable."""
    if not url or not url.strip():
        return False, "URL is required"
    url = url.strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        return False, "URL must start with http:// or https://"
    return True, ""

# ---------------------------------------------------------------------
# Keyring helpers
# ---------------------------------------------------------------------
def save_login(username, password):
    if not username or not password:
        messagebox.showwarning("Missing", "Username and password required.")
        return
    keyring.set_password(APP_NAME, "username", username)
    keyring.set_password(APP_NAME, "password", password)
    messagebox.showinfo("Saved", "Login saved securely.")


def load_login():
    return keyring.get_password(APP_NAME, "username") or "", keyring.get_password(APP_NAME, "password") or ""


# REDCap keyring helpers
REDCAP_APP_NAME = "GoodSAM_ETL_REDCAP"

def save_redcap(url, token):
    if not token:
        messagebox.showwarning("Missing", "REDCap API token required.")
        return
    if url:
        keyring.set_password(REDCAP_APP_NAME, "url", url)
    keyring.set_password(REDCAP_APP_NAME, "token", token)
    messagebox.showinfo("Saved", "REDCap settings saved securely.")


def load_redcap():
    url = keyring.get_password(REDCAP_APP_NAME, "url") or ""
    token = keyring.get_password(REDCAP_APP_NAME, "token") or ""
    return url, token

# ---------------------------------------------------------------------
# File/Folder selectors
# ---------------------------------------------------------------------
def browse_file(entry, title="Select File"):
    path = filedialog.askopenfilename(title=title, filetypes=[("CSV files", "*.csv"), ("All files", "*.*")])
    if path:
        entry.delete(0, tk.END)
        entry.insert(0, path)


def browse_output(entry):
    path = filedialog.asksaveasfilename(
        title="Save Output CSV",
        defaultextension=".csv",
        filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
    )
    if path:
        entry.delete(0, tk.END)
        entry.insert(0, path)


def _basic_run_cli(argv, mode_label, after_success=None, notify=True):
    """Run CLI command in a background thread with live progress bar (basic mode)."""
    if basic_text_status is not None:
        basic_text_status.insert(tk.END, f"=== {mode_label} ===\n")
        basic_text_status.insert(tk.END, f"Args: {' '.join(argv[1:])}\n\n")
        basic_text_status.see(tk.END)

    # Create a queue for thread communication
    msg_queue = queue.Queue()

    def worker():
        """Background worker thread."""
        try:
            if getattr(sys, 'frozen', False):
                buf_out = io.StringIO()
                buf_err = io.StringIO()
                retcode = 0
                try:
                    old_argv = sys.argv
                    sys.argv = argv
                    with contextlib.redirect_stdout(buf_out), contextlib.redirect_stderr(buf_err):
                        BUILDER.main()
                except SystemExit as se:
                    try:
                        retcode = int(se.code or 0)
                    except Exception:
                        retcode = 1
                except Exception as e:
                    retcode = 1
                    buf_err.write(traceback.format_exc())
                finally:
                    sys.argv = old_argv

                out_text = buf_out.getvalue()
                err_text = buf_err.getvalue()
                # Send output line by line for progress tracking
                for line in (out_text or "").split('\n'):
                    if line.strip():
                        msg_queue.put(("output", line))
                if err_text:
                    msg_queue.put(("error", err_text))
                msg_queue.put(("done", retcode))
            else:
                cmd = [sys.executable, SCRIPT_PATH] + argv[1:]
                msg_queue.put(("output", f"Running: {' '.join(cmd)}\n"))

                # Stream output line by line
                process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

                # Read stdout
                for line in process.stdout:
                    msg_queue.put(("output", line.rstrip()))

                # Wait for completion
                process.wait()

                # Read any stderr
                stderr_text = process.stderr.read()
                if stderr_text:
                    msg_queue.put(("error", stderr_text))

                msg_queue.put(("done", process.returncode))
        except Exception as e:
            msg_queue.put(("exception", str(e)))

    # Progress tracking based on pipeline stages
    progress_stages = {
        "Starting GoodSAM": 10,
        "Alerts received": 25,
        "Responders received": 35,
        "Dropped": 45,
        "Master responder": 50,
        "REDCap build": 60,
        "Alerts kept": 70,
        "Responders kept": 75,
        "Distinct IDs": 80,
        "Total rows": 85,
        "Output:": 95,
        "upload": 90,
    }

    def check_queue():
        """Poll the queue and update GUI with progress tracking."""
        try:
            while True:
                msg_type, data = msg_queue.get_nowait()

                if msg_type == "output":
                    if basic_text_status is not None:
                        basic_text_status.insert(tk.END, data + "\n")
                        basic_text_status.see(tk.END)

                    # Update progress based on output
                    if basic_progress_bar is not None:
                        for keyword, progress_value in progress_stages.items():
                            if keyword.lower() in data.lower():
                                basic_progress_bar["value"] = progress_value
                                break

                elif msg_type == "error":
                    if basic_text_status is not None:
                        basic_text_status.insert(tk.END, "ERRORS:\n" + data + "\n")
                        basic_text_status.see(tk.END)
                elif msg_type == "done":
                    if basic_progress_bar is not None:
                        basic_progress_bar["value"] = 100  # Complete
                    if data == 0:
                        if after_success:
                            after_success()
                        if notify:
                            messagebox.showinfo("Done", f"{mode_label} completed. See console output on the right.")
                    else:
                        if basic_text_status is not None:
                            basic_text_status.insert(tk.END, f"[GUI] {mode_label} failed.\n")
                        if notify:
                            messagebox.showwarning("Action failed", f"{mode_label} failed. Check console output on the right.")
                    if basic_text_status is not None:
                        basic_text_status.see(tk.END)
                    # Reset progress bar after a delay
                    if basic_progress_bar is not None:
                        root.after(1000, lambda: basic_progress_bar.configure(value=0))
                    return  # Stop polling
                elif msg_type == "exception":
                    if basic_progress_bar is not None:
                        basic_progress_bar["value"] = 0
                    messagebox.showerror("Execution Error", data)
                    return  # Stop polling
        except queue.Empty:
            pass

        # Continue polling
        root.after(100, check_queue)

    # Initialize progress bar
    try:
        if basic_progress_bar is not None:
            basic_progress_bar["value"] = 0
            basic_progress_bar["maximum"] = 100
    except tk.TclError:  # Widget not ready
        pass

    # Start worker thread
    thread = threading.Thread(target=worker, daemon=True)
    thread.start()

    # Start polling queue
    root.after(100, check_queue)


def basic_run_auto_pipeline():
    global LAST_OUTPUT_PATH, WELREQ_PATH
    if basic_ent_user is None:
        messagebox.showerror("Not ready", "Basic tab has not been initialised.")
        return
    username = basic_ent_user.get().strip()
    password = basic_ent_pass.get().strip()
    redcap_url = basic_ent_redcap_url.get().strip()
    redcap_token = basic_ent_redcap_token.get().strip()
    debug_mode = bool(basic_var_debug_mode.get())
    save_api_json = bool(basic_var_save_api_json.get())

    if not username or not password:
        messagebox.showerror("Missing GoodSAM credentials", "Enter GoodSAM username and password.")
        return
    if not redcap_token or not redcap_url:
        messagebox.showerror("Missing REDCap details", "Enter REDCap API URL and token.")
        return

    # Validate REDCap URL format
    valid, error_msg = validate_url(redcap_url)
    if not valid:
        messagebox.showerror("Invalid REDCap URL", error_msg)
        return

    basic_btn_run.config(state=tk.DISABLED)
    root.config(cursor="watch")
    root.update_idletasks()

    try:
        context = BUILDER.get_latest_record_context(redcap_url, redcap_token, verify=True)
        next_id = int(context.get("next_record_id") or 1)
        last_reg = context.get("last_regtime") or ""
        last_dt = _parse_regtime(last_reg)

        today = datetime.now()
        end_dt = today.replace(hour=0, minute=0, second=0, microsecond=0)
        prev_day = end_dt - timedelta(days=1)

        if last_dt:
            start_dt = last_dt + timedelta(seconds=1)
        else:
            start_dt = prev_day

        if start_dt >= end_dt:
            if basic_text_status is not None:
                basic_text_status.insert(
                    tk.END,
                    f"[GUI] No new data window detected (start {start_dt} >= end {end_dt}). Nothing to run.\n",
                )
                basic_text_status.see(tk.END)
            messagebox.showinfo("Nothing to do", "No new GoodSAM data window was detected.")
            return

        filename = prev_day.strftime("%y%m%d") + ".csv"
        out_path = os.path.join(DEFAULT_OUTPUT_DIR, filename)
        start_str = start_dt.strftime("%Y-%m-%d %H:%M:%S")
        end_str = end_dt.strftime("%Y-%m-%d %H:%M:%S")

        if basic_text_status is not None:
            basic_text_status.insert(
                tk.END,
                f"[GUI] Last record_id: {context.get('last_record_id')}, regtime: {last_reg or 'N/A'}\n"
            )
            basic_text_status.insert(
                tk.END,
                f"[GUI] Next record_id: {next_id}; API window {start_str} -> {end_str}\n"
            )
            basic_text_status.insert(tk.END, f"[GUI] Output CSV: {out_path}\n")
            basic_text_status.see(tk.END)

        argv_build = [
            "GS2RCAPI.py",
            "--out", out_path,
            "--start-id", str(next_id),
            "--username", username,
            "--password", password,
            "--start-date", start_str,
            "--end-date", end_str,
        ]
        if not save_api_json:
            argv_build.append("--no-save-api-json")

        def _after_build():
            global LAST_OUTPUT_PATH, WELREQ_PATH
            LAST_OUTPUT_PATH = out_path
            WELREQ_PATH = os.path.join(os.path.dirname(os.path.abspath(out_path)), "welreq_followup.csv")
            if os.path.exists(WELREQ_PATH):
                if basic_text_status is not None:
                    basic_text_status.insert(tk.END, f"[GUI] Welfare follow-up ready: {WELREQ_PATH}\n")
                    basic_text_status.see(tk.END)
                basic_load_welreq_into_view(WELREQ_PATH)
            else:
                basic_clear_welreq_view()
                if basic_text_status is not None:
                    basic_text_status.insert(tk.END, "[GUI] No welfare follow-up generated.\n")

        if not _basic_run_cli(argv_build, "API Build", after_success=_after_build, notify=False):
            return

        if debug_mode:
            basic_lbl_run_info.configure(
                text=f"Last run: {filename} | Window {start_str} \u2192 {end_str} (debug build only)"
            )
            if basic_text_status is not None:
                basic_text_status.insert(tk.END, "[GUI] Debug mode enabled: skipping REDCap upload.\n")
                basic_text_status.see(tk.END)
            messagebox.showinfo("Debug build complete", "CSV built. Upload skipped (debug mode).")
            return

        argv_upload = [
            "GS2RCAPI.py",
            "--upload-input", out_path,
            "--out", out_path,
            "--redcap-batch-size", str(REDCAP_BATCH_DEFAULT),
            "--redcap-url", redcap_url,
            "--redcap-token", redcap_token,
        ]

        if not _basic_run_cli(argv_upload, "REDCap Upload", notify=False):
            return

        basic_lbl_run_info.configure(
            text=f"Last run: {filename} | Window {start_str} \u2192 {end_str}"
        )
        messagebox.showinfo("Success", "Build and upload completed.")
    except Exception as exc:
        messagebox.showerror("Auto run failed", str(exc))
    finally:
        root.config(cursor="")
        basic_btn_run.config(state=tk.NORMAL)

def _run_cli(argv, mode_label, after_success=None):
    """Run CLI command in a background thread with live progress bar."""
    text_status.insert(tk.END, f"=== {mode_label} ===\n")
    text_status.insert(tk.END, f"Args: {' '.join(argv[1:])}\n\n")
    text_status.see(tk.END)

    # Create a queue for thread communication
    msg_queue = queue.Queue()

    def worker():
        """Background worker thread."""
        try:
            if getattr(sys, 'frozen', False):
                buf_out = io.StringIO()
                buf_err = io.StringIO()
                retcode = 0
                try:
                    old_argv = sys.argv
                    sys.argv = argv
                    with contextlib.redirect_stdout(buf_out), contextlib.redirect_stderr(buf_err):
                        BUILDER.main()
                except SystemExit as se:
                    try:
                        retcode = int(se.code or 0)
                    except Exception:
                        retcode = 1
                except Exception as e:
                    retcode = 1
                    buf_err.write(traceback.format_exc())
                finally:
                    sys.argv = old_argv

                out_text = buf_out.getvalue()
                err_text = buf_err.getvalue()
                # Send output line by line for progress tracking
                for line in (out_text or "").split('\n'):
                    if line.strip():
                        msg_queue.put(("output", line))
                if err_text:
                    msg_queue.put(("error", err_text))
                msg_queue.put(("done", retcode))
            else:
                cmd = [sys.executable, SCRIPT_PATH] + argv[1:]
                msg_queue.put(("output", f"Running: {' '.join(cmd)}\n"))

                # Stream output line by line
                process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

                # Read stdout
                for line in process.stdout:
                    msg_queue.put(("output", line.rstrip()))

                # Wait for completion
                process.wait()

                # Read any stderr
                stderr_text = process.stderr.read()
                if stderr_text:
                    msg_queue.put(("error", stderr_text))

                msg_queue.put(("done", process.returncode))
        except Exception as e:
            msg_queue.put(("exception", str(e)))

    # Progress tracking based on pipeline stages
    progress_stages = {
        "Starting GoodSAM": 10,
        "Alerts received": 25,
        "Responders received": 35,
        "Dropped": 45,
        "Master responder": 50,
        "REDCap build": 60,
        "Alerts kept": 70,
        "Responders kept": 75,
        "Distinct IDs": 80,
        "Total rows": 85,
        "Output:": 95,
        "upload": 90,  # For upload operations
    }

    def check_queue():
        """Poll the queue and update GUI with progress tracking."""
        try:
            while True:
                msg_type, data = msg_queue.get_nowait()

                if msg_type == "output":
                    text_status.insert(tk.END, data + "\n")
                    text_status.see(tk.END)

                    # Update progress based on output
                    for keyword, progress_value in progress_stages.items():
                        if keyword.lower() in data.lower():
                            adv_progress_bar["value"] = progress_value
                            break

                elif msg_type == "error":
                    text_status.insert(tk.END, "ERRORS:\n" + data + "\n")
                    text_status.see(tk.END)
                elif msg_type == "done":
                    adv_progress_bar["value"] = 100  # Complete
                    if data == 0:
                        if after_success:
                            after_success()
                        messagebox.showinfo("Done", f"{mode_label} completed. See console output on the right.")
                    else:
                        text_status.insert(tk.END, f"[GUI] {mode_label} failed.\n")
                        messagebox.showwarning("Action failed", f"{mode_label} failed. Check console output on the right.")
                    text_status.see(tk.END)
                    # Reset progress bar after a delay
                    root.after(1000, lambda: adv_progress_bar.configure(value=0))
                    return  # Stop polling
                elif msg_type == "exception":
                    adv_progress_bar["value"] = 0
                    messagebox.showerror("Execution Error", data)
                    return  # Stop polling
        except queue.Empty:
            pass

        # Continue polling
        root.after(100, check_queue)

    # Initialize progress bar
    try:
        adv_progress_bar["value"] = 0
        adv_progress_bar["maximum"] = 100
    except Exception:
        pass

    # Start worker thread
    thread = threading.Thread(target=worker, daemon=True)
    thread.start()

    # Start polling queue
    root.after(100, check_queue)


# ---------------------------------------------------------------------
# Builder runner
# ---------------------------------------------------------------------
def advanced_run_builder():
    username = ent_user.get().strip()
    password = ent_pass.get().strip()
    start_day = start_var.get().strip()
    end_day = end_var.get().strip()
    alerts = ent_alert.get().strip()
    responders = ent_resp.get().strip()
    out_path = ent_out.get().strip()
    start_id = ent_startid.get().strip()
    if not start_id:
        messagebox.showerror("Missing Record ID", "Please enter a starting record ID.\n\nTip: Use 'Get Next ID' button to auto-fill from REDCap.")
        return

    if not out_path:
        messagebox.showerror("Missing output", "Please choose an output file.")
        return

    try:
        sd = datetime.strptime(start_day, "%Y-%m-%d")
        ed = datetime.strptime(end_day, "%Y-%m-%d")
    except ValueError:
        messagebox.showerror("Invalid dates", "Please enter dates as YYYY-MM-DD.")
        return
    if sd > ed:
        messagebox.showerror("Invalid range", "Start day must be on or before end day.")
        return

    start_date = f"{start_day} 00:00:00"
    end_date = f"{end_day} 23:59:59"

    mode = None
    if username and password:
        mode = "api"
    elif alerts and responders:
        # Validate CSV file paths
        valid, error_msg = validate_file_exists(alerts)
        if not valid:
            messagebox.showerror("Invalid Alert CSV", error_msg)
            return
        valid, error_msg = validate_file_exists(responders)
        if not valid:
            messagebox.showerror("Invalid Responder CSV", error_msg)
            return
        mode = "csv"
    else:
        messagebox.showerror("Missing input", "Provide either API credentials or both CSV files.")
        return

    argv = ["GS2RCAPI.py", "--out", out_path, "--start-id", start_id]
    if mode == "api":
        argv += ["--username", username, "--password", password, "--start-date", start_date, "--end-date", end_date]
    else:
        argv += ["--alerts", alerts, "--responders", responders]
    if not var_save_api_json.get():
        argv.append("--no-save-api-json")

    def _after_success():
        base, _ = os.path.splitext(out_path)
        BUILDER.LAST_MASTER_PATH = base + "_master_responder_list.csv"
        if os.path.exists(BUILDER.LAST_MASTER_PATH):
            text_status.insert(tk.END, f"[GUI] Master list ready: {BUILDER.LAST_MASTER_PATH}\n")
        else:
            text_status.insert(tk.END, f"[GUI] Expected master list at: {BUILDER.LAST_MASTER_PATH}\n")

        global WELREQ_PATH
        WELREQ_PATH = os.path.join(os.path.dirname(os.path.abspath(out_path)), "welreq_followup.csv")
        if os.path.exists(WELREQ_PATH):
            text_status.insert(tk.END, f"[GUI] Welfare follow-up ready: {WELREQ_PATH}\n")
            load_welreq_into_view(WELREQ_PATH)
        else:
            clear_welreq_view()
            text_status.insert(tk.END, f"[GUI] No welfare follow-up at: {WELREQ_PATH}\n")

    mode_label = "API Build" if mode == "api" else "CSV Build"
    _run_cli(argv, mode_label, after_success=_after_success)


def advanced_upload_to_redcap():
    out_path = ent_out.get().strip()
    if not out_path:
        messagebox.showerror("Missing output", "Build a CSV first (output path is empty).")
        return
    if not os.path.exists(out_path):
        messagebox.showerror("File missing", f"Output CSV not found:\n{out_path}")
        return

    redcap_token = ent_redcap_token.get().strip()
    if not redcap_token:
        messagebox.showerror("Missing REDCap token", "Enter a REDCap API token before uploading.")
        return

    redcap_url = ent_redcap_url.get().strip()

    argv = [
        "GS2RCAPI.py",
        "--upload-input", out_path,
        "--out", out_path,
        "--redcap-batch-size", str(REDCAP_BATCH_DEFAULT)
    ]
    if redcap_url:
        argv += ["--redcap-url", redcap_url]
    argv += ["--redcap-token", redcap_token]

    _run_cli(argv, "REDCap Upload")


def upload_to_redcap():
    """Backwards-compatible alias."""
    return advanced_upload_to_redcap()


def run_builder():
    """Backwards-compatible alias."""
    return advanced_run_builder()


def _parse_regtime(regtime_str):
    """Parse a regtime string (dd/mm/yyyy HH:MM:SS) into a datetime object."""
    if not regtime_str or regtime_str.strip() == "":
        return None
    try:
        # Try dd/mm/yyyy HH:MM:SS format
        return datetime.strptime(regtime_str.strip(), "%d/%m/%Y %H:%M:%S")
    except ValueError:
        try:
            # Try without seconds
            return datetime.strptime(regtime_str.strip(), "%d/%m/%Y %H:%M")
        except ValueError:
            return None


# ---------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------
root = tk.Tk()
root.title("GoodSAM -> REDCap Builder")
root.geometry("1150x720")
root.minsize(980, 620)

# Split layout: left controls, right console
paned = ttk.Panedwindow(root, orient="horizontal")
paned.pack(fill="both", expand=True)

left = ttk.Frame(paned, padding=(10, 10, 10, 10))
right = ttk.Frame(paned, padding=(8, 10, 10, 10))
paned.add(left, weight=0)   # left does not expand
paned.add(right, weight=1)  # right expands

# --- Keep left pane visible & sized nicely ---
LEFT_MIN = 560  # ensure browse buttons are visible; tweak 520–600 to taste

def set_initial_sash(*_):
    try:
        root.update_idletasks()
        total_w = paned.winfo_width() or root.winfo_width()
        target = max(LEFT_MIN, min(total_w - 380, LEFT_MIN))
        paned.sashpos(0, target)
    except Exception:
        pass

def enforce_left_min(event=None):
    try:
        current = paned.sashpos(0)
        if current < LEFT_MIN:
            paned.sashpos(0, LEFT_MIN)
    except Exception:
        pass

root.after(60, set_initial_sash)
root.bind("<Map>", set_initial_sash)
root.bind("<Configure>", enforce_left_min)

# Styles (bring back green Run button look)
style = ttk.Style()
try:
    style.theme_use(style.theme_use())  # no-op; ensure theme is loaded
except Exception:
    pass

# --- Date range ---
frm_dates = ttk.LabelFrame(left, text="Date range (local)")
frm_dates.pack(fill="x", pady=(0, 8))

start_var = tk.StringVar(value=datetime.now().strftime("%Y-%m-%d"))
end_var = tk.StringVar(value=datetime.now().strftime("%Y-%m-%d"))

calendar_btn = None  # created if calendar not available

def _rebuild_date_pickers():
    global start_picker, end_picker, calendar_btn
    # Destroy existing widgets if present
    try:
        start_picker.destroy()
        end_picker.destroy()
    except Exception:
        pass

    if DateEntry is not None:
        start_widget = DateEntry(frm_dates, textvariable=start_var, date_pattern="yyyy-mm-dd", width=12)
        end_widget = DateEntry(frm_dates, textvariable=end_var, date_pattern="yyyy-mm-dd", width=12)
    else:
        start_widget = tk.Entry(frm_dates, textvariable=start_var, width=12)
        end_widget = tk.Entry(frm_dates, textvariable=end_var, width=12)

    # Assign and place
    start_picker = start_widget
    end_picker = end_widget
    start_picker.grid(row=0, column=1, padx=4, pady=3, sticky="w")
    end_picker.grid(row=0, column=3, padx=4, pady=3, sticky="w")

    # Manage the calendar install button
    if DateEntry is None:
        if calendar_btn is None:
            def install_tkcalendar():
                try:
                    messagebox.showinfo("Installing", "Attempting to install tkcalendar...\nThis may take a moment.")

                    # Try conda first (common in Anaconda environments)
                    install_success = False
                    error_messages = []

                    if shutil.which("conda"):
                        try:
                            cmd = ["conda", "install", "-y", "-c", "conda-forge", "tkcalendar"]
                            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
                            if result.returncode == 0:
                                install_success = True
                            else:
                                error_messages.append(f"conda: {result.stderr or result.stdout}")
                        except Exception as e:
                            error_messages.append(f"conda: {str(e)}")

                    # If conda failed or not available, try pip
                    if not install_success:
                        try:
                            cmd = [sys.executable, "-m", "pip", "install", "tkcalendar"]
                            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
                            if result.returncode == 0:
                                install_success = True
                            else:
                                error_messages.append(f"pip: {result.stderr or result.stdout}")
                        except Exception as e:
                            error_messages.append(f"pip: {str(e)}")

                    if not install_success:
                        raise RuntimeError("Installation failed:\n" + "\n".join(error_messages))

                    # Try to import now
                    global DateEntry
                    from tkcalendar import DateEntry as _DE
                    DateEntry = _DE
                    messagebox.showinfo("Installed", "Calendar support enabled. Replacing date fields.")
                    _rebuild_date_pickers()
                    # Remove the button once installed
                    try:
                        calendar_btn.destroy()
                    except Exception:
                        pass
                except Exception as e:
                    messagebox.showerror("Install failed", f"Could not enable calendar support.\n{e}")

            # Create and place the button at column 4
            btn = ttk.Button(frm_dates, text="Enable Calendar", command=install_tkcalendar)
            btn.grid(row=0, column=4, padx=(8, 0), pady=3, sticky="w")
            calendar_btn = btn
    else:
        # If calendar available, ensure any prior button is removed
        try:
            if calendar_btn is not None:
                calendar_btn.destroy()
        except Exception:
            pass

ttk.Label(frm_dates, text="Start day:").grid(row=0, column=0, padx=4, pady=3, sticky="e")
ttk.Label(frm_dates, text="End day:").grid(row=0, column=2, padx=8, pady=3, sticky="e")

# Initial build of the date pickers
_rebuild_date_pickers()

# --- API login ---
frame_api = ttk.LabelFrame(left, text="GoodSAM API Login")
frame_api.pack(fill="x", pady=(0, 8))

ttk.Label(frame_api, text="Username / Client ID:").grid(row=0, column=0, sticky="e", padx=4, pady=3)
ent_user = ttk.Entry(frame_api, width=44)
ent_user.grid(row=0, column=1, padx=4, pady=3, sticky="w")

ttk.Label(frame_api, text="Password / Secret:").grid(row=1, column=0, sticky="e", padx=4, pady=3)
ent_pass = ttk.Entry(frame_api, show="*", width=44)
ent_pass.grid(row=1, column=1, padx=4, pady=3, sticky="w")

ttk.Button(frame_api, text="Save Login", command=lambda: save_login(ent_user.get(), ent_pass.get())).grid(
    row=2, column=1, sticky="e", padx=4, pady=(6, 2)
)

var_save_api_json = tk.BooleanVar(value=True)
ttk.Checkbutton(
    frame_api,
    text="Save GoodSAM API JSON dumps",
    variable=var_save_api_json
).grid(row=3, column=1, sticky="w", padx=4, pady=(0, 2))

# --- CSV fallback ---
frame_csv = ttk.LabelFrame(left, text="CSV Fallback (optional)")
frame_csv.pack(fill="x", pady=(0, 8))

# Tighter rows and shorter entries so Browse fits without panning
ttk.Label(frame_csv, text="Alert CSV:").grid(row=0, column=0, sticky="e", padx=4, pady=2)
ent_alert = ttk.Entry(frame_csv, width=48)
ent_alert.grid(row=0, column=1, padx=(4, 4), pady=2, sticky="w")
ttk.Button(frame_csv, text="Browse", command=lambda: browse_file(ent_alert)).grid(row=0, column=2, padx=(4, 4), pady=2)

ttk.Label(frame_csv, text="Responder CSV:").grid(row=1, column=0, sticky="e", padx=4, pady=2)
ent_resp = ttk.Entry(frame_csv, width=48)
ent_resp.grid(row=1, column=1, padx=(4, 4), pady=2, sticky="w")
ttk.Button(frame_csv, text="Browse", command=lambda: browse_file(ent_resp)).grid(row=1, column=2, padx=(4, 4), pady=2)

# --- Output settings ---
frame_out = ttk.LabelFrame(left, text="Output Settings")
frame_out.pack(fill="x", pady=(0, 8))

ttk.Label(frame_out, text="Starting record_id:").grid(row=0, column=0, sticky="e", padx=4, pady=3)
ent_startid = ttk.Entry(frame_out, width=10)
# No default value - user must explicitly set or use "Get Next ID" button
ent_startid.grid(row=0, column=1, sticky="w", padx=4, pady=3)
def _fill_next_record_id():
    try:
        url = ent_redcap_url.get().strip() if 'ent_redcap_url' in globals() else ''
        token = ent_redcap_token.get().strip() if 'ent_redcap_token' in globals() else ''
        if not url or not token:
            messagebox.showwarning("Missing", "Enter REDCap URL and Token first.")
            return
        next_id = BUILDER.get_next_record_id(url, token, verify=True)
        ent_startid.delete(0, tk.END)
        ent_startid.insert(0, str(next_id))
        try:
            text_status.insert(tk.END, f"[GUI] Next record_id from REDCap: {next_id}\n")
            text_status.see(tk.END)
        except Exception:
            pass
    except Exception as e:
        messagebox.showerror("Get Next ID failed", str(e))
ttk.Button(frame_out, text="Get Next ID", command=_fill_next_record_id).grid(row=0, column=2, padx=(4, 4), pady=3)

ttk.Label(frame_out, text="Output file:").grid(row=1, column=0, sticky="e", padx=4, pady=3)
ent_out = ttk.Entry(frame_out, width=48)
ent_out.grid(row=1, column=1, padx=(4, 4), pady=3, sticky="w")
ttk.Button(frame_out, text="Browse", command=lambda: browse_output(ent_out)).grid(row=1, column=2, padx=(4, 4), pady=3)

# --- REDCap settings ---
frame_rc = ttk.LabelFrame(left, text="REDCap Import")
frame_rc.pack(fill="x", pady=(0, 8))

ttk.Label(frame_rc, text="API URL:").grid(row=0, column=0, sticky="e", padx=4, pady=2)
ent_redcap_url = ttk.Entry(frame_rc, width=48)
ent_redcap_url.grid(row=0, column=1, padx=(4, 4), pady=2, sticky="w")
ent_redcap_url.insert(0, DEFAULT_REDCAP_URL)

ttk.Label(frame_rc, text="API Token:").grid(row=1, column=0, sticky="e", padx=4, pady=2)
ent_redcap_token = ttk.Entry(frame_rc, show="*", width=48)
ent_redcap_token.grid(row=1, column=1, padx=(4, 4), pady=2, sticky="w")
ttk.Button(frame_rc, text="Save REDCap", command=lambda: save_redcap(ent_redcap_url.get(), ent_redcap_token.get())).grid(row=1, column=2, padx=(4, 4), pady=2)

ttk.Label(frame_rc, text="Batch size:").grid(row=2, column=0, sticky="e", padx=4, pady=2)
ent_redcap_batch = ttk.Entry(frame_rc, width=10)
# Display fixed batch size (edit via REDCAP_BATCH_DEFAULT constant if ever needed)
ent_redcap_batch.insert(0, str(REDCAP_BATCH_DEFAULT))
ent_redcap_batch.configure(state="readonly")
ent_redcap_batch.grid(row=2, column=1, sticky="w", padx=4, pady=2)

ttk.Button(frame_rc, text="Upload to REDCap", command=upload_to_redcap).grid(row=3, column=1, sticky="w", padx=4, pady=2)
# --- Action buttons ---
# Bring back the green button look using tk.Button for easy bg colors
btn_run = tk.Button(
    left,
    text="Run Build",
    command=run_builder,
    bg="#4caf50",
    fg="white",
    activebackground="#43a047",
    activeforeground="white",
    relief="raised",
    font=("Segoe UI", 11, "bold"),
    padx=8,
    pady=6,
)
btn_run.pack(fill="x", pady=(6, 6))
ttk.Button(left, text="Copy Master Responder List", command=copy_master_list_to_clipboard).pack(fill="x", pady=(0, 4))

# --- Welfare Requests panel ---
frame_wel = ttk.LabelFrame(right, text="Welfare Requests (welreq=True)")
frame_wel.pack(fill="x", pady=(0, 8))

# Treeview for highlighted rows
wel_tree = ttk.Treeview(frame_wel, columns=(), show="headings", height=6)
wel_tree.pack(fill="x", padx=4, pady=(4, 2))

# Controls under the table
wel_controls = ttk.Frame(frame_wel)
wel_controls.pack(fill="x", padx=4, pady=(0, 4))
ttk.Button(wel_controls, text="Refresh Welfare List", command=lambda: load_welreq_into_view()).pack(side="left")
ttk.Button(wel_controls, text="Copy Welfare Requests", command=copy_welreq_to_clipboard).pack(side="left", padx=(6, 0))
wel_count = ttk.Label(wel_controls, text="No welfare requests loaded")
wel_count.pack(side="right")

# --- Right console ---
frame_log = ttk.LabelFrame(right, text="Console Output")
frame_log.pack(fill="both", expand=True)
text_status = tk.Text(frame_log, wrap="word", bg="#111", fg="#eee", insertbackground="white")
text_status.pack(fill="both", expand=True)
adv_progress_bar = ttk.Progressbar(frame_log, mode="determinate", maximum=100)
adv_progress_bar.pack(fill="x", pady=(6, 0))

# Load saved credentials
u, p = load_login()
if u:
    ent_user.insert(0, u)
if p:
    ent_pass.insert(0, p)

# Load saved REDCap settings
try:
    rc_url, rc_token = load_redcap()
    if rc_url:
        ent_redcap_url.delete(0, tk.END)
        ent_redcap_url.insert(0, rc_url)
    if rc_token:
        ent_redcap_token.insert(0, rc_token)
except Exception:
    pass

# ---------------------------------------------------------------------
# Keyboard Shortcuts
# ---------------------------------------------------------------------
def setup_keyboard_shortcuts():
    """Setup keyboard shortcuts for common actions."""
    # Ctrl+R: Run Build
    root.bind('<Control-r>', lambda e: advanced_run_builder())
    root.bind('<Control-R>', lambda e: advanced_run_builder())

    # Ctrl+U: Upload to REDCap
    root.bind('<Control-u>', lambda e: advanced_upload_to_redcap())
    root.bind('<Control-U>', lambda e: advanced_upload_to_redcap())

    # Ctrl+C when welfare list has focus: Copy welfare requests
    wel_tree.bind('<Control-c>', lambda e: copy_welreq_to_clipboard())
    wel_tree.bind('<Control-C>', lambda e: copy_welreq_to_clipboard())

    # Ctrl+M: Copy Master Responder List
    root.bind('<Control-m>', lambda e: copy_master_list_to_clipboard())
    root.bind('<Control-M>', lambda e: copy_master_list_to_clipboard())

    # F5: Refresh Welfare List
    root.bind('<F5>', lambda e: load_welreq_into_view())

setup_keyboard_shortcuts()

root.mainloop()









