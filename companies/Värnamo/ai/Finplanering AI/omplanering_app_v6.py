# -*- coding: utf-8 -*-
"""
AI Omplanering v6 - skrivbordsapp (Tkinter)
=========================================

Grafiskt skal runt `omplanering_core_v6`. Anvaendaren vaeljer en arbetsbok,
klustringsfoenster och laashorisont, trycker Kör och far tillbaka:

  * live-logg fran motorn
  * nyckeltal fore/efter
  * hela sammanfattningsfliken
  * en soek- och filtrerbar tabell med alla resultatrader
  * datavalideringens anmaerkningar
  * genvaegar till de skapade Excel-/CSV-filerna

Starta med::

    python omplanering_app_v6.py

Kraever endast standardbiblioteket + pandas/openpyxl (samma som motorn).
V6 har egna UI-installningar och laashorisont (standard 4 h). Vaerdet 0
staenger av framtida laashorisont; redan paaboerjade order foerblir frysta.
Import av modulen startar inget GUI; main() startar skrivbordsappen.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import traceback
from datetime import datetime
from typing import Optional

import pandas as pd
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import omplanering_core_v6 as core  # noqa: E402


APP_TITLE = f"AI Omplanering  v{core.VERSION}  –  Finplanering Op10"
SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             ".omplanering_ui_v6.json")

# Paletten foljer statusfaergerna i Jeeves.
C_BG = "#f4f6f9"
C_PANEL = "#ffffff"
C_INK = "#1f2933"
C_MUTED = "#5c6b7a"
C_ACCENT = "#1f3864"
C_GREEN = "#d8f0d0"
C_RED = "#fbd5cb"
C_YELLOW = "#fff4c2"
C_BLUE = "#d6e6fa"

STATUS_TAGS = {"Grön": C_GREEN, "Röd": C_RED, "Gul": C_YELLOW, "Blå": C_BLUE}

PREVIEW_COLUMNS = [
    ("AoNr", 70), ("OpNr", 50), ("ArtNr", 90),
    ("ProdGr", 70), ("AI_ProdGr", 80),
    ("Orginal_TiSlutDat", 120), ("AI_TiSlutDat", 120),
    ("Orginal_OrdBerLevDat", 110),
    ("Orginal_ColorName", 90), ("AI_ColorName", 90),
    ("AI_OpkoPrioritet", 70), ("AI_Kommentar", 700),
]


def _display(value) -> str:
    """Cellvarde -> text. Tomt/NaT/NaN blir tom strang, datum far kort format."""
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d %H:%M")
    return str(value)


# ---------------------------------------------------------------------------
# Smaa byggstenar
# ---------------------------------------------------------------------------

class KpiCard(ttk.Frame):
    """Ett nyckeltalskort: stor siffra + etikett + valfri delta-rad."""

    def __init__(self, master, label: str, tint: str = C_PANEL):
        super().__init__(master, style="Card.TFrame", padding=(14, 10))
        self.configure(borderwidth=1, relief="solid")
        self._tint = tint
        self.lbl_value = tk.Label(self, text="–", font=("Segoe UI", 22, "bold"),
                                  fg=C_ACCENT, bg=tint, anchor="w")
        self.lbl_value.pack(fill="x")
        self.lbl_name = tk.Label(self, text=label, font=("Segoe UI", 9),
                                 fg=C_MUTED, bg=tint, anchor="w")
        self.lbl_name.pack(fill="x")
        self.lbl_sub = tk.Label(self, text="", font=("Segoe UI", 9, "bold"),
                                fg=C_MUTED, bg=tint, anchor="w")
        self.lbl_sub.pack(fill="x")
        self.configure(style="Card.TFrame")
        for w in (self, self.lbl_value, self.lbl_name, self.lbl_sub):
            try:
                w.configure(background=tint)
            except tk.TclError:
                pass

    def set(self, value, sub: str = "", sub_color: str = C_MUTED) -> None:
        self.lbl_value.configure(text=str(value))
        self.lbl_sub.configure(text=sub, fg=sub_color)


# ---------------------------------------------------------------------------
# Huvudfoenster
# ---------------------------------------------------------------------------

class App(tk.Tk):

    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1280x820")
        self.minsize(1060, 680)
        self.configure(bg=C_BG)

        self.queue: "queue.Queue[tuple]" = queue.Queue()
        self.result: Optional[core.RunResult] = None
        self.worker: Optional[threading.Thread] = None
        self._preview_rows = []

        self.var_input = tk.StringVar()
        self.var_output = tk.StringVar()
        self.var_status = tk.StringVar(value="Välj en arbetsbok för att börja.")
        self.var_filter = tk.StringVar(value="Alla")
        self.var_search = tk.StringVar()
        # Klustringspolicy (N2 + N3) - se dokumentationen
        self.var_window = tk.StringVar(value=str(core.CLUSTER_WINDOW_DAYS))
        self.var_lock_horizon = tk.StringVar(value=str(core.LOCK_HORIZON_HOURS))

        self._init_style()
        self._build()
        self._load_settings()
        self.after(120, self._pump)

    # -- utseende ---------------------------------------------------------

    def _init_style(self) -> None:
        st = ttk.Style(self)
        try:
            st.theme_use("clam")
        except tk.TclError:
            pass
        st.configure(".", background=C_BG, foreground=C_INK,
                     font=("Segoe UI", 9))
        st.configure("TFrame", background=C_BG)
        st.configure("Card.TFrame", background=C_PANEL)
        st.configure("TLabel", background=C_BG, foreground=C_INK)
        st.configure("Head.TLabel", font=("Segoe UI", 15, "bold"),
                     foreground=C_ACCENT)
        st.configure("Sub.TLabel", foreground=C_MUTED)
        st.configure("Section.TLabelframe", background=C_BG)
        st.configure("Section.TLabelframe.Label", font=("Segoe UI", 10, "bold"),
                     foreground=C_ACCENT, background=C_BG)
        st.configure("Run.TButton", font=("Segoe UI", 10, "bold"), padding=(18, 9))
        st.configure("TNotebook", background=C_BG, borderwidth=0)
        st.configure("TNotebook.Tab", padding=(16, 8), font=("Segoe UI", 9))
        st.configure("Treeview", rowheight=22, fieldbackground=C_PANEL,
                     background=C_PANEL)
        st.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"))

    # -- layout -----------------------------------------------------------

    def _build(self) -> None:
        head = ttk.Frame(self, padding=(18, 14, 18, 6))
        head.pack(fill="x")
        ttk.Label(head, text="AI Omplanering – Op10", style="Head.TLabel").pack(anchor="w")
        ttk.Label(head, style="Sub.TLabel",
                  text="EDD-sekvensering · balanserad artikel-klustring · "
                       "valbar låshorisont · förseningsstak · alternativruttning   |   "
                       "Instruktion v6").pack(anchor="w")

        self._build_input(ttk.Frame(self, padding=(18, 6)))
        self._build_kpis()

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=18, pady=(10, 6))
        self.nb = nb
        self._build_tab_log(nb)
        self._build_tab_summary(nb)
        self._build_tab_result(nb)
        self._build_tab_warnings(nb)

        bar = ttk.Frame(self, padding=(18, 4, 18, 12))
        bar.pack(fill="x")
        self.lbl_status = ttk.Label(bar, textvariable=self.var_status, style="Sub.TLabel")
        self.lbl_status.pack(side="left")
        self.progress = ttk.Progressbar(bar, mode="indeterminate", length=190)
        self.progress.pack(side="right")

    def _build_input(self, box: ttk.Frame) -> None:
        box.pack(fill="x")
        grid = ttk.Frame(box)
        grid.pack(fill="x")
        grid.columnconfigure(1, weight=1)

        ttk.Label(grid, text="Arbetsbok (.xlsx)").grid(row=0, column=0, sticky="w", pady=3)
        e1 = ttk.Entry(grid, textvariable=self.var_input)
        e1.grid(row=0, column=1, sticky="ew", padx=8, pady=3)
        ttk.Button(grid, text="Bläddra…", command=self._pick_input).grid(row=0, column=2, pady=3)

        ttk.Label(grid, text="Utkatalog").grid(row=1, column=0, sticky="w", pady=3)
        ttk.Entry(grid, textvariable=self.var_output).grid(row=1, column=1, sticky="ew",
                                                           padx=8, pady=3)
        ttk.Button(grid, text="Bläddra…", command=self._pick_output).grid(row=1, column=2, pady=3)

        # --- Klustringsfönster; V6 styr övriga mål i motorn ---
        pol = ttk.Frame(grid)
        pol.grid(row=2, column=1, sticky="w", padx=8, pady=(8, 0))
        ttk.Label(grid, text="Klustring").grid(row=2, column=0, sticky="w", pady=(8, 0))
        ttk.Label(pol, text="Fönster").pack(side="left")
        ttk.Entry(pol, textvariable=self.var_window, width=5).pack(side="left", padx=(6, 2))
        ttk.Label(pol, text="dygn från EDD-datum; lika vikt per order",
              style="Sub.TLabel").pack(side="left")

        lock = ttk.Frame(grid)
        lock.grid(row=3, column=1, sticky="w", padx=8, pady=(8, 0))
        ttk.Label(grid, text="Låshorisont").grid(row=3, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(lock, textvariable=self.var_lock_horizon, width=7).pack(side="left")
        ttk.Label(lock, text="timmar – standard 4 h; 0 stänger av framtida låshorisont. "
                            "Redan påbörjade förblir frysta.",
                  style="Sub.TLabel").pack(side="left", padx=(6, 0))

        btns = ttk.Frame(box)
        btns.pack(fill="x", pady=(10, 2))
        self.btn_run = ttk.Button(btns, text="▶  Kör omplanering",
                                  style="Run.TButton", command=self._run)
        self.btn_run.pack(side="left")
        self.btn_xlsx = ttk.Button(btns, text="Öppna Excel", state="disabled",
                                   command=lambda: self._open(self.result.xlsx_path))
        self.btn_xlsx.pack(side="left", padx=(10, 0))
        self.btn_csv = ttk.Button(btns, text="Öppna CSV", state="disabled",
                                  command=lambda: self._open(self.result.csv_path))
        self.btn_csv.pack(side="left", padx=(6, 0))
        self.btn_dir = ttk.Button(btns, text="Öppna mapp", state="disabled",
                                  command=self._open_dir)
        self.btn_dir.pack(side="left", padx=(6, 0))
        ttk.Button(btns, text="Dokumentation V6",
                   command=self._open_doc).pack(side="right")

    def _build_kpis(self) -> None:
        wrap = ttk.Frame(self, padding=(18, 8, 18, 0))
        wrap.pack(fill="x")
        self.kpis = {}
        spec = [
            ("rows", "Rader i underlaget", C_PANEL),
            ("red", "Röda order  (före → efter)", C_RED),
            ("yellow", "Gula order  (före → efter)", C_YELLOW),
            ("green", "Gröna order  (före → efter)", C_GREEN),
            ("late", "Förseningsdygn  (före → efter)", C_PANEL),
            ("movable", "Omplanerade Op10", C_PANEL),
            ("frozen", "Frysta – redan påbörjade", C_BLUE),
            ("reroute", "Flyttade till alt. maskin", C_PANEL),
            ("setup", "Sparad ställtid (h)", C_PANEL),
        ]
        for i, (key, label, tint) in enumerate(spec):
            card = KpiCard(wrap, label, tint)
            card.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 8, 0))
            wrap.columnconfigure(i, weight=1)
            self.kpis[key] = card

    def _build_tab_log(self, nb: ttk.Notebook) -> None:
        f = ttk.Frame(nb, padding=10)
        nb.add(f, text="  Körlogg  ")
        self.txt_log = tk.Text(f, wrap="word", font=("Consolas", 9),
                               bg="#11161d", fg="#dbe4ee", insertbackground="#dbe4ee",
                               relief="flat", padx=12, pady=10)
        sb = ttk.Scrollbar(f, command=self.txt_log.yview)
        self.txt_log.configure(yscrollcommand=sb.set, state="disabled")
        self.txt_log.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.txt_log.tag_configure("warn", foreground="#ffb454")
        self.txt_log.tag_configure("err", foreground="#ff6b6b")
        self.txt_log.tag_configure("ok", foreground="#7ee787")
        self.txt_log.tag_configure("head", foreground="#79c0ff",
                                   font=("Consolas", 9, "bold"))

    def _build_tab_summary(self, nb: ttk.Notebook) -> None:
        f = ttk.Frame(nb, padding=10)
        nb.add(f, text="  Sammanfattning  ")
        cols = ("post", "varde")
        self.tv_sum = ttk.Treeview(f, columns=cols, show="headings", height=22)
        self.tv_sum.heading("post", text="Post")
        self.tv_sum.heading("varde", text="Värde")
        self.tv_sum.column("post", width=520, anchor="w")
        self.tv_sum.column("varde", width=520, anchor="w")
        sb = ttk.Scrollbar(f, command=self.tv_sum.yview)
        self.tv_sum.configure(yscrollcommand=sb.set)
        self.tv_sum.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tv_sum.tag_configure("section", background=C_ACCENT, foreground="white",
                                  font=("Segoe UI", 9, "bold"))
        for name, colr in STATUS_TAGS.items():
            self.tv_sum.tag_configure("c_" + name, background=colr)

    def _build_tab_result(self, nb: ttk.Notebook) -> None:
        f = ttk.Frame(nb, padding=10)
        nb.add(f, text="  Resultat per order  ")

        bar = ttk.Frame(f)
        bar.pack(fill="x", pady=(0, 8))
        ttk.Label(bar, text="Visa:").pack(side="left")
        cb = ttk.Combobox(bar, textvariable=self.var_filter, width=26, state="readonly",
                          values=["Alla", "Endast röda (AI)", "Endast gula (AI)",
                                  "Endast gröna (AI)",
                                  "Förbättrade (Röd → Grön/Gul)", "Försämrade (→ Röd)",
                                  "Mer försenade än originalplanen",
                                  "Omrutade till alt. maskin", "Ställtid sparad",
                                  "Framdragna för klustring",
                                  "Frysta – redan påbörjade", "Frysta – låshorisont",
                                  "Frysta – övriga"])
        cb.pack(side="left", padx=(6, 16))
        cb.bind("<<ComboboxSelected>>", lambda _e: self._refresh_preview())
        ttk.Label(bar, text="Sök (AoNr / OrderNr / ArtNr / ProdGr):").pack(side="left")
        e = ttk.Entry(bar, textvariable=self.var_search, width=26)
        e.pack(side="left", padx=6)
        e.bind("<KeyRelease>", lambda _e: self._refresh_preview())
        self.lbl_count = ttk.Label(bar, text="", style="Sub.TLabel")
        self.lbl_count.pack(side="right")

        # Egen behallare sa att grid (tabell + rullister) inte krockar med
        # pack-layouten i filterraden ovanfor.
        table = ttk.Frame(f)
        table.pack(fill="both", expand=True)
        cols = [c for c, _ in PREVIEW_COLUMNS]
        self.tv_res = ttk.Treeview(table, columns=cols, show="headings")
        for name, width in PREVIEW_COLUMNS:
            self.tv_res.heading(name, text=name)
            self.tv_res.column(name, width=width, anchor="w", stretch=False)
        vs = ttk.Scrollbar(table, orient="vertical", command=self.tv_res.yview)
        hs = ttk.Scrollbar(table, orient="horizontal", command=self.tv_res.xview)
        self.tv_res.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
        self.tv_res.grid(row=0, column=0, sticky="nsew")
        vs.grid(row=0, column=1, sticky="ns")
        hs.grid(row=1, column=0, sticky="ew")
        table.rowconfigure(0, weight=1)
        table.columnconfigure(0, weight=1)
        for name, colr in STATUS_TAGS.items():
            self.tv_res.tag_configure("c_" + name, background=colr)
        self.tv_res.bind("<Double-1>", self._show_row_detail)

    def _build_tab_warnings(self, nb: ttk.Notebook) -> None:
        f = ttk.Frame(nb, padding=10)
        nb.add(f, text="  Anmärkningar  ")
        self.txt_warn = tk.Text(f, wrap="word", font=("Segoe UI", 10), bg=C_PANEL,
                                relief="flat", padx=14, pady=12)
        sb = ttk.Scrollbar(f, command=self.txt_warn.yview)
        self.txt_warn.configure(yscrollcommand=sb.set, state="disabled")
        self.txt_warn.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

    # -- filval -----------------------------------------------------------

    def _pick_input(self) -> None:
        start = os.path.dirname(self.var_input.get()) or os.getcwd()
        path = filedialog.askopenfilename(
            title="Välj arbetsbok med planeringsunderlag",
            initialdir=start,
            filetypes=[("Excel-arbetsbok", "*.xlsx *.xlsm"), ("Alla filer", "*.*")])
        if path:
            self.var_input.set(path)
            if not self.var_output.get():
                self.var_output.set(os.path.join(os.path.dirname(path), "output"))
            self.var_status.set(f"Vald fil: {os.path.basename(path)}")

    def _pick_output(self) -> None:
        start = self.var_output.get() or os.getcwd()
        path = filedialog.askdirectory(title="Välj utkatalog", initialdir=start)
        if path:
            self.var_output.set(path)

    # -- koerning ---------------------------------------------------------

    def _run(self) -> None:
        path = self.var_input.get().strip()
        if not path:
            messagebox.showwarning("Ingen fil vald",
                                   "Välj först en arbetsbok (.xlsx).")
            return
        if not os.path.isfile(path):
            messagebox.showerror("Filen saknas", f"Hittar inte:\n{path}")
            return
        if self.worker and self.worker.is_alive():
            return

        try:
            policy = core.ClusterPolicy(
                window_days=max(0, int(float(self.var_window.get().replace(",", ".")))),
                budget_days_per_hour=0.0,
            )
        except (ValueError, OverflowError):
            messagebox.showerror(
                "Ogiltig klustringspolicy",
                "Klusterfönstret ska vara ett heltal dygn, minst 0.\n"
                "Exempel: 30.")
            return

        # Läs och validera Tk-värdet här på UI-tråden, aldrig i arbetstråden.
        try:
            lock_horizon_hours = core.validate_lock_horizon_hours(
                self.var_lock_horizon.get())
        except (TypeError, ValueError, OverflowError):
            messagebox.showerror(
                "Ogiltig låshorisont",
                "Låshorisonten ska vara ett ändligt antal timmar, minst 0.\n"
                "Använd punkt eller komma för decimaler, t.ex. 4 eller 2,5.\n"
                "0 stänger av framtida låshorisont; redan påbörjade förblir frysta.")
            return

        out = self.var_output.get().strip() or None
        self._save_settings()

        self._log_clear()
        self.result = None
        for b in (self.btn_xlsx, self.btn_csv, self.btn_dir):
            b.configure(state="disabled")
        self.btn_run.configure(state="disabled")
        self.progress.start(14)
        self.var_status.set("Kör omplanering …")
        self.nb.select(0)

        self.worker = threading.Thread(target=self._work,
                                       args=(path, out, policy, lock_horizon_hours),
                                       daemon=True)
        self.worker.start()

    def _work(self, path: str, out: Optional[str],
              policy: core.ClusterPolicy, lock_horizon_hours: float) -> None:
        """Kör motorn med UI-trådens snapshot; kommunicera endast via kön."""
        try:
            res = core.run_replanning(path, out, policy=policy,
                                      lock_horizon_hours=lock_horizon_hours,
                                      log=lambda m: self.queue.put(("log", m)))
            self.queue.put(("done", res))
        except Exception as exc:  # noqa: BLE001
            self.queue.put(("error", (exc, traceback.format_exc())))

    def _pump(self) -> None:
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                if kind == "log":
                    self._log(payload)
                elif kind == "done":
                    self._finish(payload)
                elif kind == "error":
                    self._fail(*payload)
        except queue.Empty:
            pass
        self.after(120, self._pump)

    def _finish(self, res: core.RunResult) -> None:
        self.result = res
        self.progress.stop()
        self.btn_run.configure(state="normal")
        for b in (self.btn_xlsx, self.btn_csv, self.btn_dir):
            b.configure(state="normal")

        s = res.stats
        self.kpis["rows"].set(s["rows"], f"{s['machines']} produktionsgrupper")
        delta = s["red_before"] - s["red_after"]
        self.kpis["red"].set(f"{s['red_before']} → {s['red_after']}",
                             f"{delta:+d} order", "#1a7f37" if delta > 0 else C_MUTED)
        self.kpis["yellow"].set(f"{s['yellow_before']} → {s['yellow_after']}",
                                "marginal exakt 1 dygn")
        gdelta = s["green_after"] - s["green_before"]
        self.kpis["green"].set(f"{s['green_before']} → {s['green_after']}",
                               f"{gdelta:+d} order", "#1a7f37" if gdelta > 0 else C_MUTED)

        ldelta = s["late_days_after"] - s["late_days_before"]
        self.kpis["late"].set(
            f"{s['late_days_before']:.0f} → {s['late_days_after']:.0f}",
            f"{ldelta:+.0f} dygn · {s['worse_count']} order blev värre",
            "#1a7f37" if ldelta < 0 else "#b3372a")

        change_note = ("originalplan behållen – kandidat avvisad"
                   if s.get("optimization_fallback") else
                       f"{s['cap_repaired_count']} kvar i originalslot p.g.a. tak")
        self.kpis["movable"].set(s["changed"], change_note)
        self.kpis["frozen"].set(s["frozen_started"], "rörs ej – låsta i maskin")
        self.kpis["reroute"].set(s["rerouted"], "via Prio2–Prio8")
        self.kpis["setup"].set(f"{s['setup_hours_saved']:.0f}",
                               f"{s['clustered']} klustrade · "
                               f"{s['pulled_forward']} framdragna")

        self._fill_summary(res)
        self._load_preview(res)
        self._fill_warnings(res)

        result_note = (" · säkerhetsåterfall: originalplan behållen"
                       if s.get("optimization_fallback") else "")
        self.var_status.set(
            f"Klart {datetime.now():%H:%M:%S}  ·  {os.path.basename(res.xlsx_path)}  "
            f"·  röda {s['red_before']} → {s['red_after']}{result_note}")
        self.nb.select(1)

    def _fail(self, exc: Exception, tb: str) -> None:
        self.progress.stop()
        self.btn_run.configure(state="normal")
        self.var_status.set("Körningen avbröts med fel.")
        self._log("FEL: " + str(exc))
        self._log(tb)
        messagebox.showerror("Fel under körning", str(exc))

    # -- presentation -----------------------------------------------------

    def _fill_summary(self, res: core.RunResult) -> None:
        self.tv_sum.delete(*self.tv_sum.get_children())
        for label, value in res.summary:
            if label is None:
                self.tv_sum.insert("", "end", values=("", ""))
                continue
            text = str(label)
            tags = ()
            if text.isupper() or text in ("URSPRUNGLIG STATUS", "EFTER OPTIMERING",
                                          "FÖRBÄTTRING"):
                tags = ("section",)
            elif text in STATUS_TAGS:
                tags = ("c_" + text,)
            self.tv_sum.insert("", "end",
                               values=(text, "" if value is None else str(value)),
                               tags=tags)

    def _load_preview(self, res: core.RunResult) -> None:
        df = res.result
        jeeves = df["Orginal_ColorName"].map(core.normalize_color)
        rows = []
        for i, rec in enumerate(df.to_dict("records")):
            due = rec.get("Orginal_OrdBerLevDat")
            # Utgangslaget bedomt med SAMMA statusregel som AI-varden, sa att
            # filtren "forbattrade"/"forsamrade" jamfor likt med likt.
            base_margin = core.margin_days_between(due, rec.get("Orginal_TiSlutDat"))
            rec["_base"] = core.status_from_margin(base_margin, jeeves.iloc[i])
            ai_margin = core.margin_days_between(due, rec.get("AI_TiSlutDat"))
            rec["_worse"] = (
                base_margin is not None and ai_margin is not None
                and max(0, -ai_margin) > max(0, -base_margin))
            rows.append(rec)
        self._preview_rows = rows
        self._refresh_preview()

    def _refresh_preview(self) -> None:
        mode = self.var_filter.get()
        needle = self.var_search.get().strip().lower()
        self.tv_res.delete(*self.tv_res.get_children())

        shown = 0
        for rec in self._preview_rows:
            ai = rec.get("AI_ColorName")
            base = rec.get("_base")
            kom = str(rec.get("AI_Kommentar") or "")
            if mode == "Endast röda (AI)" and ai != "Röd":
                continue
            if mode == "Endast gula (AI)" and ai != "Gul":
                continue
            if mode == "Endast gröna (AI)" and ai != "Grön":
                continue
            if mode == "Förbättrade (Röd → Grön/Gul)" and not (
                    base == "Röd" and ai in ("Grön", "Gul")):
                continue
            if mode == "Försämrade (→ Röd)" and not (base != "Röd" and ai == "Röd"):
                continue
            if mode == "Mer försenade än originalplanen" and not rec.get("_worse"):
                continue
            if mode == "Omrutade till alt. maskin" and "Omrutad från" not in kom:
                continue
            if mode == "Ställtid sparad" and "Ställtid sparad" not in kom:
                continue
            if mode == "Framdragna för klustring" and "Framdragen förbi" not in kom:
                continue
            if mode == "Frysta – redan påbörjade" and "Redan påbörjad" not in kom:
                continue
            if mode == "Frysta – låshorisont" and "låshorisont" not in kom:
                continue
            if mode == "Frysta – övriga" and not (
                    ("Ligger fast" in kom or "ej omplaneringsbar" in kom
                     or "Saknar OrdBerLevDat" in kom)
                    and "Redan påbörjad" not in kom):
                continue
            if needle:
                hay = " ".join(str(rec.get(c, "")) for c in
                               ("AoNr", "ArtNr", "ProdGr", "AI_ProdGr")).lower()
                hay += " " + kom.lower()
                if needle not in hay:
                    continue

            values = [_display(rec.get(col)) for col, _w in PREVIEW_COLUMNS]
            tag = "c_" + str(ai) if ai in STATUS_TAGS else ""
            self.tv_res.insert("", "end", values=values, tags=(tag,) if tag else ())
            shown += 1
            if shown >= 3000:
                break

        total = len(self._preview_rows)
        extra = "  (visar de 3 000 första)" if shown >= 3000 else ""
        self.lbl_count.configure(text=f"{shown} av {total} rader{extra}")

    def _show_row_detail(self, _event=None) -> None:
        sel = self.tv_res.selection()
        if not sel:
            return
        values = self.tv_res.item(sel[0], "values")
        cols = [c for c, _ in PREVIEW_COLUMNS]
        win = tk.Toplevel(self)
        win.title(f"AO#{values[0]}")
        win.geometry("760x520")
        win.configure(bg=C_PANEL)
        txt = tk.Text(win, wrap="word", font=("Segoe UI", 10), bg=C_PANEL,
                      relief="flat", padx=16, pady=14)
        txt.pack(fill="both", expand=True)
        for c, v in zip(cols, values):
            txt.insert("end", f"{c}\n", "k")
            txt.insert("end", f"{v or '–'}\n\n")
        txt.tag_configure("k", font=("Segoe UI", 9, "bold"), foreground=C_ACCENT)
        txt.configure(state="disabled")

    def _fill_warnings(self, res: core.RunResult) -> None:
        self.txt_warn.configure(state="normal")
        self.txt_warn.delete("1.0", "end")
        if not res.warnings:
            self.txt_warn.insert("end",
                                 "Inga datavalideringsanmärkningar.\n\n"
                                 "Underlaget var komplett och konsekvent för de "
                                 "kontroller motorn gör: matchande operationsrader, "
                                 "operationstider, kalendertäckning och låsta "
                                 "maskinblock.")
        else:
            self.txt_warn.insert(
                "end", f"{len(res.warnings)} anmärkning(ar) från datavalideringen\n\n",
                "h")
            self.txt_warn.insert(
                "end", "Motorn gissar aldrig kring inkonsekvent data – den "
                       "rapporterar och låter berörda rader passera enligt "
                       "frysningsreglerna.\n\n")
            for i, w in enumerate(res.warnings, 1):
                self.txt_warn.insert("end", f"{i}.  ", "n")
                self.txt_warn.insert("end", w + "\n\n")
        self.txt_warn.tag_configure("h", font=("Segoe UI", 12, "bold"),
                                    foreground=C_ACCENT)
        self.txt_warn.tag_configure("n", font=("Segoe UI", 10, "bold"),
                                    foreground=C_ACCENT)
        self.txt_warn.configure(state="disabled")
        tab = f"  Anmärkningar{f' ({len(res.warnings)})' if res.warnings else ''}  "
        self.nb.tab(3, text=tab)

    # -- logg -------------------------------------------------------------

    def _log_clear(self) -> None:
        self.txt_log.configure(state="normal")
        self.txt_log.delete("1.0", "end")
        self.txt_log.configure(state="disabled")

    def _log(self, msg: str) -> None:
        tag = ""
        if msg.startswith("VARNING"):
            tag = "warn"
        elif msg.startswith("FEL"):
            tag = "err"
        elif msg.startswith("KLART"):
            tag = "ok"
        elif msg.startswith("==="):
            tag = "head"
        self.txt_log.configure(state="normal")
        self.txt_log.insert("end", msg + "\n", tag)
        self.txt_log.see("end")
        self.txt_log.configure(state="disabled")

    # -- filer ------------------------------------------------------------

    def _open(self, path: str) -> None:
        if not path or not os.path.exists(path):
            return
        try:
            if sys.platform.startswith("win"):
                os.startfile(path)  # noqa: S606
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except OSError as exc:
            messagebox.showerror("Kunde inte öppna filen", str(exc))

    def _open_dir(self) -> None:
        if self.result:
            self._open(os.path.dirname(self.result.xlsx_path))

    def _open_doc(self) -> None:
        doc = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "dokumentation_v6.html")
        if os.path.exists(doc):
            self._open(doc)
        else:
            messagebox.showinfo("Dokumentation saknas",
                                "dokumentation_v6.html hittades inte bredvid appen.")

    # -- installningar ----------------------------------------------------

    def _load_settings(self) -> None:
        # Återställ standard även vid saknad fil, felaktig JSON eller ogiltigt värde.
        self.var_lock_horizon.set(str(core.LOCK_HORIZON_HOURS))
        self.var_window.set(str(core.CLUSTER_WINDOW_DAYS))
        try:
            with open(SETTINGS_FILE, encoding="utf-8") as fh:
                data = json.load(fh)
            if not isinstance(data, dict):
                data = {}
            self.var_input.set(data.get("input", ""))
            self.var_output.set(data.get("output", ""))
            try:
                lock_horizon_hours = core.validate_lock_horizon_hours(
                    str(data.get("lock_horizon_hours", core.LOCK_HORIZON_HOURS)))
                self.var_lock_horizon.set(str(lock_horizon_hours))
            except (TypeError, ValueError, OverflowError):
                pass
            try:
                window_days = max(0, int(float(str(data.get(
                    "window_days", core.CLUSTER_WINDOW_DAYS)).replace(",", "."))))
                self.var_window.set(str(window_days))
            except (TypeError, ValueError, OverflowError):
                pass
        except (OSError, ValueError):
            pass
        if not self.var_input.get():
            here = os.path.dirname(os.path.abspath(__file__))
            for name in sorted(os.listdir(here)):
                if name.lower().endswith(".xlsx") and "resultat" not in name.lower():
                    self.var_input.set(os.path.join(here, name))
                    self.var_output.set(os.path.join(here, "output"))
                    break

    def _save_settings(self) -> None:
        try:
            # Samma normalisering som vid körning; sparas endast från UI-tråden.
            data = {"input": self.var_input.get(),
                    "output": self.var_output.get(),
                    "window_days": max(0, int(float(
                        self.var_window.get().replace(",", ".")))),
                    "lock_horizon_hours": core.validate_lock_horizon_hours(
                        self.var_lock_horizon.get())}
            with open(SETTINGS_FILE, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, allow_nan=False)
        except (OSError, TypeError, ValueError, OverflowError):
            pass


def main() -> None:
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()