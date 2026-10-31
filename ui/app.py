from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
import tkinter as tk
from collections import Counter
import hashlib
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk
from send2trash import send2trash

from core.reports import export_csv, export_txt, format_bytes
from core.scanner import CHUNK_SIZE, FileRecord, ScanResult, scan_folder


APP_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = APP_DIR / "data"
SETTINGS_FILE = DATA_DIR / "settings.json"
NAVIGATION = [
    ("⌂", "Dashboard"),
    ("⌕", "Smart Folder Scanner"),
    ("▦", "Duplicate Detection"),
    ("◴", "Storage Analyzer"),
    ("♲", "Safe Duplicate Removal"),
    ("▤", "Scan Report"),
]


class SmartDuplicateFinder(ctk.CTk):
    def __init__(self) -> None:
        DATA_DIR.mkdir(exist_ok=True)
        self.settings = self._load_settings()
        self.theme = self.settings.get("theme", "light")
        ctk.set_appearance_mode(self.theme)
        ctk.set_default_color_theme("blue")
        super().__init__()
        self.title("Smart Duplicate File Finder")
        self.geometry("1320x850")
        self.minsize(1000, 680)
        self.configure(fg_color=self._colors()["background"])

        self.active_page = "Dashboard"
        self.selected_folder = ""
        self.include_subfolders = True
        self.scan_result: ScanResult | None = None
        self.scan_active = False
        self.cancel_event: threading.Event | None = None
        self.worker: threading.Thread | None = None
        self.events: queue.Queue[tuple] = queue.Queue()
        self.selected_paths: set[Path] = set()
        self.search_var = tk.StringVar()
        self.extension_var = tk.StringVar(value="All types")
        self.group_var = tk.StringVar(value="All groups")
        self.sort_var = tk.StringVar(value="Name")
        self._progress_state = (0, 0, "")
        self._scan_started = 0.0
        self._last_scan_summary = "No scan yet"
        self._last_scan_date = "—"
        self._toast_after: str | None = None

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.sidebar = ctk.CTkFrame(self, width=252, corner_radius=0, fg_color=self._colors()["sidebar"])
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_propagate(False)
        self.content = ctk.CTkFrame(self, corner_radius=0, fg_color=self._colors()["background"])
        self.content.grid(row=0, column=1, sticky="nsew")
        self.content.grid_rowconfigure(0, weight=1)
        self.content.grid_columnconfigure(0, weight=1)
        self._build_sidebar()
        self.show_page("Dashboard")
        self.after(100, self._drain_events)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _colors(self) -> dict[str, str]:
        if getattr(self, "theme", "light") == "dark":
            return {
                "background": "#111827", "surface": "#1B2638", "sidebar": "#101827",
                "text": "#F3F6FC", "muted": "#A7B2C5", "border": "#2C3A50",
                "primary": "#6875F5", "primary_hover": "#5965E4", "teal": "#28B99A",
                "warning": "#E8A93B", "danger": "#EB6673", "selected": "#283B68",
            }
        return {
            "background": "#F4F6FB", "surface": "#FFFFFF", "sidebar": "#17233B",
            "text": "#202B3C", "muted": "#738095", "border": "#E4E9F1",
            "primary": "#5967E8", "primary_hover": "#4857D9", "teal": "#159B81",
            "warning": "#C78619", "danger": "#D84E5B", "selected": "#293B5E",
        }

    def _load_settings(self) -> dict:
        try:
            if SETTINGS_FILE.exists():
                value = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
                if isinstance(value, dict):
                    return value
        except (OSError, json.JSONDecodeError):
            messagebox.showwarning("Settings", "Settings could not be read. Default settings will be used.")
        return {"theme": "light"}

    def _save_settings(self) -> None:
        try:
            SETTINGS_FILE.write_text(json.dumps(self.settings, indent=2), encoding="utf-8")
        except OSError as error:
            messagebox.showerror("Settings", f"Could not save settings:\n{error}")

    def _build_sidebar(self) -> None:
        c = self._colors()
        for child in self.sidebar.winfo_children():
            child.destroy()
        brand = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        brand.pack(fill="x", padx=20, pady=(27, 24))
        ctk.CTkLabel(brand, text="◈", font=ctk.CTkFont(size=29, weight="bold"),
                     text_color="#8D9BFF").pack(side="left", padx=(0, 11))
        brand_text = ctk.CTkFrame(brand, fg_color="transparent")
        brand_text.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(brand_text, text="Smart Duplicate\nFile Finder",
                     font=ctk.CTkFont(size=15, weight="bold"), text_color="#FFFFFF",
                     justify="left").pack(anchor="w")
        ctk.CTkLabel(brand_text, text="Clean. Organize. Optimize.",
                     font=ctk.CTkFont(size=10), text_color="#ADB8CD").pack(anchor="w", pady=(3, 0))
        ctk.CTkLabel(self.sidebar, text="WORKSPACE", font=ctk.CTkFont(size=10, weight="bold"),
                     text_color="#8290A8").pack(anchor="w", padx=22, pady=(0, 9))
        self.nav_buttons: dict[str, ctk.CTkButton] = {}
        for icon, page in NAVIGATION:
            button = ctk.CTkButton(
                self.sidebar, text=f"  {icon}    {page}", anchor="w", height=43,
                corner_radius=9, font=ctk.CTkFont(size=13, weight="bold" if page == self.active_page else "normal"),
                fg_color=c["selected"] if page == self.active_page else "transparent",
                hover_color="#2A3A56", text_color="#FFFFFF", command=lambda name=page: self.show_page(name),
            )
            button.pack(fill="x", padx=13, pady=3)
            self.nav_buttons[page] = button
        spacer = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        spacer.pack(fill="both", expand=True)
        ctk.CTkButton(
            self.sidebar, text=f"⚙    Settings", anchor="w", height=40, corner_radius=9,
            fg_color="transparent", hover_color="#2A3A56", text_color="#D9E1F0",
            command=self._open_settings,
        ).pack(fill="x", padx=13, pady=(0, 3))
        ctk.CTkButton(
            self.sidebar, text=f"{'☀' if self.theme == 'dark' else '☾'}    Switch to {'light' if self.theme == 'dark' else 'dark'} mode",
            anchor="w", height=40, corner_radius=9, fg_color="transparent", hover_color="#2A3A56",
            text_color="#D9E1F0", command=self._toggle_theme,
        ).pack(fill="x", padx=13, pady=(0, 14))
        ctk.CTkLabel(self.sidebar, text="VERSION 1.0.0", font=ctk.CTkFont(size=10, weight="bold"),
                     text_color="#8290A8").pack(anchor="w", padx=23, pady=(0, 20))

    def _open_settings(self) -> None:
        messagebox.showinfo(
            "Settings",
            f"Theme: {self.theme.title()}\nSettings are saved automatically to:\n{SETTINGS_FILE}",
        )

    def _toggle_theme(self) -> None:
        self.theme = "dark" if self.theme == "light" else "light"
        self.settings["theme"] = self.theme
        self._save_settings()
        ctk.set_appearance_mode(self.theme)
        self.configure(fg_color=self._colors()["background"])
        self._build_sidebar()
        self.show_page(self.active_page)

    def show_page(self, page: str) -> None:
        self.active_page = page
        c = self._colors()
        for name, button in self.nav_buttons.items():
            button.configure(
                fg_color=c["selected"] if name == page else "transparent",
                font=ctk.CTkFont(size=13, weight="bold" if name == page else "normal"),
            )
        for child in self.content.winfo_children():
            child.destroy()
        canvas = ctk.CTkScrollableFrame(self.content, fg_color="transparent", corner_radius=0)
        canvas.grid(row=0, column=0, sticky="nsew", padx=30, pady=24)
        canvas.grid_columnconfigure(0, weight=1)
        builders = {
            "Dashboard": self._page_dashboard,
            "Smart Folder Scanner": self._page_scanner,
            "Duplicate Detection": self._page_duplicates,
            "Storage Analyzer": self._page_storage,
            "Safe Duplicate Removal": self._page_removal,
            "Scan Report": self._page_report,
        }
        builders[page](canvas)

    def _header(self, parent, title: str, subtitle: str, action: tuple[str, callable] | None = None) -> None:
        c = self._colors()
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.grid(row=0, column=0, sticky="ew", pady=(0, 22))
        row.grid_columnconfigure(0, weight=1)
        text = ctk.CTkFrame(row, fg_color="transparent")
        text.grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(text, text=title, font=ctk.CTkFont(size=28, weight="bold"),
                     text_color=c["text"]).pack(anchor="w")
        ctk.CTkLabel(text, text=subtitle, font=ctk.CTkFont(size=13),
                     text_color=c["muted"]).pack(anchor="w", pady=(5, 0))
        if action:
            ctk.CTkButton(row, text=action[0], command=action[1], height=40,
                          corner_radius=9, fg_color=c["primary"], hover_color=c["primary_hover"],
                          font=ctk.CTkFont(size=13, weight="bold")).grid(row=0, column=1, sticky="e", padx=(18, 0))

    def _card(self, parent, title: str, value: str, description: str, icon: str, column: int) -> None:
        c = self._colors()
        card = ctk.CTkFrame(parent, fg_color=c["surface"], border_color=c["border"],
                            border_width=1, corner_radius=14)
        card.grid(row=0, column=column, sticky="ew", padx=(0 if column == 0 else 8, 8), pady=2)
        card.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(card, text=f"{icon}   {title}", text_color=c["muted"],
                     font=ctk.CTkFont(size=12, weight="bold")).grid(row=0, column=0, sticky="w", padx=17, pady=(17, 7))
        ctk.CTkLabel(card, text=value, text_color=c["text"],
                     font=ctk.CTkFont(size=27, weight="bold")).grid(row=1, column=0, sticky="w", padx=17)
        ctk.CTkLabel(card, text=description, text_color=c["muted"],
                     font=ctk.CTkFont(size=11)).grid(row=2, column=0, sticky="w", padx=17, pady=(3, 16))

    def _summary(self) -> tuple[str, str, str, str]:
        result = self.scan_result
        if not result:
            return "0", "0", "0", "No scan data yet"
        return (
            f"{result.files_scanned:,}",
            f"{len(result.duplicate_groups):,}",
            f"{result.extra_copies:,}",
            format_bytes(result.savings_bytes),
        )

    def _page_dashboard(self, parent) -> None:
        self._header(parent, "Welcome back", "Find duplicate files and reclaim storage — safely.",
                     ("Start New Scan", lambda: self.show_page("Smart Folder Scanner")))
        c = self._colors()
        status = "Scan in progress" if self.scan_active else ("Scan complete" if self.scan_result else "Ready when you are")
        status_panel = ctk.CTkFrame(parent, fg_color=c["surface"], border_color=c["border"], border_width=1, corner_radius=14)
        status_panel.grid(row=1, column=0, sticky="ew", pady=(0, 18))
        ctk.CTkLabel(status_panel, text="●", text_color=c["teal"] if not self.scan_active else c["warning"],
                     font=ctk.CTkFont(size=14)).pack(side="left", padx=(18, 8), pady=14)
        ctk.CTkLabel(status_panel, text=status, text_color=c["text"],
                     font=ctk.CTkFont(size=13, weight="bold")).pack(side="left", pady=14)
        ctk.CTkLabel(status_panel, text=self._last_scan_summary, text_color=c["muted"],
                     font=ctk.CTkFont(size=12)).pack(side="right", padx=18, pady=14)
        values = self._summary()
        cards = ctk.CTkFrame(parent, fg_color="transparent")
        cards.grid(row=2, column=0, sticky="ew", pady=(0, 20))
        for index in range(4):
            cards.grid_columnconfigure(index, weight=1, uniform="cards")
        self._card(cards, "Files Scanned", values[0], "Files inspected in selected folder", "▤", 0)
        self._card(cards, "Duplicate Groups", values[1], "Sets of byte-identical files", "⧉", 1)
        self._card(cards, "Extra Copies", values[2], "Copies beyond one retained file", "↗", 2)
        self._card(cards, "Potential Savings", values[3], "Estimated removable duplicate space", "◴", 3)
        panel = ctk.CTkFrame(parent, fg_color=c["surface"], border_color=c["border"], border_width=1, corner_radius=14)
        panel.grid(row=3, column=0, sticky="ew")
        ctk.CTkLabel(panel, text="Recent scan", font=ctk.CTkFont(size=17, weight="bold"),
                     text_color=c["text"]).pack(anchor="w", padx=20, pady=(18, 10))
        if not self.scan_result:
            ctk.CTkLabel(panel, text="⌕", font=ctk.CTkFont(size=38), text_color=c["primary"]).pack(pady=(15, 5))
            ctk.CTkLabel(panel, text="No scan yet. Choose a folder to discover duplicate files.",
                         font=ctk.CTkFont(size=13), text_color=c["muted"]).pack(pady=(0, 8))
            ctk.CTkButton(panel, text="Choose a folder", command=lambda: self.show_page("Smart Folder Scanner"),
                          fg_color=c["primary"], hover_color=c["primary_hover"], height=38,
                          corner_radius=9).pack(pady=(0, 18))
        else:
            r = self.scan_result
            self._detail_row(panel, "Folder", str(r.root))
            self._detail_row(panel, "Scan date", self._last_scan_date)
            self._detail_row(panel, "Files scanned", f"{r.files_scanned:,}")
            self._detail_row(panel, "Duplicates found", f"{len(r.duplicate_groups)} groups · {r.extra_copies} extra copies")
            self._detail_row(panel, "Potential savings", format_bytes(r.savings_bytes), bottom=True)
        if self.scan_result and self.scan_result.errors:
            ctk.CTkLabel(parent, text=f"Scan completed with {len(self.scan_result.errors)} warning(s). See Scan Report.",
                         text_color=c["warning"], font=ctk.CTkFont(size=12)).grid(row=4, column=0, sticky="w", pady=12)

    def _detail_row(self, parent, label: str, value: str, bottom: bool = False) -> None:
        c = self._colors()
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=20, pady=(0, 14 if bottom else 7))
        ctk.CTkLabel(row, text=label, text_color=c["muted"], width=130, anchor="w",
                     font=ctk.CTkFont(size=12)).pack(side="left")
        ctk.CTkLabel(row, text=value, text_color=c["text"], anchor="w",
                     font=ctk.CTkFont(size=12), wraplength=800).pack(side="left", fill="x", expand=True)

    def _page_scanner(self, parent) -> None:
        self._header(parent, "Smart Folder Scanner", "Choose a folder and scan its files for exact content duplicates.")
        c = self._colors()
        box = ctk.CTkFrame(parent, fg_color=c["surface"], border_color=c["border"], border_width=1, corner_radius=16)
        box.grid(row=1, column=0, sticky="ew")
        ctk.CTkLabel(box, text="▱", font=ctk.CTkFont(size=42), text_color=c["primary"]).pack(pady=(25, 4))
        ctk.CTkLabel(box, text="Choose a folder to scan", font=ctk.CTkFont(size=19, weight="bold"),
                     text_color=c["text"]).pack()
        ctk.CTkLabel(box, text="The scan reads files in the background. Symbolic links are skipped.",
                     font=ctk.CTkFont(size=12), text_color=c["muted"]).pack(pady=(5, 14))
        ctk.CTkButton(box, text="Browse Folder", command=self._browse_folder, height=39, corner_radius=9,
                      fg_color=c["primary"], hover_color=c["primary_hover"]).pack()
        self.folder_label = ctk.CTkLabel(box, text=self.selected_folder or "No folder selected",
                                          text_color=c["text"] if self.selected_folder else c["muted"],
                                          font=ctk.CTkFont(size=12), wraplength=750)
        self.folder_label.pack(pady=(14, 14))
        self.recursive_var = tk.BooleanVar(value=self.include_subfolders)
        ctk.CTkCheckBox(box, text="Include subfolders", variable=self.recursive_var,
                        text_color=c["text"], fg_color=c["primary"], hover_color=c["primary_hover"],
                        command=self._update_recursive).pack(pady=(0, 22))
        controls = ctk.CTkFrame(parent, fg_color="transparent")
        controls.grid(row=2, column=0, sticky="ew", pady=17)
        self.start_button = ctk.CTkButton(controls, text="Start Scan", command=self._start_scan, width=135,
                                          height=40, corner_radius=9, fg_color=c["primary"],
                                          hover_color=c["primary_hover"])
        self.start_button.pack(side="left")
        self.cancel_button = ctk.CTkButton(controls, text="Cancel Scan", command=self._cancel_scan,
                                           width=120, height=40, corner_radius=9, state="disabled",
                                           fg_color=c["danger"], hover_color="#C94755")
        self.cancel_button.pack(side="left", padx=9)
        self.clear_button = ctk.CTkButton(controls, text="Clear Selection", command=self._clear_selection,
                                          width=130, height=40, corner_radius=9, fg_color=c["surface"],
                                          hover_color=c["border"], text_color=c["text"], border_color=c["border"],
                                          border_width=1)
        self.clear_button.pack(side="left")
        self.scan_status = ctk.CTkLabel(parent, text="Select a folder to get started.", text_color=c["muted"])
        self.scan_status.grid(row=3, column=0, sticky="w")
        self.progress = ctk.CTkProgressBar(parent, height=10, progress_color=c["primary"])
        self.progress.grid(row=4, column=0, sticky="ew", pady=(9, 6))
        self.progress.set(0)
        self.progress_details = ctk.CTkLabel(parent, text="", text_color=c["muted"], font=ctk.CTkFont(size=11))
        self.progress_details.grid(row=5, column=0, sticky="w")
        if self.scan_active:
            self._set_scanning_controls(True)

    def _browse_folder(self) -> None:
        folder = filedialog.askdirectory(title="Choose folder to scan", mustexist=True)
        if folder:
            self.selected_folder = folder
            if hasattr(self, "folder_label") and self.folder_label.winfo_exists():
                self.folder_label.configure(text=folder, text_color=self._colors()["text"])

    def _update_recursive(self) -> None:
        self.include_subfolders = bool(self.recursive_var.get())

    def _clear_selection(self) -> None:
        if self.scan_active:
            return
        self.selected_folder = ""
        if hasattr(self, "folder_label") and self.folder_label.winfo_exists():
            self.folder_label.configure(text="No folder selected", text_color=self._colors()["muted"])

    def _start_scan(self) -> None:
        if self.scan_active:
            return
        if not self.selected_folder:
            messagebox.showinfo("Select a folder", "Browse to choose a folder before starting a scan.")
            return
        self.scan_active = True
        self.cancel_event = threading.Event()
        self._scan_started = time.monotonic()
        self._set_scanning_controls(True)
        self.progress.set(0)
        self.scan_status.configure(text="Preparing scan…", text_color=self._colors()["text"])
        folder, recursive, cancel_event = self.selected_folder, self.include_subfolders, self.cancel_event

        def report(processed: int, total: int, path: str) -> None:
            self.events.put(("progress", processed, total, path))

        def work() -> None:
            try:
                result = scan_folder(folder, recursive, cancel_event, report)
                self.events.put(("done", result, cancel_event.is_set()))
            except (OSError, RuntimeError) as error:
                self.events.put(("error", error))

        self.worker = threading.Thread(target=work, name="duplicate-scan", daemon=True)
        self.worker.start()

    def _set_scanning_controls(self, active: bool) -> None:
        if hasattr(self, "start_button") and self.start_button.winfo_exists():
            self.start_button.configure(state="disabled" if active else "normal")
            self.cancel_button.configure(state="normal" if active else "disabled")
            self.clear_button.configure(state="disabled" if active else "normal")

    def _cancel_scan(self) -> None:
        if self.scan_active and self.cancel_event:
            self.cancel_event.set()
            self.cancel_button.configure(state="disabled")
            if hasattr(self, "scan_status") and self.scan_status.winfo_exists():
                self.scan_status.configure(text="Cancelling safely…")

    def _drain_events(self) -> None:
        try:
            while True:
                event = self.events.get_nowait()
                if event[0] == "progress":
                    _, processed, total, path = event
                    self._progress_state = (processed, total, path)
                    self._update_progress_ui()
                elif event[0] == "done":
                    _, result, cancelled = event
                    self.scan_result = result
                    self.selected_paths.clear()
                    self.group_var.set("All groups")
                    self.extension_var.set("All types")
                    self.search_var.set("")
                    self.scan_active = False
                    self._last_scan_date = datetime.now().astimezone().strftime("%b %d, %Y %H:%M")
                    self._last_scan_summary = f"{result.root} · {self._last_scan_date}"
                    self._set_scanning_controls(False)
                    if hasattr(self, "scan_status") and self.scan_status.winfo_exists():
                        state = "Scan cancelled" if cancelled else "Scan complete"
                        self.scan_status.configure(text=f"{state} · {result.files_scanned:,} files scanned")
                    if hasattr(self, "progress") and self.progress.winfo_exists():
                        self.progress.set(1 if not cancelled else 0)
                    if self.active_page != "Smart Folder Scanner":
                        self.show_page(self.active_page)
                    self._notify("Scan cancelled." if cancelled else f"Scan complete — {len(result.duplicate_groups)} duplicate groups found.")
                elif event[0] == "error":
                    self.scan_active = False
                    self._set_scanning_controls(False)
                    messagebox.showerror("Scan failed", str(event[1]))
        except queue.Empty:
            pass
        if self.winfo_exists():
            self.after(100, self._drain_events)

    def _update_progress_ui(self) -> None:
        processed, total, path = self._progress_state
        fraction = processed / total if total else 0
        elapsed = max(0, int(time.monotonic() - self._scan_started))
        if hasattr(self, "progress") and self.progress.winfo_exists():
            self.progress.set(fraction)
            self.scan_status.configure(text=f"Hashing files · {processed:,} of {total:,}")
            self.progress_details.configure(
                text=f"{fraction:.0%} complete · {elapsed // 60:02d}:{elapsed % 60:02d} elapsed · {Path(path).name}"
            )

    def _notify(self, text: str) -> None:
        if not self.winfo_exists():
            return
        if hasattr(self, "_toast") and self._toast.winfo_exists():
            self._toast.destroy()
        self._toast = ctk.CTkLabel(self, text=text, fg_color=self._colors()["selected"],
                                   text_color="#FFFFFF", corner_radius=9, padx=16, pady=10,
                                   font=ctk.CTkFont(size=12, weight="bold"))
        self._toast.place(relx=0.98, rely=0.96, anchor="se")
        self.after(3500, self._dismiss_toast)

    def _dismiss_toast(self) -> None:
        if hasattr(self, "_toast") and self._toast.winfo_exists():
            self._toast.destroy()

    def _page_duplicates(self, parent) -> None:
        self._header(parent, "Duplicate Detection", "Review exact matches, search results, and choose what to keep.",
                     ("Select extra copies", self._select_extra_copies))
        c = self._colors()
        result = self.scan_result
        if not result:
            self._empty_state(parent, "No scan results yet", "Run a folder scan to see duplicate groups here.",
                              lambda: self.show_page("Smart Folder Scanner"))
            return
        if not result.duplicate_groups:
            self._empty_state(parent, "No duplicates found", "This folder has no byte-identical duplicate files.",
                              lambda: self.show_page("Smart Folder Scanner"))
            return
        strip = ctk.CTkFrame(parent, fg_color=c["surface"], border_color=c["border"], border_width=1, corner_radius=12)
        strip.grid(row=1, column=0, sticky="ew", pady=(0, 14))
        for i, (label, value) in enumerate((
            ("Duplicate groups", str(len(result.duplicate_groups))),
            ("Extra copies", str(result.extra_copies)),
            ("Potential savings", format_bytes(result.savings_bytes)),
        )):
            strip.grid_columnconfigure(i, weight=1)
            ctk.CTkLabel(strip, text=f"{label.upper()}   {value}", text_color=c["text"],
                         font=ctk.CTkFont(size=12, weight="bold")).grid(row=0, column=i, padx=12, pady=14)
        controls = ctk.CTkFrame(parent, fg_color="transparent")
        controls.grid(row=2, column=0, sticky="ew", pady=(0, 12))
        controls.grid_columnconfigure(0, weight=1)
        search = ctk.CTkEntry(controls, textvariable=self.search_var, placeholder_text="Search file name…",
                              height=38, corner_radius=9)
        search.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        search.bind("<KeyRelease>", lambda _event: self._render_results())
        extensions = sorted({record.extension for group in result.duplicate_groups for record in group}, key=str.casefold)
        ctk.CTkOptionMenu(controls, variable=self.extension_var, values=["All types", *extensions],
                          command=lambda _value: self._render_results(), height=38, corner_radius=9).grid(row=0, column=1, padx=4)
        ctk.CTkOptionMenu(controls, variable=self.group_var,
                          values=["All groups", *[f"Group {number}" for number in range(1, len(result.duplicate_groups) + 1)]],
                          command=lambda _value: self._render_results(), height=38, corner_radius=9).grid(row=0, column=2, padx=4)
        ctk.CTkOptionMenu(controls, variable=self.sort_var, values=["Name", "Size (largest first)"],
                          command=lambda _value: self._render_results(), height=38, corner_radius=9).grid(row=0, column=3, padx=4)
        ctk.CTkButton(controls, text="Refresh", command=self._render_results, width=90, height=38,
                      corner_radius=9, fg_color=c["surface"], text_color=c["text"],
                      border_color=c["border"], border_width=1, hover_color=c["border"]).grid(row=0, column=4, padx=(4, 0))
        self.results_frame = ctk.CTkFrame(parent, fg_color=c["surface"], border_color=c["border"], border_width=1, corner_radius=12)
        self.results_frame.grid(row=3, column=0, sticky="ew")
        self._render_results()

    def _filtered_records(self) -> list[tuple[int, FileRecord, bool]]:
        if not self.scan_result:
            return []
        query = self.search_var.get().strip().casefold()
        extension = self.extension_var.get()
        rows: list[tuple[int, FileRecord, bool]] = []
        for group_number, group in enumerate(self.scan_result.duplicate_groups, start=1):
            for index, record in enumerate(group):
                if query and query not in record.name.casefold():
                    continue
                if extension != "All types" and record.extension != extension:
                    continue
                if self.group_var.get() != "All groups" and self.group_var.get() != f"Group {group_number}":
                    continue
                rows.append((group_number, record, index == 0))
        if self.sort_var.get() == "Size (largest first)":
            rows.sort(key=lambda item: (-item[1].size, item[1].name.casefold()))
        else:
            rows.sort(key=lambda item: (item[0], item[1].name.casefold()))
        return rows

    def _render_results(self, *_args) -> None:
        if not hasattr(self, "results_frame") or not self.results_frame.winfo_exists():
            return
        c = self._colors()
        for child in self.results_frame.winfo_children():
            child.destroy()
        header = ctk.CTkFrame(self.results_frame, fg_color=c["background"], corner_radius=7)
        header.pack(fill="x", padx=8, pady=(8, 4))
        for text, width in (("Select", 62), ("File name", 185), ("Type", 115), ("Size", 92), ("Group", 68), ("File location", 1)):
            ctk.CTkLabel(header, text=text, text_color=c["muted"], width=width if width > 1 else 0,
                         anchor="w", font=ctk.CTkFont(size=11, weight="bold")).pack(side="left", padx=5, pady=8,
                                                                                   fill="x" if width == 1 else "none", expand=width == 1)
        rows = self._filtered_records()
        scroll = ctk.CTkScrollableFrame(self.results_frame, height=390, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        if not rows:
            ctk.CTkLabel(scroll, text="No matching duplicate files.", text_color=c["muted"]).pack(pady=25)
            return
        for group_no, record, retained in rows:
            row = ctk.CTkFrame(scroll, fg_color="transparent", border_color=c["border"], border_width=1, corner_radius=7)
            row.pack(fill="x", pady=3)
            variable = tk.BooleanVar(value=record.path in self.selected_paths)
            ctk.CTkCheckBox(row, text="", variable=variable, width=62, checkbox_width=17, checkbox_height=17,
                            fg_color=c["primary"], command=lambda path=record.path, var=variable: self._toggle_selected(path, var)).pack(side="left", padx=9)
            ctk.CTkLabel(row, text=record.name, width=185, anchor="w", text_color=c["text"],
                         font=ctk.CTkFont(size=11), wraplength=170).pack(side="left", padx=5, pady=9)
            ctk.CTkLabel(row, text=record.extension, width=115, anchor="w", text_color=c["muted"],
                         font=ctk.CTkFont(size=11)).pack(side="left", padx=5)
            ctk.CTkLabel(row, text=format_bytes(record.size), width=92, anchor="w", text_color=c["text"],
                         font=ctk.CTkFont(size=11)).pack(side="left", padx=5)
            ctk.CTkLabel(row, text=f"#{group_no}" + (" · keep" if retained else ""),
                         width=68, anchor="w", text_color=c["teal"] if retained else c["muted"],
                         font=ctk.CTkFont(size=10, weight="bold" if retained else "normal")).pack(side="left", padx=5)
            path_label = ctk.CTkLabel(row, text=str(record.path.parent), anchor="w", text_color=c["muted"],
                                      font=ctk.CTkFont(size=10), cursor="hand2")
            path_label.pack(side="left", fill="x", expand=True, padx=5)
            path_label.bind("<Double-Button-1>", lambda _e, path=record.path.parent: self._open_location(path))
            path_label.bind("<Enter>", lambda _e, label=path_label: label.configure(text_color=c["primary"]))
            path_label.bind("<Leave>", lambda _e, label=path_label: label.configure(text_color=c["muted"]))

    def _toggle_selected(self, path: Path, variable: tk.BooleanVar) -> None:
        if variable.get():
            self.selected_paths.add(path)
        else:
            self.selected_paths.discard(path)

    def _select_extra_copies(self) -> None:
        if not self.scan_result:
            return
        extras = {record.path for group in self.scan_result.duplicate_groups for record in group[1:]}
        self.selected_paths = extras
        self._render_results()
        self._notify(f"Selected {len(extras)} extra copies; one copy per group is retained.")

    def _page_storage(self, parent) -> None:
        self._header(parent, "Storage Analyzer", "Understand duplicate storage and the safely reclaimable portion.")
        result = self.scan_result
        if not result:
            self._empty_state(parent, "Storage insights appear after a scan", "Scan a folder to calculate duplicate storage.",
                              lambda: self.show_page("Smart Folder Scanner"))
            return
        c = self._colors()
        cards = ctk.CTkFrame(parent, fg_color="transparent")
        cards.grid(row=1, column=0, sticky="ew", pady=(0, 18))
        for i in range(3):
            cards.grid_columnconfigure(i, weight=1, uniform="storage")
        self._card(cards, "Duplicate Groups", str(len(result.duplicate_groups)), "Unique content groups", "⧉", 0)
        self._card(cards, "All Duplicate Data", format_bytes(sum(len(g) * g[0].size for g in result.duplicate_groups)),
                   "Includes the retained copies", "▤", 1)
        self._card(cards, "Extra-Copy Savings", format_bytes(result.savings_bytes),
                   "Only copies beyond one per group", "◴", 2)
        box = ctk.CTkFrame(parent, fg_color=c["surface"], border_color=c["border"], border_width=1, corner_radius=13)
        box.grid(row=2, column=0, sticky="ew", pady=(0, 16))
        ctk.CTkLabel(box, text="Largest duplicate groups", text_color=c["text"],
                     font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w", padx=18, pady=(16, 10))
        largest = sorted(enumerate(result.duplicate_groups, start=1),
                         key=lambda item: (len(item[1]) - 1) * item[1][0].size, reverse=True)[:8]
        if not largest:
            ctk.CTkLabel(box, text="No duplicate groups were found.", text_color=c["muted"]).pack(anchor="w", padx=18, pady=15)
        for index, group in largest:
            savings = (len(group) - 1) * group[0].size
            row = ctk.CTkFrame(box, fg_color="transparent")
            row.pack(fill="x", padx=18, pady=5)
            ctk.CTkLabel(row, text=f"Group {index} · {len(group)} files", text_color=c["text"],
                         font=ctk.CTkFont(size=12)).pack(side="left")
            ctk.CTkLabel(row, text=f"{format_bytes(savings)} reclaimable", text_color=c["teal"],
                         font=ctk.CTkFont(size=12, weight="bold")).pack(side="right")
            bar = ctk.CTkProgressBar(box, height=7, progress_color=c["primary"])
            bar.pack(fill="x", padx=18, pady=(0, 7))
            max_saving = max((len(g) - 1) * g[0].size for g in result.duplicate_groups) or 1
            bar.set(savings / max_saving)
        types: Counter[str] = Counter()
        for group in result.duplicate_groups:
            types[group[0].extension] += (len(group) - 1) * group[0].size
        if types:
            type_box = ctk.CTkFrame(parent, fg_color=c["surface"], border_color=c["border"], border_width=1, corner_radius=13)
            type_box.grid(row=3, column=0, sticky="ew")
            ctk.CTkLabel(type_box, text="Reclaimable by file type", text_color=c["text"],
                         font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w", padx=18, pady=(16, 8))
            for extension, size in types.most_common():
                self._detail_row(type_box, extension, format_bytes(size))

    def _page_removal(self, parent) -> None:
        self._header(parent, "Safe Duplicate Removal", "Review selected extra copies. Files are sent to the Recycle Bin, never permanently deleted.")
        c = self._colors()
        if not self.scan_result:
            self._empty_state(parent, "No files selected", "Scan a folder, then select duplicate copies for safe removal.",
                              lambda: self.show_page("Smart Folder Scanner"))
            return
        safe_extras = {record.path: record for group in self.scan_result.duplicate_groups for record in group[1:]}
        selected = [(path, safe_extras[path]) for path in self.selected_paths if path in safe_extras]
        total = sum(record.size for _, record in selected)
        panel = ctk.CTkFrame(parent, fg_color=c["surface"], border_color=c["border"], border_width=1, corner_radius=13)
        panel.grid(row=1, column=0, sticky="ew")
        ctk.CTkLabel(panel, text=f"{len(selected)} extra copies selected",
                     text_color=c["text"], font=ctk.CTkFont(size=18, weight="bold")).pack(anchor="w", padx=18, pady=(17, 5))
        ctk.CTkLabel(panel, text=f"Estimated reclaimable space: {format_bytes(total)}",
                     text_color=c["teal"], font=ctk.CTkFont(size=13, weight="bold")).pack(anchor="w", padx=18, pady=(0, 12))
        listing = ctk.CTkScrollableFrame(panel, height=300, fg_color="transparent")
        listing.pack(fill="x", padx=10, pady=(0, 10))
        if not selected:
            ctk.CTkLabel(listing, text="Nothing selected. Use Select extra copies on Duplicate Detection, or check individual files.",
                         text_color=c["muted"], wraplength=750).pack(pady=25)
        for path, record in selected:
            row = ctk.CTkFrame(listing, fg_color="transparent", border_color=c["border"], border_width=1, corner_radius=7)
            row.pack(fill="x", pady=3)
            ctk.CTkLabel(row, text=f"{record.name}\n{path}", text_color=c["text"], anchor="w",
                         justify="left", wraplength=760, font=ctk.CTkFont(size=11)).pack(side="left", fill="x", expand=True, padx=12, pady=8)
            ctk.CTkLabel(row, text=format_bytes(record.size), text_color=c["muted"],
                         font=ctk.CTkFont(size=11)).pack(side="right", padx=12)
        buttons = ctk.CTkFrame(parent, fg_color="transparent")
        buttons.grid(row=2, column=0, sticky="ew", pady=14)
        ctk.CTkButton(buttons, text="Review duplicates", command=lambda: self.show_page("Duplicate Detection"),
                      height=40, corner_radius=9, fg_color=c["surface"], text_color=c["text"],
                      border_color=c["border"], border_width=1, hover_color=c["border"]).pack(side="left")
        ctk.CTkButton(buttons, text="Move selected to Recycle Bin", command=self._confirm_removal,
                      height=40, corner_radius=9, fg_color=c["danger"], hover_color="#C94755",
                      state="normal" if selected else "disabled").pack(side="left", padx=9)
        ctk.CTkLabel(parent, text="The first file in each identical group is retained. Before moving, every selected file is revalidated.",
                     text_color=c["muted"], font=ctk.CTkFont(size=11)).grid(row=3, column=0, sticky="w")

    def _confirm_removal(self) -> None:
        if not self.scan_result:
            return
        groups = self.scan_result.duplicate_groups
        extras = {record.path: record for group in groups for record in group[1:]}
        selected = [(path, extras[path]) for path in self.selected_paths if path in extras]
        if not selected:
            return
        amount = sum(record.size for _, record in selected)
        message = (
            f"Move {len(selected)} selected file(s) to the Recycle Bin?\n"
            f"Estimated space to reclaim: {format_bytes(amount)}\n\n"
            "One copy from each duplicate group will be retained. This action is not permanent deletion."
        )
        if not messagebox.askyesno("Confirm safe removal", message, icon="warning"):
            return

        moved: set[Path] = set()
        failed: list[str] = []
        for path, record in selected:
            try:
                if not path.is_file() or path.is_symlink():
                    raise OSError("File no longer qualifies as a safe duplicate.")
                stat = path.stat(follow_symlinks=False)
                if stat.st_size != record.size:
                    raise OSError("File size changed since the scan.")
                if self._hash_file(path) != record.digest:
                    raise OSError("File content changed since the scan.")
                group = next(
                    (items for items in groups if any(item.path == path and item.digest == record.digest for item in items)),
                    None,
                )
                if group is None:
                    raise OSError("No retained duplicate copy can be verified.")
                retained_verified = False
                for other in group:
                    if other.path == path:
                        continue
                    try:
                        if (
                            other.path.is_file()
                            and not other.path.is_symlink()
                            and other.path.stat(follow_symlinks=False).st_size == other.size
                            and self._hash_file(other.path) == record.digest
                        ):
                            retained_verified = True
                            break
                    except OSError:
                        continue
                if not retained_verified:
                    raise OSError("No remaining identical copy could be verified.")
                send2trash(str(path))
                moved.add(path)
            except OSError as error:
                failed.append(f"{path}: {error}")
        self.selected_paths.difference_update(moved)
        if moved:
            self._notify(f"Moved {len(moved)} file(s) to the Recycle Bin.")
        if failed:
            messagebox.showwarning("Some files could not be moved", "\n".join(failed[:10]))
        # Keep the original scan snapshot for reports; selected removal paths are
        # passed to report export to show which files were successfully moved.
        self._removal_history = getattr(self, "_removal_history", set()) | moved
        self.show_page("Safe Duplicate Removal")

    @staticmethod
    def _hash_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(CHUNK_SIZE), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _page_report(self, parent) -> None:
        self._header(parent, "Scan Report", "Review scan details and export a shareable CSV or plain-text report.")
        result = self.scan_result
        c = self._colors()
        if not result:
            self._empty_state(parent, "Your report will appear here", "Complete a scan to create a detailed report.",
                              lambda: self.show_page("Smart Folder Scanner"))
            return
        summary = ctk.CTkFrame(parent, fg_color=c["surface"], border_color=c["border"], border_width=1, corner_radius=13)
        summary.grid(row=1, column=0, sticky="ew")
        ctk.CTkLabel(summary, text="Latest scan summary", text_color=c["text"],
                     font=ctk.CTkFont(size=17, weight="bold")).pack(anchor="w", padx=18, pady=(17, 10))
        self._detail_row(summary, "Scan date", self._last_scan_date)
        self._detail_row(summary, "Selected folder", str(result.root))
        self._detail_row(summary, "Total files scanned", f"{result.files_scanned:,}")
        self._detail_row(summary, "Duplicate groups", str(len(result.duplicate_groups)))
        self._detail_row(summary, "Extra copies", str(result.extra_copies))
        self._detail_row(summary, "Potential savings", format_bytes(result.savings_bytes), bottom=True)
        buttons = ctk.CTkFrame(parent, fg_color="transparent")
        buttons.grid(row=2, column=0, sticky="w", pady=16)
        ctk.CTkButton(buttons, text="Export CSV", command=lambda: self._export_report("csv"),
                      height=40, corner_radius=9, fg_color=c["primary"], hover_color=c["primary_hover"]).pack(side="left")
        ctk.CTkButton(buttons, text="Export TXT", command=lambda: self._export_report("txt"),
                      height=40, corner_radius=9, fg_color=c["surface"], text_color=c["text"],
                      border_color=c["border"], border_width=1, hover_color=c["border"]).pack(side="left", padx=9)
        warnings = ctk.CTkFrame(parent, fg_color=c["surface"], border_color=c["border"], border_width=1, corner_radius=13)
        warnings.grid(row=3, column=0, sticky="ew")
        ctk.CTkLabel(warnings, text=f"Duplicate file entries ({sum(map(len, result.duplicate_groups))})",
                     text_color=c["text"], font=ctk.CTkFont(size=15, weight="bold")).pack(anchor="w", padx=18, pady=(15, 7))
        entries = ctk.CTkScrollableFrame(warnings, height=260, fg_color="transparent")
        entries.pack(fill="x", padx=8, pady=(0, 8))
        if not result.duplicate_groups:
            ctk.CTkLabel(entries, text="No duplicate files found. Your selected folder is clear.",
                         text_color=c["teal"]).pack(anchor="w", padx=12, pady=13)
        for group_index, group in enumerate(result.duplicate_groups, start=1):
            for file_index, record in enumerate(group):
                status = " · retained" if file_index == 0 else ""
                if record.path in getattr(self, "_removal_history", set()):
                    status = " · moved to Recycle Bin"
                ctk.CTkLabel(entries, text=f"Group {group_index}{status}  |  {record.path}",
                             text_color=c["muted"] if file_index else c["text"], anchor="w",
                             wraplength=850, font=ctk.CTkFont(size=11)).pack(fill="x", padx=8, pady=4)
        if result.errors:
            ctk.CTkLabel(parent, text=f"{len(result.errors)} scan warning(s) were recorded.",
                         text_color=c["warning"], font=ctk.CTkFont(size=12)).grid(row=4, column=0, sticky="w", pady=10)

    def _export_report(self, kind: str) -> None:
        if not self.scan_result:
            return
        extension = ".csv" if kind == "csv" else ".txt"
        destination = filedialog.asksaveasfilename(
            title="Save scan report", defaultextension=extension,
            filetypes=[("CSV report", "*.csv")] if kind == "csv" else [("Text report", "*.txt")],
            initialfile=f"duplicate-scan-report{extension}",
        )
        if not destination:
            return
        try:
            removed = getattr(self, "_removal_history", set())
            output = export_csv if kind == "csv" else export_txt
            output(self.scan_result, destination, removed)
            self._notify(f"Report exported: {Path(destination).name}")
            if messagebox.askyesno("Report saved", "Report saved successfully. Open its containing folder?"):
                self._open_location(Path(destination).parent)
        except OSError as error:
            messagebox.showerror("Export failed", f"Could not save report:\n{error}")

    def _open_location(self, path: Path) -> None:
        try:
            if os.name == "nt":
                os.startfile(str(path))  # type: ignore[attr-defined]
            elif os.name == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except OSError as error:
            messagebox.showerror("Could not open location", str(error))

    def _empty_state(self, parent, title: str, description: str, command) -> None:
        c = self._colors()
        panel = ctk.CTkFrame(parent, fg_color=c["surface"], border_color=c["border"], border_width=1, corner_radius=14)
        panel.grid(row=1, column=0, sticky="ew", pady=3)
        ctk.CTkLabel(panel, text="⌕", font=ctk.CTkFont(size=42), text_color=c["primary"]).pack(pady=(28, 8))
        ctk.CTkLabel(panel, text=title, text_color=c["text"],
                     font=ctk.CTkFont(size=18, weight="bold")).pack()
        ctk.CTkLabel(panel, text=description, text_color=c["muted"], wraplength=650,
                     font=ctk.CTkFont(size=12)).pack(pady=(6, 14))
        ctk.CTkButton(panel, text="Go to folder scanner", command=command,
                      fg_color=c["primary"], hover_color=c["primary_hover"], height=38,
                      corner_radius=9).pack(pady=(0, 23))

    def _on_close(self) -> None:
        if self.scan_active and self.cancel_event:
            self.cancel_event.set()
        self.destroy()
