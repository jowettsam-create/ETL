#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
GS2RCAPI_GUI_Lite.py
-----------------------------------------
Tkinter front-end (API-only) for GS2RCAPI.py
"""

import tkinter as tk
from tkinter import ttk, messagebox
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
from datetime import datetime, timedelta

try:
    import GS2RCAPI as BUILDER
except ImportError:
    import API2RC as BUILDER  # legacy fallback

# Application name for keyring storage
# **CHANGE THIS** if you need a different keyring identifier
APP_NAME = "GoodSAM_ETL"

# Default REDCap batch size for imports
# **CHANGE THIS** if you need to adjust the batch size for your REDCap server
REDCAP_BATCH_DEFAULT = 500
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
# Clipboard helpers (master responder list)
# ---------------------------------------------------------------------
def copy_master_list_to_clipboard():
    path = getattr(BUILDER, "LAST_MASTER_PATH", None)

    if (not path or not os.path.exists(path)) and LAST_OUTPUT_PATH:
        base, _ = os.path.splitext(LAST_OUTPUT_PATH)
        candidate = base + "_master_responder_list.csv"
        if os.path.exists(candidate):
            path = candidate

    if not path or not os.path.exists(path):
        messagebox.showwarning("Not available", "No master responder list found.\nRun a build and try again.")
        return

    try:
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
# Welfare Requests helpers
# ---------------------------------------------------------------------
WELREQ_PATH = None


def _resolve_welreq_path():
    global WELREQ_PATH
    if WELREQ_PATH and os.path.exists(WELREQ_PATH):
        return WELREQ_PATH
    if LAST_OUTPUT_PATH:
        base, _ = os.path.splitext(LAST_OUTPUT_PATH)
        candidate = os.path.join(os.path.dirname(base), "welreq_followup.csv")
        if os.path.exists(candidate):
            WELREQ_PATH = candidate
            return WELREQ_PATH
    return None


def copy_welreq_to_clipboard():
    path = _resolve_welreq_path()
    if not path:
        messagebox.showwarning("Not available", "No welreq_followup.csv found.\nRun a build and try again.")
        return

    try:
        lines = []
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rec_id = (row.get("record_id") or "").strip()
                name1 = (row.get("name1") or "").strip()
                name2 = (row.get("name2") or "").strip()
                phone = (row.get("phone") or "").strip()
                eml = (row.get("eml") or "").strip()

                def _clean(x):
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
    try:
        for i in wel_tree.get_children():
            wel_tree.delete(i)
    except Exception:
        pass
    if 'wel_count' in globals():
        wel_count.configure(text="No welfare requests loaded")


def load_welreq_into_view(path=None):
    global WELREQ_PATH
    clear_welreq_view()
    p = path or _resolve_welreq_path()
    if not p or not os.path.exists(p):
        wel_count.configure(text="No welfare follow-up file found")
        return
    WELREQ_PATH = p
    try:
        with open(p, "r", encoding="utf-8-sig", newline="") as f:
            reader = list(csv.reader(f))
        if not reader:
            wel_count.configure(text="Welfare follow-up is empty")
            return
        headers = reader[0]
        rows = reader[1:]
        wel_tree["columns"] = headers
        wel_tree["show"] = "headings"
        for col in headers:
            wel_tree.heading(col, text=col)
            wel_tree.column(col, width=120, anchor="w")
        for r in rows:
            vals = (r + [""] * len(headers))[:len(headers)]
            wel_tree.insert("", tk.END, values=vals, tags=("welrow",))
        try:
            wel_tree.tag_configure("welrow", background="#fff4cc")
        except Exception:
            pass
        wel_count.configure(text=f"Welfare requests: {len(rows)} shown")
    except Exception as e:
        wel_count.configure(text="Failed to load welfare list")
        messagebox.showerror("Load failed", str(e))


# ---------------------------------------------------------------------
# Credential helpers
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
# CLI runner
# ---------------------------------------------------------------------
def _run_cli(argv, mode_label, after_success=None, after_failure=None, notify=True):
    """Run CLI command in a background thread with live progress bar.

    Returns True if the command was launched successfully, False otherwise.
    Note: This returns immediately - use after_success/after_failure callbacks for sequential operations.
    """
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
        "upload": 90,
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
                            progress_bar["value"] = progress_value
                            break

                elif msg_type == "error":
                    text_status.insert(tk.END, "ERRORS:\n" + data + "\n")
                    text_status.see(tk.END)
                elif msg_type == "done":
                    progress_bar["value"] = 100  # Complete
                    if data == 0:
                        if after_success:
                            after_success()
                        if notify:
                            messagebox.showinfo("Done", f"{mode_label} completed. See console output on the right.")
                    else:
                        text_status.insert(tk.END, f"[GUI] {mode_label} failed (exit code {data}).\n")
                        if after_failure:
                            after_failure()
                        if notify:
                            messagebox.showwarning("Action failed", f"{mode_label} failed. Check console output on the right.")
                    text_status.see(tk.END)
                    # Reset progress bar after a delay
                    root.after(1000, lambda: progress_bar.configure(value=0))
                    return  # Stop polling
                elif msg_type == "exception":
                    progress_bar["value"] = 0
                    text_status.insert(tk.END, f"[GUI] Exception: {data}\n")
                    text_status.see(tk.END)
                    if after_failure:
                        after_failure()
                    messagebox.showerror("Execution Error", data)
                    return  # Stop polling
        except queue.Empty:
            pass

        # Continue polling
        root.after(100, check_queue)

    # Initialize progress bar
    try:
        progress_bar["value"] = 0
        progress_bar["maximum"] = 100
    except Exception:
        pass

    # Start worker thread
    thread = threading.Thread(target=worker, daemon=True)
    thread.start()

    # Start polling queue
    root.after(100, check_queue)

    return True  # Command launched successfully


# ---------------------------------------------------------------------
# Automated build + upload pipeline
# ---------------------------------------------------------------------
def _parse_regtime(value: str | None) -> datetime | None:
    if not value:
        return None
    txt = value.strip().replace("  ", " ")
    if not txt:
        return None
    if ":" in txt:
        date_part, time_part = txt.split(" ", 1)
        if ":" in time_part:
            segs = time_part.split(":")
            if len(segs) == 2:
                segs.append("00")
            if segs and len(segs[0]) == 1:
                segs[0] = f"0{segs[0]}"
            time_part = ":".join(segs[:3])
            txt = f"{date_part} {time_part}"
    for fmt in ("%d/%m/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(txt, fmt)
        except ValueError:
            continue
    return None


def run_auto_pipeline():
    username = ent_user.get().strip()
    password = ent_pass.get().strip()
    redcap_url = ent_redcap_url.get().strip()
    redcap_token = ent_redcap_token.get().strip()
    debug_mode = bool(var_debug_mode.get())

    if not username or not password:
        messagebox.showerror("Missing GoodSAM credentials", "Enter GoodSAM username and password.")
        return
    if not redcap_token or not redcap_url:
        messagebox.showerror("Missing REDCap details", "Enter REDCap API URL and token.")
        return

    btn_run.config(state=tk.DISABLED)
    root.config(cursor="watch")
    root.update_idletasks()

    def _cleanup():
        """Re-enable button and restore cursor."""
        root.config(cursor="")
        btn_run.config(state=tk.NORMAL)

    try:
        text_status.insert(tk.END, "[GUI] Querying REDCap for latest record...\n")
        text_status.see(tk.END)

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
            text_status.insert(
                tk.END,
                f"[GUI] No new data window detected (start {start_dt} >= end {end_dt}). Nothing to run.\n",
            )
            text_status.see(tk.END)
            messagebox.showinfo("Nothing to do", "No new GoodSAM data window was detected.")
            _cleanup()
            return

        filename = prev_day.strftime("%y%m%d") + ".csv"
        out_path = os.path.join(DEFAULT_OUTPUT_DIR, filename)
        start_str = start_dt.strftime("%Y-%m-%d %H:%M:%S")
        end_str = end_dt.strftime("%Y-%m-%d %H:%M:%S")

        text_status.insert(
            tk.END,
            f"[GUI] Last record_id: {context.get('last_record_id')}, regtime: {last_reg or 'N/A'}\n"
        )
        text_status.insert(
            tk.END,
            f"[GUI] Next record_id: {next_id}; API window {start_str} -> {end_str}\n"
        )
        text_status.insert(tk.END, f"[GUI] Output CSV: {out_path}\n")
        text_status.see(tk.END)

        argv_build = [
            "GS2RCAPI.py",
            "--out", out_path,
            "--start-id", str(next_id),
            "--username", username,
            "--password", password,
            "--start-date", start_str,
            "--end-date", end_str,
        ]
        if not var_save_api_json.get():
            argv_build.append("--no-save-api-json")

        def _after_build_success():
            """Callback after build completes successfully."""
            global LAST_OUTPUT_PATH, WELREQ_PATH
            LAST_OUTPUT_PATH = out_path
            WELREQ_PATH = os.path.join(os.path.dirname(os.path.abspath(out_path)), "welreq_followup.csv")
            if os.path.exists(WELREQ_PATH):
                text_status.insert(tk.END, f"[GUI] Welfare follow-up ready: {WELREQ_PATH}\n")
                text_status.see(tk.END)
                load_welreq_into_view(WELREQ_PATH)
            else:
                clear_welreq_view()
                text_status.insert(tk.END, "[GUI] No welfare follow-up generated.\n")
                text_status.see(tk.END)

            if debug_mode:
                lbl_run_info.configure(
                    text=f"Last run: {filename} | Window {start_str} -> {end_str} (debug build only)"
                )
                text_status.insert(tk.END, "[GUI] Debug mode enabled: skipping REDCap upload.\n")
                text_status.see(tk.END)
                messagebox.showinfo("Debug build complete", "CSV built. Upload skipped (debug mode).")
                _cleanup()
            else:
                # Launch upload step (sequential after build)
                argv_upload = [
                    "GS2RCAPI.py",
                    "--upload-input", out_path,
                    "--out", out_path,
                    "--redcap-batch-size", str(REDCAP_BATCH_DEFAULT),
                    "--redcap-url", redcap_url,
                    "--redcap-token", redcap_token,
                ]

                def _after_upload_success():
                    lbl_run_info.configure(
                        text=f"Last run: {filename} | Window {start_str} -> {end_str}"
                    )
                    messagebox.showinfo("Success", "Build and upload completed.")
                    _cleanup()

                def _after_upload_failure():
                    text_status.insert(tk.END, "[GUI] Upload failed. Check console output above.\n")
                    text_status.see(tk.END)
                    _cleanup()

                _run_cli(argv_upload, "REDCap Upload", after_success=_after_upload_success, after_failure=_after_upload_failure, notify=True)

        def _after_build_failure():
            """Callback after build fails."""
            text_status.insert(tk.END, "[GUI] Build failed. Check console output above.\n")
            text_status.see(tk.END)
            _cleanup()

        _run_cli(argv_build, "API Build", after_success=_after_build_success, after_failure=_after_build_failure, notify=True)

    except Exception as exc:
        text_status.insert(tk.END, f"[GUI] Error during pipeline setup: {str(exc)}\n")
        text_status.see(tk.END)
        messagebox.showerror("Auto run failed", str(exc))
        _cleanup()

#*** End Patch

# ---------------------------------------------------------------------
# GUI layout (API-lite)
# ---------------------------------------------------------------------
root = tk.Tk()
root.title("GoodSAM \u2192 REDCap Builder (API Lite)")
root.geometry("1000x640")
root.minsize(900, 600)

main = ttk.Frame(root, padding=10)
main.pack(fill="both", expand=True)

ttk.Label(
    main,
    text="Click the button below to fetch the latest GoodSAM data and upload it to REDCap.",
    font=("Segoe UI", 12, "bold")
).pack(fill="x", pady=(0, 10))

top = ttk.Frame(main)
top.pack(fill="x", pady=(0, 10))
bottom = ttk.Frame(main)
bottom.pack(fill="both", expand=True)

# Left pane: GoodSAM credentials
left_api = ttk.LabelFrame(top, text="GoodSAM Credentials", padding=10)
left_api.pack(side="left", fill="both", expand=True, padx=(0, 10))

ttk.Label(left_api, text="Username / Client ID:").grid(row=0, column=0, sticky="e", padx=4, pady=3)
ent_user = ttk.Entry(left_api, width=44)
ent_user.grid(row=0, column=1, padx=4, pady=3, sticky="w")

ttk.Label(left_api, text="Password / Secret:").grid(row=1, column=0, sticky="e", padx=4, pady=3)
ent_pass = ttk.Entry(left_api, show="*", width=44)
ent_pass.grid(row=1, column=1, padx=4, pady=3, sticky="w")

ttk.Button(
    left_api,
    text="Save Login",
    command=lambda: save_login(ent_user.get(), ent_pass.get())
).grid(row=2, column=1, sticky="e", padx=4, pady=(6, 2))

var_save_api_json = tk.BooleanVar(value=True)
ttk.Checkbutton(
    left_api,
    text="Save GoodSAM API JSON dumps",
    variable=var_save_api_json
).grid(row=3, column=1, sticky="w", padx=4, pady=(0, 2))

# Right pane: REDCap settings
right_rc = ttk.LabelFrame(top, text="REDCap API Settings", padding=10)
right_rc.pack(side="left", fill="both", expand=True)

ttk.Label(right_rc, text="API URL:").grid(row=0, column=0, sticky="e", padx=4, pady=3)
ent_redcap_url = ttk.Entry(right_rc, width=48)
ent_redcap_url.grid(row=0, column=1, padx=(4, 4), pady=3, sticky="w")
ent_redcap_url.insert(0, "https://nswa-redcap.ambulance.nsw.gov.au/redcap/api/")

ttk.Label(right_rc, text="API Token:").grid(row=1, column=0, sticky="e", padx=4, pady=3)
ent_redcap_token = ttk.Entry(right_rc, show="*", width=48)
ent_redcap_token.grid(row=1, column=1, padx=(4, 4), pady=3, sticky="w")

ttk.Button(
    right_rc,
    text="Save REDCap",
    command=lambda: save_redcap(ent_redcap_url.get(), ent_redcap_token.get())
).grid(row=1, column=2, padx=(4, 4), pady=3)

ttk.Button(
    right_rc,
    text="Copy Master Responder List",
    command=copy_master_list_to_clipboard
).grid(row=3, column=1, sticky="w", padx=4, pady=6)

lbl_run_info = ttk.Label(main, text="Ready to run.", anchor="w")
lbl_run_info.pack(fill="x", pady=(0, 6))

var_debug_mode = tk.BooleanVar(value=False)
ttk.Checkbutton(
    main,
    text="Debug mode (build CSV only, skip REDCap upload)",
    variable=var_debug_mode
).pack(fill="x", pady=(0, 6))

btn_run = tk.Button(
    main,
    text="Start: Build + Upload Latest",
    command=run_auto_pipeline,
    bg="#4caf50",
    fg="white",
    activebackground="#43a047",
    activeforeground="white",
    relief="raised",
    font=("Segoe UI", 12, "bold"),
    padx=8,
    pady=8,
)
btn_run.pack(fill="x", pady=(0, 10))

# Bottom layout
bottom_left = ttk.LabelFrame(bottom, text="Welfare Requests", padding=10)
bottom_left.pack(side="left", fill="both", expand=True, padx=(0, 10))
bottom_left.configure(width=420, height=220)
bottom_left.pack_propagate(False)

wel_tree = ttk.Treeview(bottom_left, columns=(), show="headings", height=6)
wel_tree.pack(fill="both", expand=True, padx=4, pady=(4, 2))

wel_controls = ttk.Frame(bottom_left)
wel_controls.pack(fill="x", padx=4, pady=(0, 4))

ttk.Button(wel_controls, text="Refresh Welfare List", command=lambda: load_welreq_into_view()).pack(side="left")

ttk.Button(wel_controls, text="Copy Welfare Requests", command=copy_welreq_to_clipboard).pack(side="left", padx=(6, 0))

wel_count = ttk.Label(wel_controls, text="No welfare requests loaded")
wel_count.pack(side="right")

bottom_right = ttk.LabelFrame(bottom, text="Console Output", padding=10)
bottom_right.pack(side="left", fill="both", expand=True)
bottom_right.configure(width=520, height=220)
bottom_right.pack_propagate(False)

text_status = tk.Text(bottom_right, wrap="word", bg="#111", fg="#eee", insertbackground="white", height=10)
text_status.pack(fill="both", expand=True)

progress_bar = ttk.Progressbar(bottom_right, mode="determinate", maximum=100)
progress_bar.pack(fill="x", pady=(6, 0))

# Load stored credentials
u, p = load_login()
if u:
    ent_user.insert(0, u)
if p:
    ent_pass.insert(0, p)

rc_url, rc_token = load_redcap()
if rc_url:
    ent_redcap_url.delete(0, tk.END); ent_redcap_url.insert(0, rc_url)
if rc_token:
    ent_redcap_token.insert(0, rc_token)

root.mainloop()


