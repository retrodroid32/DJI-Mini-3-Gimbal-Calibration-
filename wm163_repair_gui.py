#!/usr/bin/env python3
"""Tkinter desktop GUI for the DJI Mini 3 / WM163 repair project.

The GUI is intentionally a thin front end over the existing project functions.
It does not duplicate firmware/calibration protocol logic.

Safety boundary:
- Read-only diagnostics and file validation are available.
- Capture-backed Basic/Advanced calibration and 40021 repair are available with
  explicit confirmations.
- Live Service-FW flashing remains locked because wm163_service_flash_live.py
  is still deliberately interlocked pending first hardware validation.
- Exact WM163 v01.00.0500 production-firmware validation is available offline.
- "Restore Current Firmware" remains locked until the live production restore
  sequence is independently validated.
"""

from __future__ import annotations

import contextlib
import io
import pathlib
import queue
import re
import threading
import traceback
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

import mini3_gimbal_cal as cal
import wm163_service_flash_live as service_fw
import wm163_assistant_cache as assistant_cache
import wm163_private_fw as private_fw
import wm163_production_fw as production_fw
import wm163_live_preflight as live_preflight
from wm163_service_fw_inspect import inspect_package

try:
    import serial
    from serial.tools import list_ports
except ImportError:  # pragma: no cover
    serial = None
    list_ports = None


BG = "#07100b"
PANEL = "#0b1710"
PANEL_ALT = "#0f1e15"
LOG_BG = "#020704"
BORDER = "#285c3a"
GREEN = "#76ff9f"
GREEN_DIM = "#45ad68"
TEXT = "#cef9d8"
MUTED = "#769783"
WARN = "#ffd166"
BAD = "#ff6262"
LOCKED = "#626c65"


class QueueWriter(io.TextIOBase):
    def __init__(self, events: queue.Queue):
        self.events = events
        self.parts: list[str] = []

    def write(self, text: str) -> int:
        if text:
            self.parts.append(text)
            self.events.put(("log", text))
        return len(text)

    def flush(self) -> None:
        pass

    @property
    def text(self) -> str:
        return "".join(self.parts)


class WM163RepairGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(f"WM163 Repair Tool v{cal.VERSION}")
        self.root.geometry("1480x900")
        self.root.minsize(1120, 720)
        self.root.configure(bg=BG)

        self.events: queue.Queue = queue.Queue()
        self.busy = False
        self.connection_ready = False
        self.action_buttons: list[ttk.Button] = []

        self.service_package_path = tk.StringVar(value="")
        self.service_loader_path = tk.StringVar(value="")
        self.production_package_path = tk.StringVar(value="")
        self._assistant_cache_matches = []

        self.device_vars = {
            "Model": tk.StringVar(value="DJI Mini 3 / WM163"),
            "Drone SN": tk.StringVar(value="—"),
            "Gimbal SN": tk.StringVar(value="—"),
            "Camera SN / ID": tk.StringVar(value="—"),
            "FW FlightCtrl": tk.StringVar(value="—"),
            "FW Gimbal": tk.StringVar(value="—"),
            "FW Camera": tk.StringVar(value="—"),
            "FW Battery": tk.StringVar(value="—"),
        }

        self.flash_vars = {
            "Detected Model": tk.StringVar(value="DJI Mini 3 / WM163"),
            "Current FW": tk.StringVar(value="—"),
            "Service FW": tk.StringVar(value="30.00.0100"),
            "Production FW": tk.StringVar(value="Not found"),
            "Selected File": tk.StringVar(value="—"),
            "File Size": tk.StringVar(value="—"),
            "MD5": tk.StringVar(value="—"),
            "SHA256": tk.StringVar(value="—"),
            "Validation": tk.StringVar(value="NOT VALIDATED"),
        }

        self._setup_style()
        self._build_ui()
        self.refresh_ports()
        self.root.after(75, self._drain_events)
        self.root.after(350, self._auto_find_private_service_firmware_silent)
        self.root.after(700, self._auto_find_production_firmware_silent)

    # ---------- styling ----------

    def _setup_style(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure(".", background=BG, foreground=TEXT, fieldbackground=PANEL_ALT)
        style.configure("TFrame", background=BG)
        style.configure("Panel.TFrame", background=PANEL)
        style.configure("Title.TLabel", background=BG, foreground=GREEN, font=("Segoe UI", 20, "bold"))
        style.configure("Sub.TLabel", background=BG, foreground=MUTED, font=("Segoe UI", 9))
        style.configure("PanelSub.TLabel", background=PANEL, foreground=MUTED, font=("Segoe UI", 9))
        style.configure("Section.TLabel", background=PANEL, foreground=WARN, font=("Segoe UI", 10, "bold"))
        style.configure("InfoName.TLabel", background=PANEL, foreground=WARN, font=("Consolas", 9, "bold"))
        style.configure("InfoValue.TLabel", background=PANEL, foreground=GREEN, font=("Consolas", 9))
        style.configure("Status.TLabel", background=BG, foreground=BAD, font=("Segoe UI", 9, "bold"))
        style.configure("Ready.Status.TLabel", background=BG, foreground=GREEN, font=("Segoe UI", 9, "bold"))
        style.configure("Locked.TLabel", background=PANEL, foreground=LOCKED, font=("Segoe UI", 9, "bold"))

        style.configure(
            "TButton",
            background=PANEL_ALT,
            foreground=GREEN,
            bordercolor=BORDER,
            lightcolor=BORDER,
            darkcolor=BORDER,
            padding=(10, 7),
        )
        style.map(
            "TButton",
            background=[("active", "#153722"), ("disabled", "#111914")],
            foreground=[("disabled", "#56635a")],
        )
        style.configure(
            "Danger.TButton",
            background="#221212",
            foreground=WARN,
            bordercolor="#653030",
            padding=(10, 7),
        )
        style.configure(
            "Locked.TButton",
            background="#141714",
            foreground="#6c766f",
            bordercolor="#303630",
            padding=(10, 7),
        )
        style.configure("TCombobox", fieldbackground=PANEL_ALT, foreground=TEXT, arrowcolor=GREEN)
        style.configure("Horizontal.TProgressbar", background=GREEN_DIM, troughcolor=PANEL_ALT)

        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure(
            "TNotebook.Tab",
            background=PANEL_ALT,
            foreground=MUTED,
            padding=(18, 8),
            borderwidth=1,
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", PANEL)],
            foreground=[("selected", GREEN)],
        )

    def _panel(self, parent, title: str) -> tuple[tk.Frame, ttk.Frame]:
        outer = tk.Frame(parent, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        ttk.Label(outer, text=title, style="Section.TLabel").pack(anchor="w", padx=10, pady=(8, 4))
        body = ttk.Frame(outer, style="Panel.TFrame")
        body.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        return outer, body

    # ---------- top-level UI ----------

    def _build_ui(self) -> None:
        top = ttk.Frame(self.root)
        top.pack(fill="x", padx=12, pady=(10, 6))

        title_box = ttk.Frame(top)
        title_box.pack(side="left")
        ttk.Label(title_box, text="WM163 Repair Tool", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            title_box,
            text="DJI Mini 3 / WM163 — diagnostics, firmware service workflow and gimbal repair",
            style="Sub.TLabel",
        ).pack(anchor="w")

        conn = ttk.Frame(top)
        conn.pack(side="right", pady=2)
        ttk.Label(conn, text="Port:", style="Sub.TLabel").grid(row=0, column=0, padx=(0, 5))
        self.port_combo = ttk.Combobox(conn, width=31, state="normal")
        self.port_combo.grid(row=0, column=1, padx=4)
        ttk.Button(conn, text="Refresh", command=self.refresh_ports).grid(row=0, column=2, padx=4)
        ttk.Button(conn, text="Manual COM…", command=self.choose_manual_port).grid(row=0, column=3, padx=4)
        self.connect_btn = ttk.Button(conn, text="Connect", command=self.connect_test)
        self.connect_btn.grid(row=0, column=4, padx=(4, 8))
        self.status_label = ttk.Label(conn, text="DISCONNECTED", style="Status.TLabel")
        self.status_label.grid(row=0, column=5, padx=4)

        info_outer, info = self._panel(self.root, "Device Info")
        info_outer.pack(fill="x", padx=12, pady=5)

        for idx, (label, var) in enumerate(self.device_vars.items()):
            row = idx % 4
            col = (idx // 4) * 2
            ttk.Label(info, text=f"{label}:", style="InfoName.TLabel").grid(
                row=row, column=col, sticky="e", padx=(4, 8), pady=2
            )
            ttk.Label(info, textvariable=var, style="InfoValue.TLabel").grid(
                row=row, column=col + 1, sticky="w", padx=(0, 24), pady=2
            )
        info.columnconfigure(1, weight=1)
        info.columnconfigure(3, weight=1)

        read_btn = ttk.Button(info, text="Read Device Info", command=self.read_device_info)
        read_btn.grid(row=4, column=0, columnspan=4, sticky="ew", padx=4, pady=(8, 0))
        self.action_buttons.append(read_btn)

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=12, pady=(4, 12))

        self.repair_tab = ttk.Frame(self.notebook)
        self.flash_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.repair_tab, text="Repair Workflow")
        self.notebook.add(self.flash_tab, text="FW Flasher")

        self._build_repair_tab()
        self._build_flash_tab()

    # ---------- repair page ----------

    def _build_repair_tab(self) -> None:
        main = ttk.Frame(self.repair_tab)
        main.pack(fill="both", expand=True, padx=4, pady=6)
        main.columnconfigure(0, weight=5)
        main.columnconfigure(1, weight=6)
        main.rowconfigure(0, weight=1)

        # Left repair workflow gets its own vertical scroll area so Steps 4/5
        # and Basic Calibration remain reachable on 768/900-pixel desktops.
        left_host = ttk.Frame(main)
        left_host.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        left_canvas = tk.Canvas(
            left_host,
            bg=BG,
            highlightthickness=0,
            borderwidth=0,
        )
        left_scroll = ttk.Scrollbar(left_host, orient="vertical", command=left_canvas.yview)
        left_canvas.configure(yscrollcommand=left_scroll.set)
        left_scroll.pack(side="right", fill="y")
        left_canvas.pack(side="left", fill="both", expand=True)

        left = ttk.Frame(left_canvas)
        left_window = left_canvas.create_window((0, 0), window=left, anchor="nw")

        def sync_left_region(_event=None):
            left_canvas.configure(scrollregion=left_canvas.bbox("all"))

        def sync_left_width(event):
            left_canvas.itemconfigure(left_window, width=event.width)

        left.bind("<Configure>", sync_left_region)
        left_canvas.bind("<Configure>", sync_left_width)

        def left_mousewheel(event):
            delta = -1 if event.delta > 0 else 1
            left_canvas.yview_scroll(delta * 3, "units")
            return "break"

        left_canvas.bind("<Enter>", lambda _e: left_canvas.bind_all("<MouseWheel>", left_mousewheel))
        left_canvas.bind("<Leave>", lambda _e: left_canvas.unbind_all("<MouseWheel>"))

        right = ttk.Frame(main)
        right.grid(row=0, column=1, sticky="nsew", padx=(6, 0))

        workflow_outer, workflow = self._panel(left, "WM163 Repair Workflow")
        workflow_outer.pack(fill="x", pady=(0, 8))
        ttk.Label(
            workflow,
            text=(
                "For BOTH 40011 + 40021, use the numbered steps below in order. "
                "40011 requires Service Firmware before Advanced Calibration. "
                "40021 does NOT require Service Firmware and can be repaired independently."
            ),
            style="PanelSub.TLabel",
            wraplength=600,
        ).pack(anchor="w", pady=(0, 10))

        # Step 1
        ttk.Label(
            workflow,
            text="1. Diagnose current errors",
            style="Section.TLabel",
        ).pack(anchor="w", pady=(2, 2))
        ttk.Label(
            workflow,
            text="Read the current gimbal status first. No firmware or calibration data is written.",
            style="PanelSub.TLabel",
            wraplength=600,
        ).pack(anchor="w", pady=(0, 4))

        step1 = ttk.Frame(workflow, style="Panel.TFrame")
        step1.pack(fill="x", pady=(0, 10))
        step1.columnconfigure(0, weight=1)
        step1.columnconfigure(1, weight=1)
        error_btn = ttk.Button(step1, text="Read Gimbal Errors", command=self.read_errors)
        error_btn.grid(row=0, column=0, sticky="ew", padx=(0, 3))
        sensor_btn = ttk.Button(step1, text="Run 40011 Sensor Diagnostics", command=self.sensor_diagnostics)
        sensor_btn.grid(row=0, column=1, sticky="ew", padx=(3, 0))
        self.action_buttons.extend([error_btn, sensor_btn])

        # Step 2
        ttk.Label(
            workflow,
            text="2. Flash Service Firmware  —  REQUIRED for 40011",
            style="Section.TLabel",
        ).pack(anchor="w", pady=(2, 2))
        ttk.Label(
            workflow,
            text=(
                "Required before the Advanced Calibration that clears 40011. "
                "Skip this step when repairing 40021 only."
            ),
            style="PanelSub.TLabel",
            wraplength=600,
        ).pack(anchor="w", pady=(0, 4))
        fw_btn = ttk.Button(
            workflow,
            text="Go to FW Flasher  →",
            command=self.open_fw_flasher,
        )
        fw_btn.pack(fill="x", pady=(0, 10))

        # Step 3
        ttk.Label(
            workflow,
            text="3. Advanced Calibration  —  clears 40011",
            style="Section.TLabel",
        ).pack(anchor="w", pady=(2, 2))
        ttk.Label(
            workflow,
            text=(
                "Run only after the WM163 Service Firmware is active. "
                "Capture-backed sequence: Joint Coarse → Linear Hall → validation clear."
            ),
            style="PanelSub.TLabel",
            wraplength=600,
        ).pack(anchor="w", pady=(0, 4))
        adv_btn = ttk.Button(
            workflow,
            text="Run Advanced Calibration (40011)",
            command=self.advanced_calibration,
        )
        adv_btn.pack(fill="x", pady=(0, 10))
        self.action_buttons.append(adv_btn)

        # Step 4
        ttk.Label(
            workflow,
            text="4. Fix 40021 IMU Data Mismatch",
            style="Section.TLabel",
        ).pack(anchor="w", pady=(2, 2))
        ttk.Label(
            workflow,
            text=(
                "Independent of Service Firmware. The tool first requires 40021 to be active, "
                "then sends the capture-confirmed short repair and reboots the aircraft."
            ),
            style="PanelSub.TLabel",
            wraplength=600,
        ).pack(anchor="w", pady=(0, 4))
        fix_btn = ttk.Button(
            workflow,
            text="Fix Gimbal IMU Error (40021)",
            command=self.fix_40021,
        )
        fix_btn.pack(fill="x", pady=(0, 10))
        self.action_buttons.append(fix_btn)

        # Step 5
        ttk.Label(
            workflow,
            text="5. Reconnect and verify",
            style="Section.TLabel",
        ).pack(anchor="w", pady=(2, 2))
        ttk.Label(
            workflow,
            text="After the 40021 reboot, reconnect and confirm that neither 40011 nor 40021 remains active.",
            style="PanelSub.TLabel",
            wraplength=600,
        ).pack(anchor="w", pady=(0, 4))
        verify_btn = ttk.Button(
            workflow,
            text="Verify Gimbal Errors",
            command=self.read_errors,
        )
        verify_btn.pack(fill="x", pady=(0, 4))
        self.action_buttons.append(verify_btn)

        basic_outer, basic = self._panel(left, "Basic Calibration — separate from 40011 repair")
        basic_outer.pack(fill="x", pady=8)
        ttk.Label(
            basic,
            text=(
                "Normal DJI gimbal auto-calibration. This is not the Service-Firmware "
                "Advanced Calibration used to clear 40011."
            ),
            style="PanelSub.TLabel",
            wraplength=600,
        ).pack(anchor="w", pady=(0, 5))
        basic_btn = ttk.Button(basic, text="Run Basic Calibration", command=self.basic_calibration)
        basic_btn.pack(fill="x", pady=3)
        self.action_buttons.append(basic_btn)

        self._build_log_panel(right)

    def open_fw_flasher(self) -> None:
        self.notebook.select(self.flash_tab)


    # ---------- flasher page ----------

    def _build_flash_tab(self) -> None:
        # The flasher page is intentionally scrollable because the validation,
        # file-picker, progress, action and log sections together are taller
        # than many 768/900-pixel Windows desktops.
        scroll_host = ttk.Frame(self.flash_tab)
        scroll_host.pack(fill="both", expand=True, padx=4, pady=6)

        canvas = tk.Canvas(
            scroll_host,
            bg=BG,
            highlightthickness=0,
            borderwidth=0,
        )
        page_scroll = ttk.Scrollbar(scroll_host, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=page_scroll.set)

        page_scroll.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        wrapper = ttk.Frame(canvas)
        window_id = canvas.create_window((0, 0), window=wrapper, anchor="nw")

        def sync_scrollregion(_event=None):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def sync_width(event):
            canvas.itemconfigure(window_id, width=event.width)

        wrapper.bind("<Configure>", sync_scrollregion)
        canvas.bind("<Configure>", sync_width)

        def on_mousewheel(event):
            delta = -1 if event.delta > 0 else 1
            canvas.yview_scroll(delta * 3, "units")
            return "break"

        canvas.bind("<Enter>", lambda _e: canvas.bind_all("<MouseWheel>", on_mousewheel))
        canvas.bind("<Leave>", lambda _e: canvas.unbind_all("<MouseWheel>"))

        flasher_outer, body = self._panel(wrapper, "FW Flasher")
        flasher_outer.pack(fill="both", expand=True)

        header = ttk.Frame(body, style="Panel.TFrame")
        header.pack(fill="x", pady=(0, 12))
        ttk.Label(
            header,
            text="WM163 firmware service workflow",
            style="Section.TLabel",
        ).pack(anchor="w")
        ttk.Label(
            header,
            text=(
                "Service Firmware is REQUIRED before Advanced Calibration can clear 40011. "
                "It is NOT required for the independent 40021 short repair. "
                "Live Service-FW installation stays locked until the first deliberate "
                "hardware-validation run is approved."
            ),
            style="PanelSub.TLabel",
            wraplength=1000,
        ).pack(anchor="w", pady=(3, 0))

        grid = ttk.Frame(body, style="Panel.TFrame")
        grid.pack(fill="x", pady=(0, 12))
        grid.columnconfigure(1, weight=1)

        rows = [
            ("Detected Model", "Detected Model"),
            ("Current FW", "Current FW"),
            ("Service FW", "Service FW"),
            ("Production FW", "Production FW"),
            ("Selected File", "Selected File"),
            ("File Size", "File Size"),
            ("MD5", "MD5"),
            ("SHA256", "SHA256"),
            ("Validation", "Validation"),
        ]
        for row, (label, key) in enumerate(rows):
            ttk.Label(grid, text=f"{label}:", style="InfoName.TLabel").grid(
                row=row, column=0, sticky="e", padx=(0, 10), pady=3
            )
            ttk.Label(grid, textvariable=self.flash_vars[key], style="InfoValue.TLabel").grid(
                row=row, column=1, sticky="w", pady=3
            )

        files_outer, files = self._panel(body, "Firmware Files")
        files_outer.pack(fill="x", pady=8)

        self._file_row(
            files,
            row=0,
            label="Service package",
            variable=self.service_package_path,
            command=self.choose_service_package,
        )
        self._file_row(
            files,
            row=1,
            label="Session-A loader",
            variable=self.service_loader_path,
            command=self.choose_loader,
        )
        ttk.Label(files, text="DJI Assistant production cache:", style="InfoName.TLabel").grid(
            row=2, column=0, sticky="e", padx=(0, 8), pady=4
        )
        production_entry = tk.Entry(
            files,
            textvariable=self.production_package_path,
            bg=PANEL_ALT,
            fg=TEXT,
            insertbackground=GREEN,
            relief="flat",
        )
        production_entry.grid(row=2, column=1, sticky="ew", pady=4)

        production_buttons = ttk.Frame(files, style="Panel.TFrame")
        production_buttons.grid(row=2, column=2, padx=(8, 0), pady=4, sticky="e")
        ttk.Button(
            production_buttons,
            text="Auto Find",
            command=self.auto_find_production_firmware,
        ).pack(side="left", padx=(0, 4))
        ttk.Button(
            production_buttons,
            text="Browse File…",
            command=self.choose_production_package,
        ).pack(side="left", padx=(0, 4))
        ttk.Button(
            production_buttons,
            text="Browse Folder…",
            command=self.choose_production_cache,
        ).pack(side="left")

        validate_btn = ttk.Button(files, text="Validate Service Firmware", command=self.validate_service_fw)
        validate_btn.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(9, 3))
        self.action_buttons.append(validate_btn)

        validate_production_btn = ttk.Button(
            files,
            text="Validate Production Firmware",
            command=self.validate_production_fw,
        )
        validate_production_btn.grid(row=4, column=0, columnspan=3, sticky="ew", pady=3)
        self.action_buttons.append(validate_production_btn)

        live_preflight_btn = ttk.Button(
            files,
            text="Run READ-ONLY Live Preflight",
            command=self.run_live_preflight,
        )
        live_preflight_btn.grid(row=5, column=0, columnspan=3, sticky="ew", pady=(3, 8))
        self.action_buttons.append(live_preflight_btn)

        progress_outer, progress_body = self._panel(body, "Flash Progress")
        progress_outer.pack(fill="x", pady=8)
        self.flash_progress = ttk.Progressbar(progress_body, mode="determinate", maximum=100)
        self.flash_progress.pack(fill="x", pady=(5, 5))
        self.flash_progress_label = ttk.Label(
            progress_body,
            text="Ready. No firmware write is enabled.",
            style="PanelSub.TLabel",
        )
        self.flash_progress_label.pack(anchor="w")

        actions = ttk.Frame(body, style="Panel.TFrame")
        actions.pack(fill="x", pady=(12, 5))
        actions.columnconfigure(0, weight=1)
        actions.columnconfigure(1, weight=1)

        self.flash_service_btn = ttk.Button(
            actions,
            text="Flash Service FW  —  LOCKED",
            style="Locked.TButton",
            state="disabled",
        )
        self.flash_service_btn.grid(row=0, column=0, sticky="ew", padx=(0, 6))

        self.restore_fw_btn = ttk.Button(
            actions,
            text="Restore Production FW  —  LOCKED (protocol unproven)",
            style="Locked.TButton",
            state="disabled",
        )
        self.restore_fw_btn.grid(row=0, column=1, sticky="ew", padx=(6, 0))

        ttk.Label(
            body,
            text=(
                "Service FW live mode is still hard-disabled in wm163_service_flash_live.py. "
                "The exact WM163 v01.00.0500 production archive and its offline "
                "Session-B candidate stream are validated. Production restore remains "
                "disabled because the live restore handshake/finalize/commit sequence "
                "has not yet been independently captured or proven."
            ),
            style="Locked.TLabel",
            wraplength=1050,
        ).pack(anchor="w", pady=(6, 0))

        log_outer, log_body = self._panel(body, "Flasher Log")
        log_outer.pack(fill="both", expand=True, pady=(12, 0))
        self.flash_log = tk.Text(
            log_body,
            height=12,
            bg=LOG_BG,
            fg=GREEN_DIM,
            insertbackground=GREEN,
            relief="flat",
            font=("Consolas", 9),
            wrap="word",
            state="disabled",
        )
        flash_scroll = ttk.Scrollbar(log_body, orient="vertical", command=self.flash_log.yview)
        self.flash_log.configure(yscrollcommand=flash_scroll.set)
        self.flash_log.pack(side="left", fill="both", expand=True)
        flash_scroll.pack(side="right", fill="y")

    def _file_row(self, parent, *, row: int, label: str, variable: tk.StringVar, command) -> None:
        ttk.Label(parent, text=f"{label}:", style="InfoName.TLabel").grid(
            row=row, column=0, sticky="e", padx=(0, 8), pady=4
        )
        entry = tk.Entry(
            parent,
            textvariable=variable,
            bg=PANEL_ALT,
            fg=TEXT,
            insertbackground=GREEN,
            relief="flat",
        )
        entry.grid(row=row, column=1, sticky="ew", pady=4)
        ttk.Button(parent, text="Browse…", command=command).grid(row=row, column=2, padx=(8, 0), pady=4)
        parent.columnconfigure(1, weight=1)

    def _build_log_panel(self, parent) -> None:
        log_outer, log_body = self._panel(parent, "Log")
        log_outer.pack(fill="both", expand=True)
        log_body.rowconfigure(0, weight=1)
        log_body.columnconfigure(0, weight=1)

        self.log = tk.Text(
            log_body,
            bg=LOG_BG,
            fg=GREEN_DIM,
            insertbackground=GREEN,
            selectbackground="#20452e",
            relief="flat",
            font=("Consolas", 9),
            wrap="word",
            state="disabled",
        )
        scroll = ttk.Scrollbar(log_body, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=scroll.set)
        self.log.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")

        bottom = ttk.Frame(log_body, style="Panel.TFrame")
        bottom.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(7, 0))
        bottom.columnconfigure(0, weight=1)
        self.progress = ttk.Progressbar(bottom, mode="indeterminate")
        self.progress.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ttk.Button(bottom, text="Clear", command=self.clear_log).grid(row=0, column=1)

        self._append_log(
            f"WM163 Repair Tool v{cal.VERSION}\n"
            "Service-FW live flashing is intentionally locked.\n"
            "Select the DJI USB Virtual COM port and press Connect.\n\n"
        )

    # ---------- serial / common tasks ----------

    def refresh_ports(self) -> None:
        found: list[tuple[int, str]] = []
        if list_ports is not None:
            for p in list_ports.comports():
                desc = p.description or "Serial device"
                haystack = f"{p.device} {desc} {getattr(p, 'manufacturer', '')}".lower()
                vid = getattr(p, "vid", None)

                is_dji = (
                    vid == 0x2CA3
                    or "dji" in haystack
                    or "virtual com" in haystack
                )
                priority = 0 if is_dji else 1
                tag = " [DJI]" if is_dji else ""
                found.append((priority, f"{p.device} — {desc}{tag}"))

        values = [text for _priority, text in sorted(found, key=lambda item: (item[0], item[1]))]
        current = self.port_combo.get().strip()
        self.port_combo["values"] = values

        # Preserve a manually typed COM port even if Windows is not currently
        # advertising it through SetupAPI/list_ports.
        current_port = current.split(" — ", 1)[0] if current else ""
        current_known = next((v for v in values if v.split(" — ", 1)[0] == current_port), None)
        if current_known:
            self.port_combo.set(current_known)
            return

        dji_port = next((v for v in values if v.endswith("[DJI]")), None)
        if dji_port:
            self.port_combo.set(dji_port)
        elif current:
            self.port_combo.set(current)
        elif values:
            self.port_combo.set(values[0])
        else:
            self.port_combo.set("COM23")

    def choose_manual_port(self) -> None:
        current = self._port()
        value = simpledialog.askstring(
            "Manual COM Port",
            "Enter the DJI USB Virtual COM port (for example COM23):",
            initialvalue=current,
            parent=self.root,
        )
        if not value:
            return
        value = value.strip().upper()
        if not re.fullmatch(r"COM\d+", value):
            messagebox.showerror(
                "Invalid COM port",
                "Enter a Windows COM port such as COM23.",
                parent=self.root,
            )
            return
        self.port_combo.set(f"{value} — manual DJI USB Virtual COM")

    def _port(self) -> str:
        text = self.port_combo.get().strip()
        return text.split(" — ", 1)[0] if text else "COM23"

    def _append_log(self, text: str) -> None:
        if hasattr(self, "log"):
            self.log.configure(state="normal")
            self.log.insert("end", text)
            self.log.see("end")
            self.log.configure(state="disabled")
        if hasattr(self, "flash_log"):
            self.flash_log.configure(state="normal")
            self.flash_log.insert("end", text)
            self.flash_log.see("end")
            self.flash_log.configure(state="disabled")

    def clear_log(self) -> None:
        for widget_name in ("log", "flash_log"):
            widget = getattr(self, widget_name, None)
            if widget is not None:
                widget.configure(state="normal")
                widget.delete("1.0", "end")
                widget.configure(state="disabled")

    def _set_busy(self, busy: bool, label: str = "") -> None:
        self.busy = busy
        for button in self.action_buttons:
            button.configure(state="disabled" if busy else "normal")
        self.connect_btn.configure(state="disabled" if busy else "normal")
        if hasattr(self, "progress"):
            if busy:
                self.progress.start(12)
            else:
                self.progress.stop()
        if busy:
            self._append_log(f"\n=== {label} ===\n")

    def _run_task(self, label: str, fn, done=None) -> None:
        if self.busy:
            messagebox.showinfo("Busy", "Another operation is still running.")
            return

        self._set_busy(True, label)

        def worker():
            writer = QueueWriter(self.events)
            rc = 99
            try:
                with contextlib.redirect_stdout(writer), contextlib.redirect_stderr(writer):
                    value = fn()
                rc = int(value or 0)
            except Exception:
                writer.write(traceback.format_exc())
                rc = 99
            self.events.put(("done", label, rc, writer.text, done))

        threading.Thread(target=worker, daemon=True).start()

    def _drain_events(self) -> None:
        try:
            while True:
                event = self.events.get_nowait()
                if event[0] == "log":
                    self._append_log(event[1])
                elif event[0] == "done":
                    _, label, rc, output, callback = event
                    self._set_busy(False)
                    self._append_log(
                        f"=== {label}: {'PASS' if rc == 0 else f'ENDED rc={rc}'} ===\n"
                    )
                    if callback:
                        callback(rc, output)
        except queue.Empty:
            pass
        self.root.after(75, self._drain_events)

    def _require_connection(self) -> bool:
        if self.connection_ready:
            return True
        messagebox.showwarning(
            "Not connected",
            "Select the DJI USB Virtual COM port and press Connect first.",
        )
        return False

    def connect_test(self) -> None:
        if serial is None:
            messagebox.showerror("Missing dependency", "pyserial is not installed.")
            return
        port = self._port()

        def task():
            print(f"Checking {port} @ 9600...")
            with serial.Serial(port, baudrate=9600, timeout=0.20):
                pass
            print(f"{port}: serial link opened successfully.")
            return 0

        def done(rc, _output):
            self.connection_ready = rc == 0
            if rc == 0:
                self.status_label.configure(text=f"READY  {port}", style="Ready.Status.TLabel")
            else:
                self.status_label.configure(text="DISCONNECTED", style="Status.TLabel")

        self._run_task("Connection Check", task, done)

    @staticmethod
    def _extract_serial(text: str) -> str:
        m = re.search(r"serial=['\\\"]?([^'\\\",) ]+)", text, flags=re.I)
        if m:
            return m.group(1)
        return text.strip()[:80] or "—"

    def _apply_device_info(self, _rc: int, output: str) -> None:
        for line in output.splitlines():
            stripped = line.strip()
            if stripped.startswith("FC device-info:"):
                self.device_vars["Drone SN"].set(self._extract_serial(stripped.split(":", 1)[1]))
            elif stripped.startswith("gimbal direct-serial:"):
                self.device_vars["Gimbal SN"].set(self._extract_serial(stripped.split(":", 1)[1]))
            elif stripped.startswith("camera sensor-id:"):
                self.device_vars["Camera SN / ID"].set(self._extract_serial(stripped.split(":", 1)[1]))
            elif stripped.startswith("formal="):
                formal = stripped.split("=", 1)[1].strip()
                self.flash_vars["Current FW"].set(formal)

            m = re.match(r"(0306|0105|0100|1100)\\s+([0-9]+(?:\\.[0-9]+)+)", stripped)
            if m:
                key = {
                    "0306": "FW FlightCtrl",
                    "0105": "FW Gimbal",
                    "0100": "FW Camera",
                    "1100": "FW Battery",
                }[m.group(1)]
                self.device_vars[key].set(m.group(2))

        self.flash_vars["Detected Model"].set(self.device_vars["Model"].get())

    def read_device_info(self) -> None:
        if not self._require_connection():
            return
        port = self._port()

        def task():
            rc1 = cal.run_identity_probe(port, 9600, 2.5, 0)
            rc2 = cal.run_service_fw_probe(port, 9600, 3.0, 0)
            rc3 = cal.run_fw_manifest_probe(port, 9600, 3.0, 0)
            return 0 if rc1 == 0 and rc2 == 0 and rc3 == 0 else max(rc1, rc2, rc3)

        self._run_task("Read Device Info", task, self._apply_device_info)

    # ---------- firmware flasher page ----------

    def choose_service_package(self) -> None:
        path = filedialog.askopenfilename(
            title="Select WM163 V30 Service Firmware",
            filetypes=[("DJI firmware", "*.bin"), ("All files", "*.*")],
        )
        if path:
            self.service_package_path.set(path)
            self.flash_vars["Selected File"].set(pathlib.Path(path).name)

    def choose_loader(self) -> None:
        path = filedialog.askopenfilename(
            title="Select session_a_loader.bin",
            filetypes=[("Binary files", "*.bin"), ("All files", "*.*")],
        )
        if path:
            self.service_loader_path.set(path)

    def _auto_find_private_service_firmware_silent(self) -> None:
        # The service package and loader are intentionally local-only. Their
        # directory is gitignored, so a clone never receives the private files.
        if self.busy:
            self.root.after(1000, self._auto_find_private_service_firmware_silent)
            return

        found = private_fw.find_private_service_inputs(
            pathlib.Path(__file__).resolve().parent
        )

        if found.package is not None:
            self.service_package_path.set(str(found.package))
            self.flash_vars["Selected File"].set(found.package.name)
        if found.loader is not None:
            self.service_loader_path.set(str(found.loader))

        if found.complete:
            self.flash_vars["Service FW"].set(
                "30.00.0100 — private local, validation pending"
            )
            self._append_log(
                f"Found local-only WM163 Service FW: {found.package}\n"
                f"Found local-only Session-A loader: {found.loader}\n"
            )
            self.validate_service_fw()
        elif found.package is not None or found.loader is not None:
            missing = []
            if found.package is None:
                missing.append(private_fw.SERVICE_PACKAGE_FILENAME)
            if found.loader is None:
                missing.append(private_fw.SESSION_A_LOADER_FILENAME)
            self._append_log(
                "Private Service FW folder is incomplete; missing: "
                + ", ".join(missing)
                + "\n"
            )
        else:
            self._append_log(
                f"No local Service FW inputs found in {found.directory}. "
                "Browse remains available.\n"
            )

    def _auto_find_production_firmware_silent(self) -> None:
        # Startup convenience: prefer the exact repo-local production archive
        # when it exists; otherwise fall back to DJI Assistant cache discovery.
        if self.busy:
            self.root.after(1000, self._auto_find_production_firmware_silent)
            return
        self.auto_find_production_firmware(silent=True)

    def auto_find_production_firmware(self, silent: bool = False) -> None:
        repo_package = production_fw.find_repo_production_archive(
            pathlib.Path(__file__).resolve().parent
        )
        if repo_package is not None:
            self.production_package_path.set(str(repo_package))
            self.flash_vars["Selected File"].set(repo_package.name)
            self.flash_vars["Production FW"].set(
                "01.00.0500 — repo archive, validation pending"
            )
            self._append_log(
                f"Found repo-local WM163 production firmware: {repo_package}\n"
            )
            self.validate_production_fw()
            return

        self.auto_find_assistant_firmware(silent=silent)

    def auto_find_assistant_firmware(self, silent: bool = False) -> None:
        def task():
            roots = assistant_cache.candidate_roots()
            print("Searching DJI Assistant firmware cache locations:")
            for root in roots:
                print(f"  {root}")
            matches = assistant_cache.find_wm163_assistant_firmware()
            self._assistant_cache_matches = matches
            if not matches:
                print("No WM163 DJI Assistant firmware cache was found.")
                print(
                    "Open DJI Assistant 2 (Consumer Drones Series), connect the Mini 3, "
                    "open Firmware Update and let it download/refresh v01.00.0500, then rescan."
                )
                return 4

            print(f"Found {len(matches)} WM163 firmware cache candidate(s):")
            for idx, item in enumerate(matches, start=1):
                print(f"  {idx}. {assistant_cache.describe_cached_firmware(item)}")
            return 0

        def done(rc, _output):
            if rc == 0 and self._assistant_cache_matches:
                best = self._assistant_cache_matches[0]
                self.production_package_path.set(str(best.display_path))
                suffix = "archive" if best.kind == "archive" else "module cache"
                completeness = "complete" if best.complete else "incomplete"
                self.flash_vars["Production FW"].set(
                    f"{best.formal or '?'} — {suffix}, {completeness}"
                )
                self._append_log(
                    f"Selected DJI Assistant WM163 production cache: {best.display_path}\n"
                )
                if best.formal != assistant_cache.PREFERRED_PRODUCTION_FORMAL and not silent:
                    messagebox.showwarning(
                        "Different WM163 firmware version",
                        f"Best WM163 cache found is {best.formal or 'unknown'}, not "
                        f"{assistant_cache.PREFERRED_PRODUCTION_FORMAL}.",
                        parent=self.root,
                    )
            elif not silent:
                messagebox.showinfo(
                    "WM163 production firmware not found",
                    "No cached WM163 firmware was found.\n\n"
                    "In DJI Assistant 2 (Consumer Drones Series), connect the Mini 3, "
                    "open Firmware Update, and let Assistant download/refresh v01.00.0500. "
                    "Then click Auto Find again.",
                    parent=self.root,
                )

        self._run_task("Auto-find DJI Assistant WM163 Firmware", task, done)

    def choose_production_package(self) -> None:
        path = filedialog.askopenfilename(
            title="Select verified WM163 v01.00.0500 Production Firmware",
            filetypes=[("DJI firmware", "*.bin"), ("All files", "*.*")],
        )
        if path:
            self.production_package_path.set(path)
            self.flash_vars["Selected File"].set(pathlib.Path(path).name)
            self.flash_vars["Production FW"].set("Selected — validation pending")

    def choose_production_cache(self) -> None:
        path = filedialog.askdirectory(
            title="Select DJI Assistant firmware/cache folder"
        )
        if not path:
            return

        root = pathlib.Path(path)

        def task():
            matches = assistant_cache.find_wm163_assistant_firmware(roots=[root])
            self._assistant_cache_matches = matches
            if not matches:
                print(f"No WM163 cfg/archive found below: {root}")
                return 4
            for idx, item in enumerate(matches, start=1):
                print(f"  {idx}. {assistant_cache.describe_cached_firmware(item)}")
            return 0

        def done(rc, _output):
            if rc == 0 and self._assistant_cache_matches:
                best = self._assistant_cache_matches[0]
                self.production_package_path.set(str(best.display_path))
                suffix = "archive" if best.kind == "archive" else "module cache"
                completeness = "complete" if best.complete else "incomplete"
                self.flash_vars["Production FW"].set(
                    f"{best.formal or '?'} — {suffix}, {completeness}"
                )
            else:
                messagebox.showwarning(
                    "No WM163 firmware found",
                    "That folder does not contain a recognizable WM163 DJI Assistant "
                    "firmware archive or signed cfg/module set.",
                    parent=self.root,
                )

        self._run_task("Inspect DJI Assistant Firmware Folder", task, done)

    def validate_production_fw(self) -> None:
        package = self.production_package_path.get().strip()

        if not package:
            self.choose_production_package()
            package = self.production_package_path.get().strip()
        if not package:
            return

        pkg_path = pathlib.Path(package)
        if not pkg_path.is_file():
            messagebox.showwarning(
                "Full production archive required",
                "Exact v01.00.0500 validation requires the full WM163 .bin archive.\n\n"
                "The selected path is a folder/module cache. Choose "
                "V01.00.0500_wm163_dji_system.bin with Browse File.",
                parent=self.root,
            )
            return

        self.flash_progress["value"] = 0
        self.flash_progress_label.configure(
            text="Validating exact WM163 v01.00.0500 production archive..."
        )

        def task():
            info = production_fw.validate_production_archive(pkg_path)
            print("WM163 v01.00.0500 Production Firmware validation: PASS")
            print(f"device={info.device}")
            print(f"formal={info.formal}")
            print(f"release={info.release}")
            print(f"size={pkg_path.stat().st_size}")
            print(f"md5={info.md5}")
            print(f"sha256={info.sha256}")
            print(
                f"antirollback={info.antirollback} "
                f"antirollback_ext={info.antirollback_ext} enforce={info.enforce}"
            )
            for mod in info.modules:
                print(f"module={mod.module_id} version={mod.version}")
            print("No serial port was opened and no firmware was written.")
            return 0

        def done(rc, output):
            if rc == 0:
                self.flash_progress["value"] = 100
                self.flash_progress_label.configure(
                    text="Production FW validation PASS. Restore remains locked."
                )
                self.flash_vars["Selected File"].set(pkg_path.name)
                self.flash_vars["Validation"].set(
                    "PASS — EXACT WM163 v01.00.0500"
                )
                self.flash_vars["Production FW"].set("01.00.0500 — exact archive")
                self.flash_vars["File Size"].set(
                    f"{pkg_path.stat().st_size:,} bytes"
                )

                md5 = re.search(r"^md5=(.+)$", output, re.M)
                sha = re.search(r"^sha256=(.+)$", output, re.M)
                if md5:
                    self.flash_vars["MD5"].set(md5.group(1).strip())
                if sha:
                    self.flash_vars["SHA256"].set(sha.group(1).strip())
            else:
                self.flash_progress["value"] = 0
                self.flash_progress_label.configure(
                    text="Production FW validation FAILED."
                )
                self.flash_vars["Validation"].set("FAILED — PRODUCTION FW")

        self._run_task("Validate Production Firmware", task, done)

    def validate_service_fw(self) -> None:
        package = self.service_package_path.get().strip()
        loader = self.service_loader_path.get().strip()

        if not package:
            self.choose_service_package()
            package = self.service_package_path.get().strip()
        if not package:
            return

        if not loader:
            self.choose_loader()
            loader = self.service_loader_path.get().strip()
        if not loader:
            return

        self.flash_progress["value"] = 0
        self.flash_progress_label.configure(text="Validating exact WM163 V30 package and loader...")

        def task():
            pkg_path = pathlib.Path(package)
            loader_path = pathlib.Path(loader)

            info = inspect_package(pkg_path, require_known_v30=True)
            loader_bytes, files = service_fw.validate_inputs(pkg_path, loader_path)

            print("WM163 V30 Service Firmware validation: PASS")
            print(f"device={getattr(info, 'device', 'wm163')}")
            print(f"formal={getattr(info, 'formal', '30.00.0100')}")
            print(f"size={pkg_path.stat().st_size}")
            print(f"md5={info.md5}")
            print(f"sha256={info.sha256}")
            print(f"Session-A loader bytes={len(loader_bytes)}")
            print(f"Session-B files={len(files)}")
            print(f"Session-B total_size={service_fw.session_b_total_size(files)}")
            print(f"B/FINALIZE seq=0x{service_fw.session_b_finalize_seq(files):04X}")
            print("No serial port was opened and no firmware was written.")
            return 0

        def done(rc, output):
            if rc == 0:
                self.flash_progress["value"] = 100
                self.flash_progress_label.configure(
                    text="Validation PASS. Live Service-FW installation remains locked."
                )
                self.flash_vars["Validation"].set("PASS — EXACT KNOWN WM163 V30")
                self.flash_vars["File Size"].set(f"{pathlib.Path(package).stat().st_size:,} bytes")

                md5 = re.search(r"^md5=(.+)$", output, re.M)
                sha = re.search(r"^sha256=(.+)$", output, re.M)
                formal = re.search(r"^formal=(.+)$", output, re.M)
                if md5:
                    self.flash_vars["MD5"].set(md5.group(1).strip())
                if sha:
                    self.flash_vars["SHA256"].set(sha.group(1).strip())
                if formal:
                    self.flash_vars["Service FW"].set(
                        f"{formal.group(1).strip()} — exact validated archive"
                    )
            else:
                self.flash_progress["value"] = 0
                self.flash_progress_label.configure(text="Validation FAILED.")
                self.flash_vars["Validation"].set("FAILED")
                self.flash_vars["Service FW"].set("30.00.0100 — INVALID")

        self._run_task("Validate Service Firmware", task, done)

    def run_live_preflight(self) -> None:
        if not self._require_connection():
            return

        port = self._port()
        self.flash_progress["value"] = 0
        self.flash_progress_label.configure(
            text="Running READ-ONLY WM163 live preflight..."
        )

        def task():
            return live_preflight.run(
                port,
                baudrate=9600,
                manifest_timeout_seconds=3.0,
                diagnostic_seconds=5.0,
                base_dir=pathlib.Path(__file__).resolve().parent,
            )

        def done(rc, _output):
            if rc == 0:
                self.flash_progress["value"] = 100
                self.flash_progress_label.configure(
                    text=(
                        "READ-ONLY preflight PASS. Service-FW flashing remains "
                        "locked pending explicit hardware-validation approval."
                    )
                )
                self.flash_vars["Validation"].set("PREFLIGHT PASS — READ ONLY")
            else:
                self.flash_progress["value"] = 0
                self.flash_progress_label.configure(
                    text=f"READ-ONLY preflight BLOCKED (rc={rc})."
                )
                self.flash_vars["Validation"].set(
                    f"PREFLIGHT BLOCKED — rc={rc}"
                )

        self._run_task("READ-ONLY Live Preflight", task, done)

    # ---------- repair actions ----------

    def basic_calibration(self) -> None:
        if not self._require_connection():
            return
        if not messagebox.askyesno(
            "Start Basic Calibration?",
            "Remove the propellers, place the aircraft on a level surface, and keep it stationary.\n\n"
            "Start normal DJI gimbal Auto Calibration?",
        ):
            return
        port = self._port()
        self._run_task(
            "Basic Calibration",
            lambda: cal.run_auto_cal_capture(port, 9600, 120.0, 0),
        )

    def advanced_calibration(self) -> None:
        if not self._require_connection():
            return
        if not messagebox.askyesno(
            "Start Advanced Calibration?",
            "This is the capture-backed two-stage WM163 service calibration used to clear 40011.\n\n"
            "SERVICE FW MUST ALREADY BE ACTIVE before running this step. "
            "Remove propellers and keep the aircraft stationary.\n\nContinue?",
        ):
            return
        port = self._port()
        self._run_task(
            "Advanced Calibration",
            lambda: cal.run_advanced_calibration(port, 9600, 120.0, 0),
        )

    def sensor_diagnostics(self) -> None:
        if not self._require_connection():
            return
        port = self._port()
        self._run_task(
            "Sensor / 40011 Diagnostics",
            lambda: cal.run_40011_probe(port, 9600, 3.0, 0),
        )

    def read_errors(self) -> None:
        if not self._require_connection():
            return
        port = self._port()
        self._run_task(
            "Read Gimbal Errors",
            lambda: cal.run_gimbal_diagnostics(port, 9600, 5.0, 0),
        )

    def fix_40021(self) -> None:
        if not self._require_connection():
            return
        if not messagebox.askyesno(
            "Run 40021 Repair?",
            "This repair writes the capture-confirmed short WM163 IMU value and then reboots the aircraft.\n\n"
            "The tool refuses the write unless diagnostic 40021 is currently active.\n\nContinue?",
        ):
            return
        port = self._port()
        self._run_task(
            "Fix Gimbal IMU Error 40021",
            lambda: cal.run_fix_imu_40021_short(port, 9600, 5.0, 2.0, 0),
        )


def main() -> int:
    root = tk.Tk()
    WM163RepairGUI(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
