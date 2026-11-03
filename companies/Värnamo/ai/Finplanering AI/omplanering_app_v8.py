# -*- coding: utf-8 -*-
"""
AI Omplanering V8 - Excel- och SQL-skrivbordsapp (Tkinter)
=========================================

    Grafiskt skal runt `omplanering_core_v8`. Anvaendaren vaeljer Excel eller SQL,
    planeringsparametrar, trycker Kör och far tillbaka:

  * live-logg fran motorn
  * nyckeltal fore/efter
  * hela sammanfattningsfliken
  * en soek- och filtrerbar tabell med alla resultatrader
  * datavalideringens anmaerkningar
  * genvaegar till de skapade Excel-/CSV-filerna

Starta med::

    python omplanering_app_v8.py

Kraever endast standardbiblioteket + pandas/openpyxl (samma som motorn).
V8 bygger vidare pa V7:s kundviktning och dynamiska poaengtrappa.
Import av modulen startar inget GUI; main() startar skrivbordsappen.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
import traceback
import webbrowser
from datetime import datetime
from typing import Optional

import pandas as pd
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
SERVICE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "service")
sys.path.insert(0, SERVICE_DIR)
import config_v8 as sql_config  # noqa: E402
import db_v8 as sql_db  # noqa: E402
import sql_refresh_v8 as sql_refresh  # noqa: E402
import sql_sink_v8 as sql_sink  # noqa: E402
import sql_source_v8 as sql_source  # noqa: E402
import omplanering_core_v8 as core  # noqa: E402


APP_TITLE = f"AI Omplanering  v{core.VERSION}  –  Finplanering Op10"
SETTINGS_FILE = sql_config.USER_SETTINGS_PATH


def resource_path(name: str) -> str:
    """Resolve a resource from source or the PyInstaller bundle."""
    root = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, name)

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
C_UNKNOWN = "#e5e8e8"

STATUS_TAGS = {"Grön": C_GREEN, "Röd": C_RED, "Gul": C_YELLOW,
               "Blå": C_BLUE, "Ljusblå": C_BLUE, "Okänd": C_UNKNOWN}

PREVIEW_COLUMNS = [
    ("AoNr", 70), ("OrderNr", 90), ("Kundnr", 90), ("Kundvikt", 70),
    ("MaxFörseningsdagar", 115), ("OpNr", 50), ("ArtNr", 90),
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


class Tooltip:
    """Visar en förklarande text när muspekaren vilar över en kontroll."""

    def __init__(self, widget, text: str, wrap: int = 380):
        self.widget = widget
        self.text = text
        self.wrap = wrap
        self.tip: Optional[tk.Toplevel] = None
        widget.bind("<Enter>", self._show, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _show(self, _event=None) -> None:
        if self.tip is not None:
            return
        x = self.widget.winfo_rootx() + 12
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry(f"+{x}+{y}")
        tk.Label(self.tip, text=self.text, justify="left", wraplength=self.wrap,
                 background="#fffbe6", foreground=C_INK, relief="solid",
                 borderwidth=1, font=("Segoe UI", 9), padx=8, pady=5).pack()

    def _hide(self, _event=None) -> None:
        if self.tip is not None:
            self.tip.destroy()
            self.tip = None


def _help(widget, text: str):
    Tooltip(widget, text)
    return widget


# ---------------------------------------------------------------------------
# Huvudfoenster
# ---------------------------------------------------------------------------

class App(tk.Tk):

    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        height = max(820, min(1000, self.winfo_screenheight() - 80))
        self.geometry(f"1280x{height}")
        self.minsize(1060, 680)
        self.configure(bg=C_BG)

        self.queue: "queue.Queue[tuple]" = queue.Queue()
        self.logo_photo: Optional[tk.PhotoImage] = None
        self.result: Optional[core.RunResult] = None
        self.worker: Optional[threading.Thread] = None
        self._preview_rows = []
        self.source_mode = tk.StringVar(value="excel")
        self.var_sql_password = tk.StringVar()
        self._sql_password: Optional[str] = None
        self._sql_identity: Optional[tuple[str, str]] = None
        self._sql_source: Optional[core.SourceData] = None
        self._pending_outcome: Optional[core.PlanOutcome] = None
        self._pending_started: Optional[datetime] = None
        self._sql_busy: Optional[str] = None
        self._sql_started_at = 0.0
        self._sql_phase = ""
        self._refresh_cursor = None
        self._refresh_cancel_requested = False
        self.var_settings_status = tk.StringVar(value="")
        self.var_input = tk.StringVar()
        self.var_output = tk.StringVar()
        self.var_status = tk.StringVar(value="Välj en arbetsbok för att börja.")
        self.var_filter = tk.StringVar(value="Alla")
        self.var_search = tk.StringVar()
        # Klustringspolicy (N2 + N3) - se dokumentationen
        self.var_window = tk.StringVar(value=str(core.CLUSTER_WINDOW_DAYS))
        self.var_lock_horizon = tk.StringVar(value=str(core.LOCK_HORIZON_HOURS))
        self.var_max_tardiness = tk.StringVar(value=str(core.DEFAULT_MAX_TARDINESS_DAYS))
        self.score_band_vars = [
            [tk.StringVar(value=str(lower)),
             tk.StringVar(value="" if upper is None else str(upper)),
             tk.StringVar(value=str(score))]
            for lower, upper, score in core.DEFAULT_TARDINESS_SCORE_BANDS
        ]

        self._init_style()
        self._build_menu()
        self._build()
        self._load_settings()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
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
        st.configure("Row.TButton", padding=(2, 0))
        st.configure("TNotebook", background=C_BG, borderwidth=0)
        st.configure("TNotebook.Tab", padding=(16, 8), font=("Segoe UI", 9))
        st.configure("Treeview", rowheight=22, fieldbackground=C_PANEL,
                     background=C_PANEL)
        st.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"))

    # -- layout -----------------------------------------------------------

    def _build_menu(self) -> None:
        menu_bar = tk.Menu(self)

        file_menu = tk.Menu(menu_bar, tearoff=False)
        file_menu.add_command(
            label="Öppna Excel-arbetsbok…",
            command=self._choose_excel_workbook,
            accelerator="Ctrl+O",
        )
        file_menu.add_command(
            label="Välj utdatakatalog…",
            command=self._pick_output,
        )
        file_menu.add_separator()
        file_menu.add_command(label="Avsluta", command=self._on_close)
        menu_bar.add_cascade(label="Arkiv", menu=file_menu)

        help_menu = tk.Menu(menu_bar, tearoff=False)
        help_menu.add_command(label="Dokumentation V8", command=self._open_doc)
        help_menu.add_command(label="Kontakta support…", command=self._contact_support)
        help_menu.add_separator()
        help_menu.add_command(label="Om AI Omplanering V8", command=self._show_about)
        menu_bar.add_cascade(label="Hjälp", menu=help_menu)

        self.configure(menu=menu_bar)
        self.bind_all("<Control-o>", lambda _event: self._choose_excel_workbook())

    def _build(self) -> None:
        head = ttk.Frame(self, padding=(18, 14, 18, 6))
        head.pack(fill="x")
        brand = ttk.Frame(head)
        brand.pack(fill="x")
        try:
            logo = tk.PhotoImage(master=self, file=resource_path("Property 1=Black.png"))
            scale = max(1, (logo.width() + 189) // 190, (logo.height() + 43) // 44)
            self.logo_photo = logo.subsample(scale, scale)
            ttk.Label(brand, image=self.logo_photo).pack(side="left", padx=(0, 16))
        except (tk.TclError, OSError):
            self.logo_photo = None
        title_block = ttk.Frame(brand)
        title_block.pack(side="left", fill="x", expand=True)
        ttk.Label(title_block, text="AI Omplanering V8 – Op10",
                  style="Head.TLabel").pack(anchor="w")
        ttk.Label(title_block, style="Sub.TLabel",
                  text="Föreslår en ny ordning för Operation 10 som minskar förseningar. "
                       "Låsta och påbörjade operationer flyttas aldrig, och inget skrivs "
                       "till SQL förrän du bekräftar.").pack(anchor="w")
        ttk.Label(title_block, style="Sub.TLabel",
                  text="Gör så här: 1) välj datakälla  2) kontrollera parametrarna  "
                       "3) Kör omplanering  4) granska resultatet  "
                       "5) spara till SQL (endast SQL-läge). "
                       "Håll muspekaren över ett fält för förklaring.").pack(anchor="w")

        # Packed first at the bottom so the status bar stays visible on small screens.
        bar = ttk.Frame(self, padding=(18, 4, 18, 12))
        bar.pack(side="bottom", fill="x")
        self.lbl_status = ttk.Label(bar, textvariable=self.var_status, style="Sub.TLabel")
        self.lbl_status.pack(side="left")
        self.progress = ttk.Progressbar(bar, mode="indeterminate", length=190)
        self.progress.pack(side="right")

        self._build_input(ttk.Frame(self, padding=(18, 6)))
        self._build_kpis()

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=18, pady=(10, 6))
        self.nb = nb
        self._build_tab_log(nb)
        self._build_tab_summary(nb)
        self._build_tab_result(nb)
        self._build_tab_warnings(nb)

    def _build_input(self, box: ttk.Frame) -> None:
        box.pack(fill="x")
        source_box = ttk.LabelFrame(box, text="1. Datakälla", padding=(8, 5))
        source_box.pack(fill="x")
        selector = ttk.Frame(source_box)
        selector.pack(fill="x")
        _help(ttk.Radiobutton(selector, text="Excel-arbetsbok", variable=self.source_mode,
                              value="excel", command=self._set_source_mode),
              "Läs planeringsunderlaget från en Excel-fil. Resultatet sparas som "
              "nya Excel- och CSV-filer; den valda arbetsboken ändras inte."
              ).pack(side="left")
        _help(ttk.Radiobutton(selector, text="SQL Server", variable=self.source_mode,
                              value="sql", command=self._set_source_mode),
              "Läs planeringsunderlaget direkt från databasen. Resultatet sparas "
              "lokalt och kan därefter, efter bekräftelse, skrivas till SQL."
              ).pack(side="left", padx=12)
        ttk.Label(selector, style="Sub.TLabel",
                  text="Välj varifrån underlaget ska läsas.").pack(side="left", padx=(6, 0))

        self.excel_frame = ttk.Frame(source_box)
        self.excel_frame.pack(fill="x")
        excel_grid = ttk.Frame(self.excel_frame)
        excel_grid.pack(fill="x")
        excel_grid.columnconfigure(1, weight=1)
        ttk.Label(excel_grid, text="Arbetsbok (.xlsx)").grid(
            row=0, column=0, sticky="w", pady=3)
        _help(ttk.Entry(excel_grid, textvariable=self.var_input),
              "Excel-filen med planeringsunderlaget (baslinje, operationer, "
              "kalender och maskinprioritet).").grid(
            row=0, column=1, sticky="ew", padx=8, pady=3)
        ttk.Button(excel_grid, text="Bläddra…", command=self._pick_input).grid(
            row=0, column=2, pady=3)
        ttk.Label(excel_grid, text="Utkatalog").grid(
            row=1, column=0, sticky="w", pady=3)
        _help(ttk.Entry(excel_grid, textvariable=self.var_output),
              "Mappen där resultatfilerna (Excel och CSV) sparas. "
              "Varje körning får ett nytt tidsstämplat filnamn.").grid(
            row=1, column=1, sticky="ew", padx=8, pady=3)
        ttk.Button(excel_grid, text="Bläddra…", command=self._pick_output).grid(
            row=1, column=2, pady=3)

        self.sql_frame = ttk.LabelFrame(source_box, text="SQL Server-anslutning",
                                        padding=(8, 5))
        self.sql_frame.pack(fill="x")
        ttk.Label(self.sql_frame, style="Sub.TLabel",
                  text="Steg: ① Anslut med lösenord  →  ② Uppdatera källdata (valfritt)  "
                       "→  ③ Läs tabeller  →  ④ Kör omplanering  →  "
                       "⑤ Bekräfta och skriv till SQL").pack(anchor="w", pady=(0, 3))
        sql_grid = ttk.Frame(self.sql_frame)
        sql_grid.pack(fill="x")
        sql_grid.columnconfigure(3, weight=1)
        self.lbl_sql_target = ttk.Label(sql_grid, text="")
        self.lbl_sql_target.grid(row=0, column=0, columnspan=3, sticky="w", pady=2)
        ttk.Label(sql_grid, text="Lösenord").grid(row=1, column=0, sticky="w", pady=3)
        self.entry_sql_password = _help(ttk.Entry(
            sql_grid, textvariable=self.var_sql_password, show="*", width=32),
            "Lösenordet för SQL-användaren ovan. Det används bara under den här "
            "sessionen och sparas aldrig.")
        self.entry_sql_password.grid(row=1, column=1, sticky="w", padx=8, pady=3)
        self.btn_connect_sql = _help(ttk.Button(
            sql_grid, text="① Anslut", command=self._connect_sql),
            "Kontrollerar lösenordet och vilken server/databas appen pratar med. "
            "Inget läses eller ändras i databasen.")
        self.btn_connect_sql.grid(row=1, column=2, sticky="w", pady=3)
        sql_actions = ttk.Frame(self.sql_frame)
        sql_actions.pack(fill="x", pady=(3, 0))
        self.btn_refresh_sql = _help(ttk.Button(
            sql_actions, text="② Uppdatera källdata via procedur",
            command=self._refresh_sql, state="disabled"),
            "Kör databasens uppdateringsprocedur så att källtabellerna får färsk "
            "data från Jeeves. Kan ta lång tid; appen väntar tills SQL Server "
            "svarar och du kan avbryta. Hoppa över om datan redan är aktuell.")
        self.btn_refresh_sql.pack(side="left")
        self.btn_cancel_refresh = _help(ttk.Button(
            sql_actions, text="■ Avbryt procedur",
            command=self._cancel_refresh, state="disabled"),
            "Avbryter den pågående proceduren. Appen begär rollback; "
            "kontrollera i SQL om proceduren hann göra egna commits.")
        self.btn_cancel_refresh.pack(side="left", padx=(8, 0))
        self.btn_load_sql = _help(ttk.Button(
            sql_actions, text="③ Läs tabeller från SQL",
            command=self._load_sql, state="disabled"),
            "Läser planeringsunderlaget från databasen. Inget skrivs.")
        self.btn_load_sql.pack(side="left", padx=(8, 0))
        self.btn_sql_config = _help(ttk.Button(
            sql_actions, text="Öppna SQL-konfiguration", command=self._open_sql_config),
            "Öppnar connection.json med server, databas, användare och tidsgränser. "
            "Ändras normalt av administratör; starta om appen efter ändring.")
        self.btn_sql_config.pack(side="left", padx=(8, 0))
        self.lbl_sql_status = ttk.Label(self.sql_frame, text="")
        self.lbl_sql_status.pack(anchor="w", pady=(4, 0))
        self.sql_progress = ttk.Progressbar(
            self.sql_frame, mode="indeterminate", length=220)
        self._update_sql_target()
        self.sql_frame.pack_forget()

        settings_row = ttk.Frame(box)
        settings_row.pack(fill="x", pady=(8, 0))
        params = ttk.LabelFrame(settings_row, text="2. Planeringsparametrar",
                                padding=(8, 5))
        params.pack(side="left", fill="both", expand=True, padx=(0, 8))
        params.columnconfigure(2, weight=1)
        param_spec = [
            ("Klusterfönster", self.var_window, "dygn",
             "Order med samma artikel får köras i följd för att spara ställtid "
             "om leveransdatum ligger inom så många dygn.",
             "Större fönster ger fler sammanslagna körningar (mindre ställtid) men "
             "kan flytta order längre från sitt leveransdatum. 0 = ingen klustring."),
            ("Låshorisont", self.var_lock_horizon, "timmar",
             "Operationer som startar inom så många timmar från nu flyttas inte.",
             "Skyddar det som redan är förberett i verkstaden. Standard 4 h. "
             "0 stänger av den framtida låsningen, men operationer som redan "
             "har startat är alltid låsta. Decimaler tillåts, t.ex. 2,5."),
            ("Maxförsening", self.var_max_tardiness, "kalenderdagar",
             "En order får inte planeras så att den blir mer försenad än så här.",
             "Gäller alla kunder. Har en kund ett eget MaxLate i CustomerConfig "
             "gäller kundens värde i stället. Är ordern redan mer försenad i "
             "originalplanen får den inte bli sämre än originalet."),
        ]
        for row, (label, variable, unit, explanation, tooltip) in enumerate(param_spec):
            _help(ttk.Label(params, text=label), tooltip).grid(
                row=row, column=0, sticky="nw", pady=(3, 0))
            entry_box = ttk.Frame(params)
            entry_box.grid(row=row, column=1, sticky="nw", padx=8, pady=(3, 0))
            _help(ttk.Entry(entry_box, textvariable=variable, width=7),
                  tooltip).pack(side="left")
            ttk.Label(entry_box, text=unit).pack(side="left", padx=(4, 0))
            ttk.Label(params, text=explanation, style="Sub.TLabel",
                      wraplength=360, justify="left").grid(
                row=row, column=2, sticky="nw", pady=(3, 0))
        save_box = ttk.Frame(params)
        save_box.grid(row=len(param_spec), column=0, columnspan=3,
                      sticky="w", pady=(8, 0))
        _help(ttk.Button(save_box, text="💾 Spara inställningar",
                         command=lambda: self._save_settings(notify=True)),
              "Sparar parametrar, poängtrappa och sökvägar till nästa gång appen "
              "öppnas. Sparas även automatiskt vid körning och när appen stängs. "
              "Lösenord sparas aldrig.").pack(side="left")
        _help(ttk.Button(save_box, text="Återställ standardvärden",
                         command=self._reset_defaults),
              "Sätter parametrar och poängtrappa till standardvärdena. "
              "Sökvägar behålls.").pack(side="left", padx=(6, 0))
        ttk.Label(save_box, textvariable=self.var_settings_status,
                  style="Sub.TLabel").pack(side="left", padx=(8, 0))

        self._build_score_band_editor(settings_row)

        btns = ttk.Frame(box)
        btns.pack(fill="x", pady=(10, 2))
        self.btn_run = _help(ttk.Button(btns, text="▶  Kör omplanering",
                                        style="Run.TButton", command=self._run),
                             "Beräknar ett nytt planeringsförslag och sparar det som "
                             "Excel/CSV. Inget skrivs till SQL i detta steg.")
        self.btn_run.pack(side="left")
        self.btn_write_sql = _help(ttk.Button(
            btns, text="Bekräfta och skriv till SQL",
            command=self._write_sql_result, state="disabled"),
            "Sparar den granskade planen i SQL som en ny körning (nytt RunId). "
            "Tidigare körningar ändras inte. Du får bekräfta innan något skrivs.")
        self.btn_write_sql.pack(side="left", padx=(8, 0))
        self.btn_xlsx = ttk.Button(btns, text="Öppna Excel", state="disabled",
                                   command=lambda: self._open(self.result.xlsx_path))
        self.btn_xlsx.pack(side="left", padx=(10, 0))
        self.btn_csv = ttk.Button(btns, text="Öppna CSV", state="disabled",
                                  command=lambda: self._open(self.result.csv_path))
        self.btn_csv.pack(side="left", padx=(6, 0))
        self.btn_dir = ttk.Button(btns, text="Öppna mapp", state="disabled",
                                  command=self._open_dir)
        self.btn_dir.pack(side="left", padx=(6, 0))
        ttk.Button(btns, text="Dokumentation V8",
                   command=self._open_doc).pack(side="right")

    def _update_sql_target(self) -> None:
        try:
            sql_config.reload_config()
            fields = (sql_config.SERVER_NAME, sql_config.DATABASE, sql_config.USERNAME)
            if all(fields):
                target = f"{fields[0]} / {fields[1]} · SQL-användare {fields[2]}"
            else:
                target = "SQL-anslutning saknar server, databas eller användarnamn."
            procedure = sql_config.REFRESH_PROCEDURE
        except (OSError, ValueError, RuntimeError) as exc:
            target = f"SQL-konfigurationen är ogiltig: {exc}"
            procedure = ""
        self.lbl_sql_target.configure(text=target)
        if hasattr(self, "btn_refresh_sql"):
            self.btn_refresh_sql.configure(
                state=("normal" if self._sql_password and procedure else "disabled"))

    def _set_source_mode(self) -> None:
        if self._sql_busy:
            self.source_mode.set("sql")
            return
        if self.source_mode.get() == "sql":
            self.excel_frame.pack_forget()
            self.sql_frame.pack(fill="x")
            self.var_status.set("SQL-läge: anslut och läs in datatabeller.")
            self.btn_write_sql.configure(
                state=("normal" if self._pending_outcome is not None
                       and not self._sql_busy else "disabled"))
        else:
            self.sql_frame.pack_forget()
            self.excel_frame.pack(fill="x")
            self.var_status.set("Excel-läge: välj en arbetsbok.")
            self.btn_write_sql.configure(state="disabled")

    def _open_sql_config(self) -> None:
        if self._sql_busy:
            return
        self._update_sql_target()
        try:
            os.startfile(sql_config.CONNECTION_CONFIG_PATH)
        except OSError as exc:
            messagebox.showerror("SQL-konfiguration",
                                 f"Kunde inte öppna konfigurationsfilen:\n{exc}")

    def _connect_sql(self) -> None:
        password = self.var_sql_password.get()
        if not password:
            messagebox.showwarning("Lösenord saknas", "Ange SQL-lösenordet.")
            return
        self._save_settings()
        self._sql_password = password
        self.var_sql_password.set("")
        self._start_sql_worker("connect", password=password)

    def _refresh_sql(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        if not self._sql_password:
            messagebox.showwarning("Inte ansluten", "Anslut till SQL Server först.")
            return
        procedure = sql_config.REFRESH_PROCEDURE
        if not procedure:
            messagebox.showwarning(
                "Procedur saknas",
                "En administratör måste konfigurera refresh_procedure först.")
            return
        if not messagebox.askyesno(
                "Uppdatera källdata?",
                f"Appen kör proceduren {procedure} i databasen "
                f"{sql_config.DATABASE}. Den uppdaterar källtabellerna och "
                "ändringarna sparas (commit) när proceduren är klar.\n\n"
                f"Tidsgräns: {sql_refresh.describe_refresh_timeout(sql_config.REFRESH_TIMEOUT)}.\n"
                "Du kan avbryta med knappen ”Avbryt procedur”. Tidigare inläst "
                "data och ej sparad plan måste läsas in/köras på nytt efteråt.\n\n"
                "Vill du fortsätta?"):
            return
        self._start_sql_worker("refresh")

    def _cancel_refresh(self) -> None:
        cursor = self._refresh_cursor
        if self._sql_busy != "refresh" or cursor is None:
            return
        if not messagebox.askyesno(
                "Avbryta proceduren?",
                "Proceduren avbryts och appen begär rollback.\n\n"
                "Om proceduren själv hunnit göra commit kan delar av uppdateringen "
                "redan vara sparade – kontrollera i SQL innan du kör igen.\n\n"
                "Avbryta nu?"):
            return
        self._refresh_cancel_requested = True
        self.btn_cancel_refresh.configure(state="disabled")
        self._sql_phase = "Avbrott begärt – väntar på att SQL Server bekräftar"
        self._log("Avbrott av proceduren begärt av användaren.")
        try:
            cursor.cancel()
        except Exception as exc:  # noqa: BLE001
            self._log(f"Avbrottet kunde inte skickas till SQL Server: {exc}")

    def _load_sql(self) -> None:
        if not self._sql_password:
            messagebox.showwarning("Inte ansluten", "Anslut till SQL Server först.")
            return
        self._sql_source = None
        self._pending_outcome = None
        self._pending_started = None
        self.btn_write_sql.configure(state="disabled")
        self.btn_run.configure(state="disabled")
        self._start_sql_worker("load")

    def _start_sql_worker(self, action: str, password: Optional[str] = None) -> None:
        if self.worker and self.worker.is_alive():
            return
        self._sql_busy = action
        self._sql_started_at = time.monotonic()
        self._sql_phase = "Ansluter och kontrollerar SQL-målet"
        for button in (self.btn_connect_sql, self.btn_refresh_sql, self.btn_load_sql,
                       self.btn_run, self.btn_write_sql, self.btn_sql_config):
            button.configure(state="disabled")
        self.btn_cancel_refresh.configure(
            state="normal" if action == "refresh" else "disabled")
        self.progress.start(14)
        self.sql_progress.pack(fill="x", pady=(4, 0))
        self.sql_progress.start(14)
        self.nb.select(0)
        if action == "refresh":
            self._sql_source = None
            self._pending_outcome = None
            self._pending_started = None
            self._refresh_cancel_requested = False
            self._log(
                f"Uppdatering begärd: {sql_config.REFRESH_PROCEDURE} – "
                f"{sql_refresh.describe_refresh_timeout(sql_config.REFRESH_TIMEOUT)}. "
                "Vänta tills steget avslutas eller avbryt med ”Avbryt procedur”.")
        self._update_sql_progress()
        self.var_status.set({
            "connect": "Ansluter till SQL Server …",
            "refresh": "Uppdaterar källdata via procedur …",
            "load": "Läser källtabeller från SQL Server …",
            "write": "Skriver resultat till SQL Server …",
        }[action])
        outcome = self._pending_outcome if action == "write" else None
        started = self._pending_started if action == "write" else None
        expected_identity = self._sql_identity if action != "connect" else None
        self.worker = threading.Thread(
            target=self._sql_worker,
            args=(action, password or self._sql_password, outcome, started,
                  expected_identity),
            daemon=True)
        self.worker.start()

    def _sql_worker(self, action: str, password: Optional[str],
                    outcome: Optional[core.PlanOutcome],
                    started: Optional[datetime],
                    expected_identity: Optional[tuple[str, str]]) -> None:
        conn = None
        try:
            if not password:
                raise ValueError("SQL-lösenord saknas; anslut igen.")
            conn = sql_db.connect(password)
            identity = sql_db.server_identity(conn)
            if action != "connect" and identity != expected_identity:
                raise RuntimeError(
                    "SQL-server eller databas har ändrats sedan anslutningen. "
                    "Anslut igen och läs in tabellerna på nytt.")
            if action == "connect":
                self.queue.put(("sql_connected", identity))
            elif action == "refresh":
                sql_refresh.run_refresh_procedure(
                    conn,
                    lambda text: self.queue.put(
                        ("log", text.replace(password, "<redacted>"))),
                    lambda text: self.queue.put(("sql_phase", text)),
                    lambda cursor: setattr(self, "_refresh_cursor", cursor))
                self.queue.put(("sql_refreshed", None))
            elif action == "load":
                src = sql_source.load_source_sql(
                    conn, lambda text: self.queue.put(("log", text)))
                self.queue.put(("sql_loaded", (src, identity)))
            elif action == "write":
                if outcome is None or started is None:
                    raise RuntimeError("Det finns ingen färdig V8-plan att skriva.")
                run_id = sql_sink.write_outcome(
                    conn, outcome, started,
                    lambda text: self.queue.put(("log", text)))
                self.queue.put(("sql_written", run_id))
            else:
                raise ValueError(f"Okänd SQL-åtgärd: {action}")
        except Exception as exc:  # noqa: BLE001
            self.queue.put(("sql_error", (action, exc, traceback.format_exc())))
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception as close_exc:  # noqa: BLE001
                    close_message = str(close_exc).replace(password or "\0", "<redacted>")
                    self.queue.put(
                        ("log", f"SQL-anslutningen kunde inte stängas rent: {close_message}"))

    def _finish_sql_action(self, action: str, payload=None) -> None:
        self.progress.stop()
        self.sql_progress.stop()
        self.sql_progress.pack_forget()
        self._sql_busy = None
        self._refresh_cursor = None
        self.btn_cancel_refresh.configure(state="disabled")
        self.btn_connect_sql.configure(state="normal")
        self.btn_sql_config.configure(state="normal")
        connected = bool(self._sql_password)
        self.btn_load_sql.configure(state="normal" if connected else "disabled")
        self.btn_refresh_sql.configure(
            state=("normal" if connected and sql_config.REFRESH_PROCEDURE else "disabled"))
        self.btn_run.configure(state="normal")
        self.btn_write_sql.configure(
            state=("normal" if self._pending_outcome is not None else "disabled"))
        if action == "sql_connected":
            self._sql_identity = payload
            self._sql_source = None
            self._pending_outcome = None
            self._pending_started = None
            self.btn_write_sql.configure(state="disabled")
            self.btn_run.configure(
                state="disabled" if self.source_mode.get() == "sql" else "normal")
            self.lbl_sql_status.configure(
                text=f"Ansluten: {payload[0]} · {payload[1]}")
            self.var_status.set(
                "Ansluten. Läs in SQL-tabeller innan du kör omplaneringen.")
        elif action == "sql_refreshed":
            self._sql_source = None
            self._pending_outcome = None
            self._pending_started = None
            self.btn_write_sql.configure(state="disabled")
            self.btn_run.configure(
                state="disabled" if self.source_mode.get() == "sql" else "normal")
            self.lbl_sql_status.configure(
                text="Källdata uppdaterad. Läs in tabellerna innan omplaneringen körs.")
            self.var_status.set("Proceduren är klar; källdata behöver läsas in.")
            messagebox.showinfo(
                "Källdata uppdaterad",
                "Proceduren har körts och transaktionen är committad.\n"
                "Läs tabeller från SQL igen innan du kör omplaneringen.")
        elif action == "sql_loaded":
            src, identity = payload
            self._sql_source = src
            self._sql_identity = identity
            counts = (f"{len(src.baseline)} baslinjerader · "
                      f"{len(src.operations)} operationsrader")
            self.lbl_sql_status.configure(text=f"Data inläst: {counts}")
            self.btn_run.configure(state="normal")
            self.var_status.set("SQL-data inläst. Kör omplaneringen när du är redo.")
            self.nb.select(0)
        elif action == "sql_written":
            self.btn_write_sql.configure(state="disabled")
            self.var_status.set(f"Resultat sparat i SQL · RunId {payload}")
            self._log(f"SQL-resultatet skrevs transaktionellt. RunId: {payload}")
            messagebox.showinfo("SQL-skrivning klar",
                                f"Resultatet är sparat i SQL.\nRunId: {payload}")

    def _update_sql_progress(self) -> None:
        if self._sql_busy is None:
            return
        elapsed = int(time.monotonic() - self._sql_started_at)
        text = f"{self._sql_phase} · {elapsed // 60:02d}:{elapsed % 60:02d}"
        if self._sql_busy == "refresh":
            text += (f" · {sql_refresh.describe_refresh_timeout(sql_config.REFRESH_TIMEOUT)}"
                     " (förfluten tid, inte procent klart)")
        self.lbl_sql_status.configure(text=text)

    def _write_sql_result(self) -> None:
        if self._pending_outcome is None or self._pending_started is None:
            messagebox.showwarning("Ingen plan", "Kör en SQL-plan innan du skriver resultat.")
            return
        if not self._sql_password:
            messagebox.showwarning("Inte ansluten", "Anslut till SQL Server igen.")
            return
        if not messagebox.askyesno(
                "Skriv omplaneringsresultat?",
                "V8 kommer att lägga till körningen och resultatraderna i "
                f"{sql_config.TBL_RUN} och {sql_config.TBL_RESULT} i en transaktion.\n\n"
                "Föregående körningar ändras inte. Fortsätta?"):
            return
        self._start_sql_worker("write")

    def _on_close(self) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showwarning(
                "Körning pågår",
                "Vänta tills körningen och eventuell commit/rollback har avslutats "
                "innan du stänger appen.")
            return
        self._save_settings(quiet=True)
        self.var_sql_password.set("")
        self._sql_password = None
        self.destroy()

    def _build_score_band_editor(self, parent: ttk.Frame) -> None:
        editor = ttk.LabelFrame(parent, text="3. Poängtrappa – hur allvarlig är en försening?",
                                padding=(8, 5))
        editor.pack(side="left", fill="both", expand=True)
        ttk.Label(editor, style="Sub.TLabel", wraplength=540, justify="left",
                  text="Varje rad ger poäng för ett antal dagar efter leveransdatum. "
                       "Högre poäng = viktigare att undvika. Motorn försöker minimera "
                       "summan av poäng × kundvikt. Negativa dagar = klar före "
                       "leveransdatum; ge dem poäng om order inte ska bli klara för "
                       "tidigt (lägre än förseningspoängen).").pack(
            anchor="w", pady=(0, 3))
        headings = ttk.Frame(editor)
        headings.pack(fill="x")
        for column, (label, tip) in enumerate((
                ("Från dag", "Första dagen som raden gäller för (ingår). Negativt "
                             "tal = dagar före leveransdatum, t.ex. -10."),
                ("Till dag", "Sista dagen som raden gäller för (ingår). "
                             "Tomt = obegränsat; endast på sista raden."),
                ("Poäng", "Poäng när ordern blir klar inom intervallet. "
                          "Multipliceras med kundvikten. Rader helt före dag 0 "
                          "(tidigt klar) måste ha lägre poäng än alla förseningsrader."))):
            _help(ttk.Label(headings, text=label, width=10), tip).grid(
                row=0, column=column, sticky="w", padx=(0, 8))
        _help(ttk.Button(headings, text="+ Lägg till",
                         command=self._add_score_band),
              "Delar upp sista (obegränsade) raden: den får ett slut och en ny "
              "obegränsad rad läggs till efter.").grid(row=0, column=3, sticky="w")
        _help(ttk.Button(headings, text="⇅ Sortera och rätta",
                         command=self._sort_score_bands),
              "Sorterar raderna efter Från dag och gör sista raden obegränsad. "
              "Luckor, överlapp och för höga tidighetspoäng rättas inte "
              "automatiskt utan visas med radnummer."
              ).grid(row=0, column=4, sticky="w", padx=(6, 0))
        self.score_band_rows = ttk.Frame(editor)
        self.score_band_rows.pack(fill="x", pady=(2, 0))
        ttk.Label(editor, style="Sub.TLabel", wraplength=540, justify="left",
                  text="Regler: stigande ordning utan luckor eller överlapp, dag 0 måste "
                       "ingå, sista raden har tomt Till. Tidigare än första raden får "
                       "första radens poäng. Ändpunkter ingår; sena dagar avrundas "
                       "uppåt. ▲ ▼ flyttar en rad.").pack(anchor="w", pady=(3, 0))
        self._render_score_bands()

    def _render_score_bands(self) -> None:
        for child in self.score_band_rows.winfo_children():
            child.destroy()
        last = len(self.score_band_vars) - 1
        for index, variables in enumerate(self.score_band_vars):
            for column in range(3):
                ttk.Entry(self.score_band_rows, textvariable=variables[column],
                          width=10).grid(row=index, column=column, sticky="w",
                                         padx=(0, 8), pady=1)
            ttk.Button(self.score_band_rows, text="▲", width=3, style="Row.TButton",
                       state="normal" if index > 0 else "disabled",
                       command=lambda row=index: self._move_score_band(row, -1)
                       ).grid(row=index, column=3, sticky="w", pady=1)
            ttk.Button(self.score_band_rows, text="▼", width=3, style="Row.TButton",
                       state="normal" if index < last else "disabled",
                       command=lambda row=index: self._move_score_band(row, 1)
                       ).grid(row=index, column=4, sticky="w", pady=1)
            ttk.Button(self.score_band_rows, text="−", width=3, style="Row.TButton",
                       command=lambda row=index: self._remove_score_band(row)
                       ).grid(row=index, column=5, sticky="w", padx=(4, 0), pady=1)

    def _move_score_band(self, index: int, step: int) -> None:
        target = index + step
        if not 0 <= target < len(self.score_band_vars):
            return
        rows = self.score_band_vars
        rows[index], rows[target] = rows[target], rows[index]
        self._render_score_bands()

    def _sort_score_bands(self) -> None:
        rows = []
        for number, variables in enumerate(self.score_band_vars, start=1):
            values = [value.get().strip() for value in variables]
            try:
                lower = float(values[0].replace(",", "."))
                upper = (None if values[1] == ""
                         else float(values[1].replace(",", ".")))
            except ValueError:
                messagebox.showerror(
                    "Poängtrappa",
                    f"Rad {number}: Från och Till måste vara tal innan raderna "
                    "kan sorteras.")
                return
            rows.append((lower, upper, values))
        rows.sort(key=lambda row: row[0])
        changes = []
        if rows[-1][2][1] != "":
            changes.append(f"Till på sista raden ({rows[-1][2][1]}) tömdes så att "
                           "raden gäller alla längre förseningar.")
            rows[-1][2][1] = ""
        self.score_band_vars = [[tk.StringVar(value=value) for value in row[2]]
                                for row in rows]
        self._render_score_bands()
        try:
            core.validate_tardiness_score_bands(
                [[value.get() for value in row] for row in self.score_band_vars])
        except (ValueError, OverflowError) as exc:
            messagebox.showwarning(
                "Poängtrappa sorterad – rätta kvarvarande fel",
                "\n".join(["Raderna är sorterade."] + changes
                          + ["", f"Kvar att rätta: {exc}"]))
            return
        messagebox.showinfo(
            "Poängtrappa klar",
            "\n".join(["Raderna är sorterade och trappan är giltig."] + changes))

    def _add_score_band(self) -> None:
        lower, upper, score = self.score_band_vars[-1]
        try:
            last_day = int(upper.get()) if upper.get().strip() else int(lower.get())
            if float(upper.get() or lower.get()) != last_day:
                raise ValueError
        except ValueError:
            messagebox.showerror("Ogiltigt intervall",
                                 "Sista intervallets Från/Till måste vara heltal.")
            return
        next_day = last_day + 1
        upper.set(str(last_day))
        self.score_band_vars.append([
            tk.StringVar(value=str(next_day)),
            tk.StringVar(value=""),
            tk.StringVar(value=score.get()),
        ])
        self._render_score_bands()

    def _remove_score_band(self, index: int) -> None:
        if len(self.score_band_vars) <= 1:
            messagebox.showwarning("Poängtrappa",
                                   "Minst ett intervall måste finnas kvar.")
            return
        removed = self.score_band_vars.pop(index)
        if index == 0:
            self.score_band_vars[0][0].set(removed[0].get())
        else:
            self.score_band_vars[index - 1][1].set(removed[1].get())
        self._render_score_bands()

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
        sql_mode = self.source_mode.get() == "sql"
        if sql_mode:
            if self._sql_source is None:
                messagebox.showwarning(
                    "SQL-data saknas",
                    "Anslut, kör eventuell uppdateringsprocedur och läs tabellerna först.")
                return
            path = "AI_omplanering_V8.xlsx"
        elif not path:
            messagebox.showwarning("Ingen fil vald",
                                   "Välj först en arbetsbok (.xlsx).")
            return
        elif not os.path.isfile(path):
            messagebox.showerror("Filen saknas", f"Hittar inte:\n{path}")
            return
        if self.worker and self.worker.is_alive():
            return

        try:
            score_bands = core.validate_tardiness_score_bands(
                [[value.get() for value in row] for row in self.score_band_vars])
            policy = core.ClusterPolicy(
                window_days=max(0, int(float(self.var_window.get().replace(",", ".")))),
                budget_days_per_hour=0.0,
                global_max_tardiness_days=core.validate_max_tardiness_days(
                    self.var_max_tardiness.get()),
                score_bands=score_bands,
            )
        except (ValueError, OverflowError) as exc:
            messagebox.showerror(
                "Ogiltig planeringspolicy",
                f"{exc}\n\nKontrollera klusterfönster (heltal ≥ 0), maxförsening och "
                "poängtrappan. Tips: ⇅ Sortera och rätta ordnar trappan automatiskt.")
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

        out = self.var_output.get().strip() or self._default_output_dir()
        self._pending_outcome = None
        self._pending_started = None
        self._save_settings()

        self._log_clear()
        self.result = None
        self.btn_write_sql.configure(state="disabled")
        for b in (self.btn_xlsx, self.btn_csv, self.btn_dir):
            b.configure(state="disabled")
        self.btn_run.configure(state="disabled")
        self.progress.start(14)
        self.var_status.set("Kör omplanering …")
        self.nb.select(0)

        if sql_mode:
            self.worker = threading.Thread(
                target=self._work_sql,
                args=(self._sql_source, path, out, policy, lock_horizon_hours),
                daemon=True)
        else:
            self.worker = threading.Thread(
                target=self._work,
                args=(path, out, policy, lock_horizon_hours),
                daemon=True)
        self.worker.start()

    @staticmethod
    def _default_output_dir() -> str:
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")

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

    def _work_sql(self, src: core.SourceData, path: str, out: str,
                  policy: core.ClusterPolicy, lock_horizon_hours: float) -> None:
        """Plan from the captured SQL snapshot and write local Excel/CSV files."""
        started = datetime.now()
        try:
            log = lambda message: self.queue.put(("log", message))
            log(f"=== AI Omplanering V{core.VERSION} · SQL-indata ===")
            for warning in src.warnings:
                log("VARNING: " + warning)
            outcome = core.compute_plan(
                src, policy=policy, log=log,
                lock_horizon_hours=lock_horizon_hours)
            log("Skriver Excel- och CSV-resultat …")
            xlsx_path, csv_path = core.write_outputs(
                src, outcome.result, outcome.summary, path, out,
                outcome.run_ts, log)
            result = core.RunResult(
                xlsx_path, csv_path, outcome.result, outcome.summary,
                outcome.stats, outcome.warnings, [])
            self.queue.put(("sql_plan_done", (result, outcome, started)))
        except Exception as exc:  # noqa: BLE001
            self.queue.put(("error", (exc, traceback.format_exc())))

    def _pump(self) -> None:
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                if kind == "log":
                    self._log(payload)
                elif kind == "sql_phase":
                    self._sql_phase = payload
                elif kind == "done":
                    self._finish(payload)
                elif kind == "sql_connected":
                    self._finish_sql_action(kind, payload)
                elif kind == "sql_refreshed":
                    self._finish_sql_action(kind, payload)
                elif kind == "sql_loaded":
                    self._finish_sql_action(kind, payload)
                elif kind == "sql_written":
                    self._finish_sql_action(kind, payload)
                elif kind == "sql_plan_done":
                    result, outcome, started = payload
                    self._pending_outcome = outcome
                    self._pending_started = started
                    self._finish(result)
                    if self.source_mode.get() == "sql":
                        self.btn_write_sql.configure(state="normal")
                        self.var_status.set(
                            "Plan klar. Granska sammanfattning och Excel-fil före SQL-skrivning.")
                        self.lbl_sql_status.configure(
                            text="Plan klar och exporterad lokalt. SQL-tabellerna är ännu inte ändrade.")
                elif kind == "sql_error":
                    action, exc, tb = payload
                    self._sql_busy = None
                    self._refresh_cursor = None
                    cancelled = (action == "refresh"
                                 and getattr(self, "_refresh_cancel_requested", False))
                    self._refresh_cancel_requested = False
                    self.btn_cancel_refresh.configure(state="disabled")
                    self.progress.stop()
                    self.sql_progress.stop()
                    self.sql_progress.pack_forget()
                    self.btn_connect_sql.configure(state="normal")
                    self.btn_sql_config.configure(state="normal")
                    self.btn_run.configure(state="normal")
                    password_to_redact = self._sql_password or "\0"
                    if action == "connect":
                        self._sql_password = None
                        self._sql_identity = None
                    connected = bool(self._sql_password)
                    self.btn_load_sql.configure(
                        state="normal" if connected else "disabled")
                    self.btn_refresh_sql.configure(
                        state=("normal" if connected and sql_config.REFRESH_PROCEDURE
                               else "disabled"))
                    self.btn_write_sql.configure(
                        state=("normal" if self._pending_outcome is not None
                               else "disabled"))
                    safe_message = str(exc).replace(
                        password_to_redact, "<redacted>")
                    refresh_timeout = (
                        action == "refresh" and not cancelled and bool(exc.args)
                        and exc.args[0] in ("HYT00", "HYT01"))
                    if cancelled:
                        safe_message = (
                            "Proceduren avbröts av dig och appen begärde rollback.\n\n"
                            "Om proceduren själv hann göra commit kan delar av "
                            "uppdateringen redan vara sparade. Kontrollera i SQL innan "
                            "du kör igen. Tekniskt meddelande:\n" + safe_message)
                    elif refresh_timeout:
                        safe_message += (
                            "\n\nProceduren nådde tidsgränsen refresh_timeout och "
                            "avbröts. Appen har begärt rollback men timeout bevisar "
                            "inte att alla sidoeffekter är återställda – kontrollera "
                            "SQL-loggen och serverns sessioner innan du kör igen.\n\n"
                            "Sätt refresh_timeout till 0 i connection.json för att "
                            "vänta tills SQL Server svarar, och starta om appen.")
                    self._log(f"SQL-FEL ({action}): {safe_message}")
                    self._log(tb.replace(password_to_redact, "<redacted>"))
                    if cancelled:
                        status_text = "Proceduren avbröts. Kontrollera SQL innan omkörning."
                        bar_text = "SQL-procedur avbruten av användaren – rollback begärd."
                    elif refresh_timeout:
                        status_text = ("Proceduren fick timeout. Kontrollera "
                                       "SQL-servern före omkörning.")
                        bar_text = ("SQL-procedur: timeout – körningen är inte "
                                    "bekräftad som lyckad.")
                    else:
                        status_text = "SQL-åtgärden misslyckades."
                        bar_text = "SQL-åtgärden avbröts med fel."
                    self.lbl_sql_status.configure(text=status_text)
                    self.var_status.set(bar_text)
                    messagebox.showerror(
                        "Procedur avbruten" if cancelled else "SQL-fel", safe_message)
                elif kind == "error":
                    self._fail(*payload)
        except queue.Empty:
            pass
        self._update_sql_progress()
        self.after(120, self._pump)

    def _finish(self, res: core.RunResult) -> None:
        self.result = res
        self.progress.stop()
        self.btn_run.configure(state="normal")
        for b in (self.btn_xlsx, self.btn_csv, self.btn_dir):
            b.configure(state="normal")
        self.btn_write_sql.configure(
            state=("normal" if self.source_mode.get() == "sql"
                   and self._pending_outcome is not None else "disabled"))

        s = res.stats
        self.kpis["rows"].set(s["rows"], f"{s['machines']} produktionsgrupper")
        delta = s["red_before"] - s["red_after"]
        self.kpis["red"].set(f"{s['red_before']} → {s['red_after']}",
                             f"{delta:+d} order", "#1a7f37" if delta > 0 else C_MUTED)
        self.kpis["yellow"].set(f"{s['yellow_before']} → {s['yellow_after']}",
                                "marginal exakt 1 dygn")
        gdelta = s["green_after"] - s["green_before"]
        self.kpis["green"].set(f"{s['green_before']} → {s['green_after']}",
                               f"{gdelta:+d} order · kundviktad prioritet "
                               f"{s['green_weight_before']:g} → {s['green_weight_after']:g}",
                               "#1a7f37" if gdelta > 0 else C_MUTED)

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
        doc = resource_path("documentation_v8.html")
        if os.path.exists(doc):
            self._open(doc)
        else:
            messagebox.showinfo("Dokumentation saknas",
                                "documentation_v8.html hittades inte bredvid appen.")

    def _choose_excel_workbook(self) -> None:
        self.source_mode.set("excel")
        self._set_source_mode()
        self._pick_input()

    def _contact_support(self) -> None:
        address = "support@dizparc.se"
        try:
            opened = webbrowser.open(
                f"mailto:{address}?subject=AI%20Omplanering%20V8", new=1)
        except webbrowser.Error:
            opened = False
        if not opened:
            messagebox.showinfo("Dizparc support", address)

    def _show_about(self) -> None:
        messagebox.showinfo(
            "Om AI Omplanering V8",
            f"AI Omplanering V8 · version {core.VERSION}\n\n"
            "Planeringsstöd för Operation 10 i Jeeves ERP. "
            "Läs underlag från Excel eller SQL Server, granska ett "
            "planeringsförslag och exportera Excel/CSV. SQL-resultat skrivs "
            "bara efter uttrycklig bekräftelse.\n\n"
            "Dokumentation: Hjälp → Dokumentation V8\n"
            "Support: support@dizparc.se"
        )

    # -- installningar ----------------------------------------------------

    def _load_settings(self) -> None:
        # Återställ standard även vid saknad fil, felaktig JSON eller ogiltigt värde.
        invalid_values = False
        self.var_lock_horizon.set(str(core.LOCK_HORIZON_HOURS))
        self.var_window.set(str(core.CLUSTER_WINDOW_DAYS))
        self.var_max_tardiness.set(str(core.DEFAULT_MAX_TARDINESS_DAYS))
        self.score_band_vars = [
            [tk.StringVar(value=str(lower)),
             tk.StringVar(value="" if upper is None else str(upper)),
             tk.StringVar(value=str(score))]
            for lower, upper, score in core.DEFAULT_TARDINESS_SCORE_BANDS
        ]
        try:
            with open(SETTINGS_FILE, encoding="utf-8") as fh:
                data = json.load(fh)
            if not isinstance(data, dict):
                invalid_values = True
                data = {}
            self.var_input.set(data.get("input", ""))
            self.var_output.set(data.get("output", ""))
            try:
                lock_horizon_hours = core.validate_lock_horizon_hours(
                    str(data.get("lock_horizon_hours", core.LOCK_HORIZON_HOURS)))
                self.var_lock_horizon.set(str(lock_horizon_hours))
            except (TypeError, ValueError, OverflowError):
                invalid_values = True
            try:
                window_days = max(0, int(float(str(data.get(
                    "window_days", core.CLUSTER_WINDOW_DAYS)).replace(",", "."))))
                self.var_window.set(str(window_days))
            except (TypeError, ValueError, OverflowError):
                invalid_values = True
            try:
                self.var_max_tardiness.set(str(core.validate_max_tardiness_days(
                    data.get("max_tardiness_days", core.DEFAULT_MAX_TARDINESS_DAYS))))
                saved_bands = data.get(
                    "score_bands", core.DEFAULT_TARDINESS_SCORE_BANDS)
                normalized_bands = core.validate_tardiness_score_bands(saved_bands)
                self.score_band_vars = [
                    [tk.StringVar(value=str(lower)),
                     tk.StringVar(value="" if upper is None else str(upper)),
                     tk.StringVar(value=str(score))]
                    for lower, upper, score in normalized_bands
                ]
                if hasattr(self, "score_band_rows"):
                    self._render_score_bands()
            except (TypeError, ValueError, OverflowError):
                invalid_values = True
        except FileNotFoundError:
            pass
        except (OSError, ValueError):
            messagebox.showwarning(
                "Inställningar kunde inte läsas",
                f"V8-inställningarna kunde inte läsas från {SETTINGS_FILE}. "
                "Standardvärden används.")
        if invalid_values:
            messagebox.showwarning(
                "Ogiltiga sparade inställningar",
                "Ett eller flera sparade planeringsvärden var ogiltiga. "
                "Standardvärden används för de berörda fälten.")
        if hasattr(self, "score_band_rows"):
            self._render_score_bands()
        if not self.var_input.get():
            here = os.path.dirname(os.path.abspath(__file__))
            names = sorted(os.listdir(here),
                           key=lambda name: ("v7" not in name.lower(), name.lower()))
            for name in names:
                if name.lower().endswith(".xlsx") and "resultat" not in name.lower():
                    self.var_input.set(os.path.join(here, name))
                    self.var_output.set(os.path.join(here, "output"))
                    break

    def _reset_defaults(self) -> None:
        if not messagebox.askyesno(
                "Återställ standardvärden?",
                "Klusterfönster, låshorisont, maxförsening och poängtrappa sätts till "
                "standardvärdena och sparas. Sökvägar behålls.\n\nFortsätta?"):
            return
        self.var_window.set(str(core.CLUSTER_WINDOW_DAYS))
        self.var_lock_horizon.set(str(core.LOCK_HORIZON_HOURS))
        self.var_max_tardiness.set(str(core.DEFAULT_MAX_TARDINESS_DAYS))
        self.score_band_vars = [
            [tk.StringVar(value=str(lower)),
             tk.StringVar(value="" if upper is None else str(upper)),
             tk.StringVar(value=str(score))]
            for lower, upper, score in core.DEFAULT_TARDINESS_SCORE_BANDS
        ]
        self._render_score_bands()
        self._save_settings(notify=True)

    def _save_settings(self, notify: bool = False, quiet: bool = False) -> bool:
        """Sparar giltiga fält. Ogiltiga fält behåller sitt senast sparade värde.

        Returnerar True om alla fält kunde sparas."""
        try:
            with open(SETTINGS_FILE, encoding="utf-8") as fh:
                data = json.load(fh)
            if not isinstance(data, dict):
                data = {}
        except (OSError, ValueError):
            data = {}
        data["input"] = self.var_input.get()
        data["output"] = self.var_output.get()
        problems = []
        validators = (
            ("window_days", "Klusterfönster",
             lambda: max(0, int(float(self.var_window.get().replace(",", "."))))),
            ("lock_horizon_hours", "Låshorisont",
             lambda: core.validate_lock_horizon_hours(self.var_lock_horizon.get())),
            ("max_tardiness_days", "Maxförsening",
             lambda: core.validate_max_tardiness_days(self.var_max_tardiness.get())),
            # Samma normalisering som vid körning; sparas endast från UI-tråden.
            ("score_bands", "Poängtrappa",
             lambda: [list(band) for band in core.validate_tardiness_score_bands(
                 [[value.get() for value in row] for row in self.score_band_vars])]),
        )
        for key, label, read in validators:
            try:
                data[key] = read()
            except (TypeError, ValueError, OverflowError) as exc:
                problems.append(f"• {label}: {exc}")
        try:
            os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
            temporary = SETTINGS_FILE + ".tmp"
            with open(temporary, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, allow_nan=False, indent=2)
                fh.write("\n")
            os.replace(temporary, SETTINGS_FILE)
        except (OSError, TypeError, ValueError, OverflowError) as exc:
            if not quiet:
                messagebox.showerror(
                    "Inställningar kunde inte sparas",
                    f"V8-inställningarna sparades inte:\n{exc}")
            return False
        status = getattr(self, "var_settings_status", None)
        if problems:
            if status is not None:
                status.set(f"Delvis sparat {datetime.now():%H:%M} – se meddelande")
            if not quiet:
                messagebox.showwarning(
                    "Inställningar delvis sparade",
                    "Övriga inställningar sparades, men dessa fält är ogiltiga och "
                    "behåller sitt senast sparade värde:\n\n" + "\n".join(problems))
            return False
        if status is not None:
            status.set(f"✓ Sparat {datetime.now():%H:%M}")
        if notify:
            messagebox.showinfo(
                "Inställningar sparade",
                f"Inställningarna används nästa gång appen öppnas.\n\n{SETTINGS_FILE}")
        return True


def main() -> None:
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()