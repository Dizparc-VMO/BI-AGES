# -*- coding: utf-8 -*-
"""AI Omplanering – fristående beräkningsmotor V7.

V5:s kalender-, sekvenserings-, klustrings-, ruttnings- och förseningsstaksregler
V5/V6:s kalender-, sekvenserings-, klustrings- och ruttningsregler bevaras.
V7 tillför kundviktad poäng och konfigurerbara absoluta förseningsgränser.
Sökningen är heuristisk, inte globalt optimal.
"""
from __future__ import annotations

import bisect
import csv
import math
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import pandas as pd

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

VERSION = "7.0"
TZ_NAME = "Europe/Stockholm"
EXCEL_EPOCH = pd.Timestamp("1899-12-30")
SHEET_BASELINE = "tblSTGetAoColorCodeLis"
SHEET_OPERATIONS = "tblSTAllOperationsForAoNr"
SHEET_CALENDAR = "tblSTGetDateCalenderWorkingTime"
SHEET_PRIO = "tblSTProductionGroupPrioOnItem"
SHEET_CUSTOMER_CONFIG = "CustomerConfig"
SHEET_RESULT = "tblAIAnglysisGetAoColorCodeList"
SHEET_SUMMARY = "AI_Sammanfattning"
SOURCE_SHEETS = [SHEET_BASELINE, SHEET_OPERATIONS, SHEET_CALENDAR, SHEET_PRIO]
COLOR_CODES = {
    "Grön": "#00ff00", "Röd": "#FF4500", "Gul": "#ffff66",
    "Blå": "#66b3ff", "Ljusblå": "#add8e6", "Okänd": "#cfd6d8",
}
KNOWN_COLORS = {"Grön", "Röd", "Gul", "Blå", "Ljusblå"}
GREEN_MARGIN_DAYS = 1
LOCK_HORIZON_HOURS = 4
DEFAULT_TARDINESS_SCORE_BANDS = (
    (-99, 0, 1.0), (1, 2, 2.0), (3, 4, 4.0),
    (5, 7, 9.0), (8, 9, 10.0), (10, None, 20.0),
)
DEFAULT_MAX_TARDINESS_DAYS = 10.0
DEFAULT_CUSTOMER_WEIGHT = 1.0
CAP_EPSILON_DAYS = 1e-9
TEMPLATE_COLUMNS = [
    "AoNr", "AoPos", "OpNr", "ProdGr", "ArtNr", "AI_ProdGr",
    "Orginal_AoStartDatTid", "Orginal_AoSlutDatTid", "Orginal_TiSlutDat",
    "Orginal_ColorCode", "Orginal_ColorName", "Orginal_OpkoPrioritet",
    "AI_AoStartDatTid", "AI_AoSlutDatTid", "AI_TiSlutDat", "AI_ColorCode",
    "AI_ColorName", "AI_OpkoPrioritet", "AI_LogCreatDateTime", "AI_Kommentar",
]
EXTRA_COLUMNS = [
    "Orginal_OrdBerLevDat", "Orginal_TardinessScore", "AI_TardinessScore",
    "AI_CapExcessDygn", "KundOrderNr", "Kundnr", "Kundvikt",
    "MaxFörseningsdagar", "Orginal_WeightedTardinessScore",
    "AI_WeightedTardinessScore",
]
DATE_COLUMNS = [
    "Orginal_AoStartDatTid", "Orginal_AoSlutDatTid", "Orginal_TiSlutDat",
    "Orginal_OrdBerLevDat", "AI_AoStartDatTid", "AI_AoSlutDatTid",
    "AI_TiSlutDat", "AI_LogCreatDateTime",
]
EXCEL_DATE_FORMAT = "yyyy-mm-dd hh:mm"
CSV_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
EPS_SECONDS = 30
MAX_ROUTING_PASSES = 4
CLUSTER_WINDOW_DAYS = 30
DELAY_IN_WORKDAYS = False
COMPANY_CALENDAR = "foretag"
DELAY_CALENDAR: object = COMPANY_CALENDAR
PROTECT_MARGIN_DAYS = 0
TARDINESS_BUDGET_PER_SETUP_HOUR = 0.0
LogFn = Callable[[str], None]


def _noop(_msg: str) -> None:
    pass


def validate_lock_horizon_hours(value) -> float:
    """Returnera ändliga, icke-negativa timmar; acceptera decimalpunkt/-komma.

    Bool och icke-numeriska värden avvisas. Gränsen är datetime:s hela
    representerbara datumspann, inte en godtycklig verksamhetsgräns. Dessutom
    kontrolleras timedelta-konstruktionen. Körningen kontrollerar separat att
    horisonten kan adderas till just dess NOW_Stockholm.
    """
    message = (
        "Låshorisonten måste vara ett ändligt, icke-negativt antal timmar "
        "(t.ex. 4 eller 2,5) som ryms inom datumintervallet."
    )
    if isinstance(value, bool):
        raise ValueError(message)
    try:
        hours = float(value.strip().replace(",", ".") if isinstance(value, str) else value)
        if not math.isfinite(hours) or hours < 0:
            raise ValueError(message)
        duration = timedelta(hours=hours)
        if duration > datetime.max - datetime.min:
            raise ValueError(message)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(message) from exc
    return hours


def _finite_nonnegative(value, label: str, allow_zero: bool = True) -> float:
    message = f"{label} måste vara ett ändligt " + (
        "positivt" if not allow_zero else "icke-negativt") + " tal."
    try:
        number = float(str(value).strip().replace(",", "."))
    except (TypeError, ValueError) as exc:
        raise ValueError(message) from exc
    if not math.isfinite(number) or number < 0 or (not allow_zero and number == 0):
        raise ValueError(message)
    return number


def validate_max_tardiness_days(value) -> float:
    return _finite_nonnegative(value, "Maxförseningen")


def validate_customer_weight(value) -> float:
    return _finite_nonnegative(value, "Kundvikten", allow_zero=False)


def validate_tardiness_score_bands(bands) -> tuple:
    if not isinstance(bands, (list, tuple)) or not bands:
        raise ValueError("Poängtrappan måste innehålla minst ett intervall.")

    parsed = []
    for index, band in enumerate(bands):
        if not isinstance(band, (list, tuple)) or len(band) != 3:
            raise ValueError("Varje intervall måste ha Från, Till och Poäng.")
        lower_value, upper_value, score_value = band

        def day_bound(value, label):
            if isinstance(value, bool):
                raise ValueError(f"{label} måste vara ett helt antal dagar.")
            try:
                number = float(str(value).strip().replace(",", "."))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{label} måste vara ett helt antal dagar.") from exc
            if not math.isfinite(number) or not number.is_integer():
                raise ValueError(f"{label} måste vara ett ändligt helt antal dagar.")
            return int(number)

        lower = day_bound(lower_value, "Från")
        upper = None if upper_value is None or str(upper_value).strip() == "" else (
            day_bound(upper_value, "Till"))
        score = _finite_nonnegative(score_value, "Poängen")
        if upper is None and index != len(bands) - 1:
            raise ValueError("Endast det sista intervallet får sakna övre gräns.")
        if upper is not None and upper < lower:
            raise ValueError("Till måste vara större än eller lika med Från.")
        parsed.append((lower, upper, score))

    if parsed[0][0] > 0 or (parsed[0][1] is not None and parsed[0][1] < 0):
        raise ValueError("Poängtrappan måste omfatta förseningsdag 0.")
    if parsed[-1][1] is not None:
        raise ValueError("Det sista intervallet måste sakna övre gräns.")
    for previous, current in zip(parsed, parsed[1:]):
        if previous[1] is None or current[0] != previous[1] + 1:
            raise ValueError("Intervallen får inte överlappa eller lämna luckor.")
    return tuple(parsed)


def _lock_horizon_end(now: datetime, hours: float) -> datetime:
    try:
        return now + timedelta(hours=hours)
    except (OverflowError, ValueError) as exc:
        raise ValueError(
            "Låshorisonten är för stor för aktuell NOW_Stockholm; "
            "välj ett mindre antal timmar."
        ) from exc


def now_stockholm() -> datetime:
    """Svensk lokal tid som naiv datetime, samma tidsbas som Jeeves."""
    if ZoneInfo is not None:
        return datetime.now(ZoneInfo(TZ_NAME)).replace(tzinfo=None)
    return datetime.now()


def excel_serial_to_datetime(value) -> Optional[pd.Timestamp]:
    if value is None:
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        ts = pd.to_datetime(value, errors="coerce")
        return None if pd.isna(ts) else ts
    if pd.isna(num) or num == 0:
        return None
    return EXCEL_EPOCH + pd.to_timedelta(num, unit="D")


def normalize_prodgr(value) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    text = str(value).strip()
    if text == "" or text.lower() in {"nan", "none"}:
        return None
    try:
        return str(int(float(text)))
    except (TypeError, ValueError):
        return text


def normalize_identifier(value) -> Optional[str]:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "null"}:
        return None
    try:
        number = float(text)
        if math.isfinite(number) and number.is_integer():
            return str(int(number))
    except (TypeError, ValueError, OverflowError):
        pass
    return text


def normalize_color(name) -> str:
    if name is None:
        return "Okänd"
    try:
        if pd.isna(name):
            return "Okänd"
    except (TypeError, ValueError):
        pass
    text = str(name).strip()
    if text == "" or text.lower() in {"nan", "none", "null"}:
        return "Okänd"
    return text if text in KNOWN_COLORS else "Okänd"


def fmt_dt(value, with_time: bool = True) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "-"
    ts = pd.Timestamp(value)
    if pd.isna(ts):
        return "-"
    return ts.strftime("%Y-%m-%d %H:%M") if with_time else ts.strftime("%Y-%m-%d")


def fmt_order(order_nr) -> str:
    if order_nr is None or (isinstance(order_nr, float) and pd.isna(order_nr)):
        return "saknas"
    try:
        return str(int(float(order_nr)))
    except (TypeError, ValueError):
        return str(order_nr)


def margin_days_between(due, finish) -> Optional[int]:
    if due is None or finish is None:
        return None
    d, f = pd.Timestamp(due), pd.Timestamp(finish)
    if pd.isna(d) or pd.isna(f):
        return None
    return (d.normalize().date() - f.normalize().date()).days


def tardiness_days_between(due, finish) -> float:
    if due is None or finish is None:
        return 0.0
    due_ts, finish_ts = pd.Timestamp(due), pd.Timestamp(finish)
    if pd.isna(due_ts) or pd.isna(finish_ts):
        return 0.0
    return max(0.0, (finish_ts - due_ts).total_seconds() / 86400.0)


def tardiness_score(days: float,
                    bands: tuple = DEFAULT_TARDINESS_SCORE_BANDS) -> float:
    whole_days = math.ceil(max(0.0, float(days)))
    for lower, upper, score in bands:
        if whole_days >= lower and (upper is None or whole_days <= upper):
            return score
    raise ValueError(f"Förseningsdag {whole_days} saknas i poängtrappan.")


def v7_tardiness_metrics(jobs: Sequence["Job"],
                         policy: Optional["ClusterPolicy"] = None
                         ) -> Dict[str, object]:
    policy = policy or ClusterPolicy()
    score_before = 0.0
    score_after = 0.0
    cap_excesses: List[float] = []
    unplanned = 0
    baseline_over_limit = 0
    after_over_limit = 0
    for job in jobs:
        if job.ord_ber_lev_dat is None:
            continue
        baseline_late = tardiness_days_between(job.ord_ber_lev_dat, job.orig_tislutdat)
        configured_limit = job.max_tardiness_days
        baseline_over_limit += baseline_late > configured_limit + CAP_EPSILON_DAYS
        score_before += job.customer_weight * tardiness_score(
            baseline_late, policy.score_bands)
        if job.ai_tislutdat is None:
            if job.movable:
                unplanned += 1
                score_after += job.customer_weight * tardiness_score(
                    baseline_late, policy.score_bands)
                cap_excesses.append(0.0)
            continue
        after_late = tardiness_days_between(job.ord_ber_lev_dat, job.ai_tislutdat)
        after_over_limit += after_late > configured_limit + CAP_EPSILON_DAYS
        score_after += job.customer_weight * tardiness_score(
            after_late, policy.score_bands)
        cap_excesses.append(max(0.0, after_late - job.permitted_tardiness_days()))
    breaches = [value for value in cap_excesses if value > CAP_EPSILON_DAYS]
    return {
        "tardiness_score_before": round(score_before, 3),
        "tardiness_score_after": round(score_after, 3),
        "cap_breach_count": len(breaches),
        "cap_excess_days": round(sum(breaches), 3),
        "worst_cap_excess_days": round(max(breaches, default=0.0), 3),
        "baseline_over_limit_count": int(baseline_over_limit),
        "after_over_limit_count": int(after_over_limit),
        "unplanned_count": unplanned, "cap_met": not breaches,
    }
    return {
        "tardiness_score_before": round(score_before, 3),
        "tardiness_score_after": round(score_after, 3),
        "cap_breach_count": len(breaches),
        "cap_excess_days": round(sum(breaches), 3),
        "worst_cap_excess_days": round(max(breaches, default=0.0), 3),
        "baseline_over_limit_count": int(baseline_over_limit),
        "after_over_limit_count": int(after_over_limit),
        "unplanned_count": unplanned, "cap_met": not breaches,
    }

v5_tardiness_metrics = v7_tardiness_metrics


def status_from_margin(margin: Optional[float], fallback: str = "Okänd") -> str:
    if margin is None or (isinstance(margin, float) and margin != margin):
        return fallback
    if margin > GREEN_MARGIN_DAYS:
        return "Grön"
    if margin == GREEN_MARGIN_DAYS:
        return "Gul"
    return "Röd"


def fmt_hours(hours: float) -> str:
    text = f"{hours:.2f}".rstrip("0").rstrip(".")
    return text.replace(".", ",") + " h"


@dataclass
class WorkWindow:
    start: datetime
    end: datetime

    @property
    def hours(self) -> float:
        return (self.end - self.start).total_seconds() / 3600.0


class WorkCalendar:
    """Kalenderfönster och arbetsdagsindex enligt den oförändrade V5-logiken."""

    def __init__(self, cal_df: pd.DataFrame, now: datetime, log: LogFn = _noop):
        self.now = now
        self.windows: Dict[int, List[WorkWindow]] = {}
        self.window_starts: Dict[int, List[datetime]] = {}
        self.window_ends: Dict[int, List[datetime]] = {}
        self.coverage: Dict[int, Tuple[datetime, datetime]] = {}
        self.mean_daily_hours: Dict[int, float] = {}
        self.warnings: List[str] = []
        self.work_days: Dict[int, List[int]] = {}
        self.work_weekdays: Dict[int, set] = {}
        self.day_coverage: Dict[int, Tuple[int, int]] = {}
        self._build_workday_index(cal_df)
        today = pd.Timestamp(now).normalize()
        for kal, grp in cal_df.groupby("kalendernr"):
            wins: List[WorkWindow] = []
            for _, row in grp.sort_values("_date").iterrows():
                start = row["Date_komtid"]
                end_limit = row["Date_gicktid"]
                if pd.isna(start) or pd.isna(end_limit):
                    continue
                start = pd.Timestamp(start).to_pydatetime()
                end_limit = pd.Timestamp(end_limit).to_pydatetime()
                day = pd.Timestamp(row["_date"]).normalize()
                if day == today:
                    capacity = row.get("arbtimperdag_firstdaymode")
                    if capacity is None or pd.isna(capacity):
                        capacity = row.get("arbtimperdag")
                    if start < now:
                        start = now
                else:
                    capacity = row.get("arbtimperdag")
                if capacity is None or pd.isna(capacity):
                    capacity = (end_limit - start).total_seconds() / 3600.0
                end = min(end_limit, start + timedelta(hours=float(capacity)))
                if end > start:
                    wins.append(WorkWindow(start, end))
            wins.sort(key=lambda w: w.start)
            if not wins:
                self.warnings.append(
                    f"Kalendernr {kal} saknar användbara arbetsfönster – "
                    f"operationer på denna kalender kan inte kalendervalideras.")
                continue
            self.windows[int(kal)] = wins
            self.window_starts[int(kal)] = [w.start for w in wins]
            self.window_ends[int(kal)] = [w.end for w in wins]
            self.coverage[int(kal)] = (wins[0].start, wins[-1].end)
            total = sum(w.hours for w in wins)
            days = max(1, len({w.start.date() for w in wins}))
            self.mean_daily_hours[int(kal)] = total / days
        for msg in self.warnings:
            log("VARNING: " + msg)

    def _build_workday_index(self, cal_df: pd.DataFrame) -> None:
        for kal, grp in cal_df.groupby("kalendernr"):
            cap = pd.to_numeric(grp.get("arbtimperdag"), errors="coerce").fillna(0)
            dates = pd.to_datetime(grp["_date"], errors="coerce")
            ords = sorted({d.date().toordinal()
                           for d, c in zip(dates, cap) if pd.notna(d) and c > 0})
            if not ords:
                continue
            kal = int(kal)
            lo, hi = ords[0], ords[-1]
            self.work_days[kal] = ords
            self.day_coverage[kal] = (lo, hi)
            present = set(ords)
            hits, total = [0] * 7, [0] * 7
            for n in range(lo, hi + 1):
                wd = (n - 1) % 7
                total[wd] += 1
                hits[wd] += n in present
            self.work_weekdays[kal] = {
                wd for wd in range(7) if total[wd] and hits[wd] / total[wd] >= 0.5}
        self._build_company_calendar()

    def _build_company_calendar(self) -> None:
        if not self.work_days:
            return
        sets = {k: set(v) for k, v in self.work_days.items()}
        lo = min(a for a, _ in self.day_coverage.values())
        hi = max(b for _, b in self.day_coverage.values())
        company: List[int] = []
        for n in range(lo, hi + 1):
            if (n - 1) % 7 >= 5:
                continue
            covering = [k for k, (a, b) in self.day_coverage.items() if a <= n <= b]
            working = sum(1 for k in covering if n in sets[k])
            if covering and working * 2 > len(covering):
                company.append(n)
        if company:
            self.work_days[COMPANY_CALENDAR] = company
            self.day_coverage[COMPANY_CALENDAR] = (lo, hi)
            self.work_weekdays[COMPANY_CALENDAR] = {0, 1, 2, 3, 4}

    @staticmethod
    def _count_weekdays(a: int, b: int, weekdays: set) -> int:
        if b < a or not weekdays:
            return 0
        full, rest = divmod(b - a + 1, 7)
        start_wd = (a - 1) % 7
        return full * len(weekdays) + sum(
            1 for i in range(rest) if (start_wd + i) % 7 in weekdays)

    @staticmethod
    def _key(kal):
        return kal if kal == COMPANY_CALENDAR else int(kal)

    def has_workdays(self, kal) -> bool:
        return self._key(kal) in self.work_days

    def working_days_after(self, kal, due, finish) -> Tuple[int, bool]:
        a = due.toordinal() + 1
        b = finish.toordinal()
        if b < a:
            return 0, False
        kal = self._key(kal)
        if kal not in self.work_days:
            return b - a + 1, True
        days = self.work_days[kal]
        weekdays = self.work_weekdays[kal]
        lo, hi = self.day_coverage[kal]
        count, estimated = 0, False
        ia, ib = max(a, lo), min(b, hi)
        if ia <= ib:
            count += bisect.bisect_right(days, ib) - bisect.bisect_left(days, ia)
        if a < lo:
            count += self._count_weekdays(a, min(b, lo - 1), weekdays)
            estimated = True
        if b > hi:
            count += self._count_weekdays(max(a, hi + 1), b, weekdays)
            estimated = True
        return count, estimated

    def has(self, kal: int) -> bool:
        return int(kal) in self.windows

    def coverage_text(self) -> str:
        parts = []
        for kal in sorted(self.coverage):
            lo, hi = self.coverage[kal]
            parts.append(f"kal {kal}: {lo:%Y-%m-%d} - {hi:%Y-%m-%d}")
        return "; ".join(parts)

    def schedule(self, kal: int, earliest: datetime, hours: float
                 ) -> Tuple[Optional[datetime], Optional[datetime], List[str]]:
        flags: List[str] = []
        kal = int(kal)
        hours = max(0.0, float(hours))
        if kal not in self.windows:
            flags.append(f"Ingen kalenderdata för kalendernr {kal}; kapacitet saknas")
            return None, None, flags
        wins = self.windows[kal]
        ends = self.window_ends[kal]
        idx = bisect.bisect_right(ends, earliest)
        if idx >= len(wins):
            flags.append(
                f"Utanför kalendertäckning (kal {kal} slutar "
                f"{self.coverage[kal][1]:%Y-%m-%d}); ingen extrapolering gjordes")
            return None, None, flags
        start = max(wins[idx].start, earliest)
        if hours <= 0:
            return start, start, flags
        remaining = hours
        cursor = start
        for w in wins[idx:]:
            seg_start = max(w.start, cursor)
            if seg_start >= w.end:
                continue
            avail = (w.end - seg_start).total_seconds() / 3600.0
            if avail + 1e-9 >= remaining:
                return start, seg_start + timedelta(hours=remaining), flags
            remaining -= avail
            cursor = w.end
        flags.append(
            f"Operationen ryms inte inom kalendertäckningen för kal {kal} "
            f"(t.o.m. {self.coverage[kal][1]:%Y-%m-%d}); ingen extrapolering gjordes")
        return None, None, flags

    def project(self, kal: int, start: datetime,
                durations: Sequence[float]) -> List[datetime]:
        kal = int(kal)
        out: List[datetime] = []
        if kal not in self.windows:
            cursor = start
            for d in durations:
                cursor = cursor + timedelta(hours=max(0.0, d))
                out.append(cursor)
            return out
        wins = self.windows[kal]
        ends = self.window_ends[kal]
        per_day = self.mean_daily_hours.get(kal) or 8.0
        idx = bisect.bisect_right(ends, start)
        cursor = start if idx >= len(wins) else max(wins[idx].start, start)
        for d in durations:
            remaining = max(0.0, float(d))
            while remaining > 1e-9 and idx < len(wins):
                w = wins[idx]
                seg_start = max(w.start, cursor)
                if seg_start >= w.end:
                    idx += 1
                    continue
                avail = (w.end - seg_start).total_seconds() / 3600.0
                if avail + 1e-9 >= remaining:
                    cursor = seg_start + timedelta(hours=remaining)
                    remaining = 0.0
                    break
                remaining -= avail
                cursor = w.end
                idx += 1
            if remaining > 1e-9:
                cursor = cursor + timedelta(days=remaining / per_day)
            out.append(cursor)
        return out


@dataclass
class Job:
    idx: int
    ao_nr: int
    ao_pos: int
    op_nr: int
    art_nr: str
    order_nr: Optional[float]
    prodgr_org: Optional[str]
    kalendernr: int
    op_status: int
    op_status_text: str
    orig_start: Optional[datetime]
    orig_end: Optional[datetime]
    orig_tislutdat: Optional[datetime]
    ord_ber_lev_dat: Optional[datetime]
    orig_color_code: Optional[str]
    orig_color_name: Optional[str]
    orig_prio: Optional[int]
    stalltid: float
    stycktid: float
    downstream_delta: timedelta
    movable: bool = False
    frozen_reason: str = ""
    already_started: bool = False
    locked_horizon: bool = False
    unplanned_reason: str = ""
    cap_locked_original: bool = False
    cap_repair_reason: str = ""
    prodgr_ai: Optional[str] = None
    ai_start: Optional[datetime] = None
    ai_end: Optional[datetime] = None
    ai_tislutdat: Optional[datetime] = None
    ai_color_name: Optional[str] = None
    ai_color_code: Optional[str] = None
    ai_prio: Optional[int] = None
    setup_saved: float = 0.0
    cluster_ref: Optional["Job"] = None
    pulled_forward: bool = False
    cluster_cost_days: float = 0.0
    rerouted_from: Optional[str] = None
    predecessor: Optional["Job"] = None
    successor: Optional["Job"] = None
    flags: List[str] = field(default_factory=list)
    comment: str = ""
    customer_order_numbers: Tuple[str, ...] = ()
    customer_numbers: Tuple[str, ...] = ()
    customer_weight: float = DEFAULT_CUSTOMER_WEIGHT
    max_tardiness_days: float = DEFAULT_MAX_TARDINESS_DAYS

    @property
    def duration_full(self) -> float:
        return self.stalltid + self.stycktid

    @property
    def duration_effective(self) -> float:
        return self.duration_full - self.setup_saved

    @property
    def baseline_status(self) -> str:
        return normalize_color(self.orig_color_name)

    @property
    def baseline_status_rule(self) -> str:
        if self.ord_ber_lev_dat is None or self.orig_tislutdat is None:
            return self.baseline_status
        return self.status_for(self.orig_tislutdat)

    def margin_days(self, tislutdat: Optional[datetime]) -> Optional[int]:
        return margin_days_between(self.ord_ber_lev_dat, tislutdat)

    def lateness_days(self, tislutdat: Optional[datetime]) -> float:
        margin = self.margin_days(tislutdat)
        return 0.0 if margin is None else float(max(0, -margin))

    def damage_days(self, tislutdat: Optional[datetime]) -> float:
        margin = self.margin_days(tislutdat)
        return 0.0 if margin is None else float(max(0, PROTECT_MARGIN_DAYS - margin))

    def status_for(self, tislutdat: Optional[datetime]) -> str:
        return status_from_margin(self.margin_days(tislutdat), fallback=self.baseline_status)

    def permitted_tardiness_days(self) -> float:
        baseline_late = tardiness_days_between(self.ord_ber_lev_dat,
                                               self.orig_tislutdat)
        return max(self.max_tardiness_days, baseline_late)

    @property
    def key(self) -> str:
        return f"AO#{self.ao_nr}/Order:{fmt_order(self.order_nr)}"


@dataclass
class Interval:
    start: datetime
    end: datetime
    job: Job
    fixed: bool


class Machine:
    def __init__(self, prodgr: str, kalendernr: int):
        self.prodgr = prodgr
        self.kalendernr = kalendernr
        self.fixed: List[Interval] = []
        self.movable: List[Job] = []
        self.sequence: List[Interval] = []

    def add_fixed(self, job: Job) -> None:
        if job.orig_start is None or job.orig_end is None:
            return
        self.fixed.append(Interval(job.orig_start, job.orig_end, job, True))
        self.fixed.sort(key=lambda i: i.start)

    def conflict(self, start: datetime, end: datetime) -> Optional[Interval]:
        for iv in self.fixed:
            if iv.start < end - timedelta(seconds=EPS_SECONDS) and \
               iv.end > start + timedelta(seconds=EPS_SECONDS):
                return iv
        return None


@dataclass
class SourceData:
    baseline: pd.DataFrame
    operations: pd.DataFrame
    calendar: pd.DataFrame
    prio: pd.DataFrame
    warnings: List[str] = field(default_factory=list)
    customer_config: pd.DataFrame = field(default_factory=pd.DataFrame)


def load_source(path: str, log: LogFn = _noop) -> SourceData:
    log(f"Läser arbetsbok: {os.path.basename(path)}")
    with pd.ExcelFile(path) as xl:
        present = set(xl.sheet_names)
        missing = [s for s in SOURCE_SHEETS if s not in present]
        if missing:
            raise ValueError(
                "Arbetsboken saknar obligatoriska flikar: " + ", ".join(missing) +
                ".\nHittade flikar: " + ", ".join(xl.sheet_names))
        baseline = xl.parse(SHEET_BASELINE)
        operations = xl.parse(SHEET_OPERATIONS)
        calendar = xl.parse(SHEET_CALENDAR)
        prio = xl.parse(SHEET_PRIO)
        customer_config = (xl.parse(SHEET_CUSTOMER_CONFIG)
                   if SHEET_CUSTOMER_CONFIG in present else pd.DataFrame())
    warnings: List[str] = []
    for name, df, required in (
        (SHEET_BASELINE, baseline,
         ["AoNr", "AoPos", "OpNr", "ProdGr", "OpStatus", "ArtNr", "AoStartDatTid",
          "AoSlutDatTid", "TiSlutDat", "OrderNr", "OrdBerLevDat", "ColorCode",
          "ColorName", "OpkoPrioritet"]),
        (SHEET_OPERATIONS, operations,
         ["AoNr", "AoPos", "OpNr", "ProdGr", "ArtNr", "OpStatus", "TiSlutDat",
          "aostartdattid", "aoslutdattid", "stalltid", "stycktid", "kalendernr"]),
        (SHEET_CALENDAR, calendar,
         ["dDate", "kalendernr", "Date_komtid", "Date_gicktid", "arbtimperdag"]),
        (SHEET_PRIO, prio, ["ArtNr", "OpNr", "Prio1"]),
    ):
        lack = [c for c in required if c not in df.columns]
        if lack:
            raise ValueError(f"Fliken '{name}' saknar kolumnerna: {', '.join(lack)}")
    if not customer_config.empty:
        required = ["OrderNumber", "Customer", "Vikt", "MaxLate"]
        lack = [c for c in required if c not in customer_config.columns]
        if lack:
            raise ValueError(
                f"Fliken '{SHEET_CUSTOMER_CONFIG}' saknar kolumnerna: "
                f"{', '.join(lack)}")
    log(f"  {SHEET_BASELINE}: {len(baseline)} rader")
    log(f"  {SHEET_OPERATIONS}: {len(operations)} rader")
    log(f"  {SHEET_CALENDAR}: {len(calendar)} rader")
    log(f"  {SHEET_PRIO}: {len(prio)} rader")
    calendar = calendar.copy()
    calendar["_date"] = pd.to_datetime(calendar["dDate"], errors="coerce")
    bad_dates = int(calendar["_date"].isna().sum())
    if bad_dates:
        warnings.append(f"{bad_dates} kalenderrader har otolkbart dDate och ignoreras.")
        calendar = calendar[calendar["_date"].notna()]
    for col in ("Date_komtid", "Date_gicktid"):
        calendar[col] = pd.to_datetime(calendar[col], errors="coerce")
    need = calendar["Date_komtid"].isna() | calendar["Date_gicktid"].isna()
    if need.any() and {"komtid", "gicktid"} <= set(calendar.columns):
        def _combine(row, col):
            raw = str(row.get(col) or "").strip()
            m = re.match(r"^(\d{1,2}):(\d{2})", raw)
            if not m:
                return pd.NaT
            return row["_date"] + pd.Timedelta(hours=int(m.group(1)), minutes=int(m.group(2)))
        calendar.loc[need, "Date_komtid"] = calendar[need].apply(
            lambda r: _combine(r, "komtid"), axis=1)
        calendar.loc[need, "Date_gicktid"] = calendar[need].apply(
            lambda r: _combine(r, "gicktid"), axis=1)
    operations = operations.copy()
    for col in ("TiSlutDat", "aostartdattid", "aoslutdattid"):
        operations[col] = pd.to_datetime(operations[col], errors="coerce")
    operations["_prodgr"] = operations["ProdGr"].map(normalize_prodgr)
    prio = prio.copy()
    prio["_artnr"] = prio["ArtNr"].astype(str).str.strip()
    return SourceData(baseline, operations, calendar, prio, warnings, customer_config)


BASELINE_KEY = ["AoNr", "AoPos", "OpNr"]


def build_customer_lookup(src: SourceData, global_limit: float,
                          warnings: List[str]
                          ) -> Dict[Tuple[str, str], List[Tuple[str, str, float, float]]]:
    links: Dict[Tuple[str, str], List[Tuple[str, str, float, float]]] = {}
    if src.customer_config.empty:
        warnings.append(
            f"Fliken {SHEET_CUSTOMER_CONFIG} saknas eller är tom; alla order använder "
            "standardvikt 1 och generell maxförsening.")
        return links

    policies: Dict[str, Tuple[str, float, float]] = {}
    for _, row in src.customer_config.iterrows():
        order = normalize_identifier(row.get("OrderNumber"))
        customer = normalize_identifier(row.get("Customer"))
        if order is None or customer is None:
            warnings.append(
                f"{SHEET_CUSTOMER_CONFIG} innehåller OrderNumber/Customer saknad; raden ignoreras.")
            continue
        weight = validate_customer_weight(row.get("Vikt"))
        raw_limit = row.get("MaxLate")
        limit = (global_limit if raw_limit is None or pd.isna(raw_limit)
                 or str(raw_limit).strip() == "" else
                 validate_max_tardiness_days(raw_limit))
        policy = (customer, weight, limit)
        if order in policies and policies[order] != policy:
            raise ValueError(
                f"{SHEET_CUSTOMER_CONFIG} innehåller motstridiga rader för "
                f"OrderNumber {order}.")
        policies[order] = policy

    matched: set = set()
    for _, row in src.baseline.iterrows():
        ao = normalize_identifier(row.get("AoNr"))
        pos = normalize_identifier(row.get("AoPos"))
        order = normalize_identifier(row.get("OrderNr"))
        if ao is None or pos is None or order not in policies:
            continue
        customer, weight, limit = policies[order]
        entry = (order, customer, weight, limit)
        key = (ao, pos)
        if entry not in links.setdefault(key, []):
            links[key].append(entry)
        matched.add(order)
    unused = sorted(set(policies) - matched)
    if unused:
        warnings.append(
            "OrderNumber i CustomerConfig saknas i baslinjens OrderNr: "
            f"{', '.join(unused[:20])}" + (" …" if len(unused) > 20 else "."))
    return links


def dedupe_baseline(baseline: pd.DataFrame, warnings: List[str],
                    log: LogFn = _noop) -> pd.DataFrame:
    if not set(BASELINE_KEY) <= set(baseline.columns):
        return baseline
    dupes = int(baseline.duplicated(subset=BASELINE_KEY).sum())
    if not dupes:
        return baseline
    before = len(baseline)
    work = baseline.copy()
    work["_ord"] = range(len(work))
    sort_by = (["OrdBerLevDat", "_ord"] if "OrdBerLevDat" in work.columns else ["_ord"])
    work = work.sort_values(sort_by, na_position="last", kind="mergesort")
    work = work.drop_duplicates(subset=BASELINE_KEY, keep="first")
    result = (work.sort_values("_ord", kind="mergesort")
                  .drop(columns=["_ord"]).reset_index(drop=True))
    conflicting = 0
    differing: Dict[str, int] = {}
    watch = [c for c in ("OrderNr", "OrdBerLevDat", "ColorName", "ProdGr", "OpStatus")
             if c in baseline.columns]
    for _, grp in baseline[baseline.duplicated(subset=BASELINE_KEY,
                                               keep=False)].groupby(BASELINE_KEY):
        cols = [c for c in watch if grp[c].astype(str).nunique() > 1]
        if cols:
            conflicting += 1
            for c in cols:
                differing[c] = differing.get(c, 0) + 1
    msg = (f"Baslinjen innehöll {before} rader varav {dupes} var dubbletter "
           f"på (AoNr, AoPos, OpNr). Maskintiden bokas en gång per operation "
           f"({len(result)} rader kvar) – annars hade beläggningen blåsts upp "
           f"med tid som inte finns.")
    if conflicting:
        detalj = ", ".join(f"{c} ({n})" for c, n in sorted(differing.items()))
        msg += (f" {conflicting} av dem är **motstridiga**: samma operation "
                f"förekommer med olika {detalj}. Det tyder på att en "
                f"tillverkningsorder täcker flera kundorder. Raden med "
                f"tidigast OrdBerLevDat har använts, så statusen speglar den "
                f"mest krävande kunden – men underlaget bör ses över, och "
                f"övriga kundorders leveransdatum syns inte i resultatet.")
    warnings.append(msg)
    log("VARNING: " + msg)
    return result


def build_jobs(src: SourceData, cal: WorkCalendar, now: datetime,
               log: LogFn = _noop,
               lock_horizon_hours: float = LOCK_HORIZON_HOURS,
               max_tardiness_days: float = DEFAULT_MAX_TARDINESS_DAYS
               ) -> Tuple[List[Job], List[str]]:
    """Klassificera med inkluderande framtidsgräns; påbörjade fryses alltid."""
    lock_horizon_hours = validate_lock_horizon_hours(lock_horizon_hours)
    lock_end = _lock_horizon_end(now, lock_horizon_hours)
    max_tardiness_days = validate_max_tardiness_days(max_tardiness_days)
    warnings = list(src.warnings)
    customer_links = build_customer_lookup(
        src, max_tardiness_days, warnings)
    baseline_rows = dedupe_baseline(src.baseline, warnings, log)
    ops = src.operations
    ops_key = ops.set_index(["AoNr", "AoPos", "OpNr"])
    ops_key = ops_key[~ops_key.index.duplicated(keep="first")]
    prodgr_cal = (ops.dropna(subset=["_prodgr"])
                     .groupby("_prodgr")["kalendernr"].agg(
                         lambda s: int(s.mode().iloc[0])).to_dict())
    jobs: List[Job] = []
    missing_ops = 0
    missing_duration = 0
    for idx, row in baseline_rows.iterrows():
        ao_nr = int(row["AoNr"])
        ao_pos = int(row["AoPos"])
        op_nr = int(row["OpNr"])
        try:
            op = ops_key.loc[(ao_nr, ao_pos, op_nr)]
        except KeyError:
            op = None
        if op is None:
            missing_ops += 1
        prodgr = normalize_prodgr(
            op["_prodgr"] if op is not None else row["ProdGr"]) or \
            normalize_prodgr(row["ProdGr"])
        kalendernr = int(op["kalendernr"]) if op is not None and not pd.isna(
            op.get("kalendernr")) else int(prodgr_cal.get(prodgr, 2))
        op_status = int(op["OpStatus"]) if op is not None else int(row["OpStatus"])
        op_status_text = str(row.get("OpStatusBeskr") or "").strip()
        if op is not None and not pd.isna(op["aostartdattid"]):
            orig_start = pd.Timestamp(op["aostartdattid"]).to_pydatetime()
        else:
            ts = excel_serial_to_datetime(row["AoStartDatTid"])
            orig_start = ts.to_pydatetime() if ts is not None else None
        if op is not None and not pd.isna(op["aoslutdattid"]):
            orig_end = pd.Timestamp(op["aoslutdattid"]).to_pydatetime()
        else:
            ts = excel_serial_to_datetime(row["AoSlutDatTid"])
            orig_end = ts.to_pydatetime() if ts is not None else None
        if op is not None and not pd.isna(op["TiSlutDat"]):
            orig_ti = pd.Timestamp(op["TiSlutDat"]).to_pydatetime()
        else:
            ts = excel_serial_to_datetime(row["TiSlutDat"])
            orig_ti = ts.to_pydatetime() if ts is not None else None
        due_ts = excel_serial_to_datetime(row["OrdBerLevDat"])
        due = due_ts.to_pydatetime() if due_ts is not None else None
        customer_rows = customer_links.get((str(ao_nr), str(ao_pos)), [])
        customer_numbers = tuple(sorted({customer for _, customer, _, _ in customer_rows}))
        customer_order_numbers = tuple(sorted({order for order, _, _, _ in customer_rows}))
        customer_weights = [weight for _, _, weight, _ in customer_rows]
        customer_limits = [limit for _, _, _, limit in customer_rows]
        customer_weight = max(customer_weights, default=DEFAULT_CUSTOMER_WEIGHT)
        effective_customer_limit = min(customer_limits, default=max_tardiness_days)
        stalltid = float(op["stalltid"]) if op is not None and not pd.isna(
            op.get("stalltid")) else 0.0
        stycktid = float(op["stycktid"]) if op is not None and not pd.isna(
            op.get("stycktid")) else 0.0
        flags: List[str] = []
        if op_nr == 10 and stalltid + stycktid <= 0:
            missing_duration += 1
            flags.append("Saknar Op10-operationstid; ingen varaktighet gissades")
        downstream = timedelta(0)
        if orig_ti is not None and orig_end is not None:
            downstream = orig_ti - orig_end
            if downstream < timedelta(0):
                downstream = timedelta(0)
        job = Job(
            idx=int(idx), ao_nr=ao_nr, ao_pos=ao_pos, op_nr=op_nr,
            art_nr=str(row["ArtNr"]).strip(),
            order_nr=(None if pd.isna(row["OrderNr"]) else float(row["OrderNr"])),
            prodgr_org=prodgr, kalendernr=kalendernr,
            op_status=op_status, op_status_text=op_status_text,
            orig_start=orig_start, orig_end=orig_end, orig_tislutdat=orig_ti,
            ord_ber_lev_dat=due,
            orig_color_code=(None if pd.isna(row.get("ColorCode")) else str(row["ColorCode"])),
            orig_color_name=(None if pd.isna(row.get("ColorName")) else str(row["ColorName"])),
            orig_prio=(None if pd.isna(row.get("OpkoPrioritet")) else int(row["OpkoPrioritet"])),
            stalltid=stalltid, stycktid=stycktid, downstream_delta=downstream,
            flags=flags,
            customer_order_numbers=customer_order_numbers,
            customer_numbers=customer_numbers,
            customer_weight=customer_weight,
            max_tardiness_days=effective_customer_limit,
        )
        job.already_started = (orig_start is not None and orig_start <= now)
        job.locked_horizon = (
            orig_start is not None and op_nr == 10 and op_status == 0
            and due is not None and now < orig_start <= lock_end)
        if op is None:
            job.movable = False
            job.frozen_reason = "saknar operationsdata"
        elif op_nr != 10:
            job.movable = False
            job.frozen_reason = f"Op{op_nr} – endast Op10 får omplaneras"
        elif job.already_started:
            job.movable = False
            job.frozen_reason = "redan påbörjad"
        elif orig_start is None:
            job.movable = False
            job.frozen_reason = "saknar ursprunglig Op10-start"
        elif job.locked_horizon:
            job.movable = False
            job.frozen_reason = f"inom {lock_horizon_hours:g}-timmars låshorisont"
        elif op_status != 0:
            job.movable = False
            job.frozen_reason = f"OpStatus {op_status}"
        elif op_nr == 10 and stalltid + stycktid <= 0:
            job.movable = False
            job.frozen_reason = "saknar Op10-operationstid"
        elif due is None:
            job.movable = False
            job.frozen_reason = "saknar OrdBerLevDat"
        elif not cal.has(kalendernr):
            job.movable = False
            job.frozen_reason = f"saknar användbar kalender {kalendernr}"
        else:
            job.movable = True
        if not cal.has(kalendernr) and op_nr == 10:
            job.flags.append(f"Kalendernr {kalendernr} saknar kalenderdata")
        jobs.append(job)
    if missing_ops:
        warnings.append(
            f"{missing_ops} baslinjerader saknar matchande rad i "
            f"{SHEET_OPERATIONS} och kan inte omplaneras.")
    if missing_duration:
        warnings.append(
            f"{missing_duration} Op10-rader saknar operationstid "
            f"(stalltid+stycktid=0); de frystes och ingen varaktighet gissades.")
    n_move = sum(1 for j in jobs if j.movable)
    n_started = sum(1 for j in jobs if j.already_started)
    log(f"Klassificering: {n_move} omplaneringsbara, {len(jobs) - n_move} frysta "
        f"(varav {n_started} redan påbörjade); låshorisont {lock_horizon_hours:g} h.")
    return jobs, warnings


FAR_FUTURE = datetime(2999, 12, 31)


@dataclass
class ClusterPolicy:
    window_days: int = CLUSTER_WINDOW_DAYS
    budget_days_per_hour: float = TARDINESS_BUDGET_PER_SETUP_HOUR
    global_max_tardiness_days: float = DEFAULT_MAX_TARDINESS_DAYS
    score_bands: tuple = DEFAULT_TARDINESS_SCORE_BANDS

    def __post_init__(self) -> None:
        if isinstance(self.window_days, bool) or int(self.window_days) != self.window_days:
            raise ValueError("Klusterfönstret måste vara ett heltal.")
        if self.window_days < 0:
            raise ValueError("Klusterfönstret kan inte vara negativt.")
        self.global_max_tardiness_days = validate_max_tardiness_days(
            self.global_max_tardiness_days)
        self.score_bands = validate_tardiness_score_bands(self.score_bands)

    def describe(self, lock_horizon_hours: float = LOCK_HORIZON_HOURS) -> str:
        lock_horizon_hours = validate_lock_horizon_hours(lock_horizon_hours)
        return (f"V7; låshorisont {lock_horizon_hours:g} h; "
                f"klusterfönster {self.window_days} dygn; "
            f"generellt förseningsstak {self.global_max_tardiness_days:g} dygn; "
            "kundviktad intervallpoäng för hela förseningsdagar")


def edd_order(jobs: Sequence[Job]) -> List[Job]:
    return sorted(jobs, key=lambda j: (j.ord_ber_lev_dat or FAR_FUTURE, j.ao_nr))


def _projected_durations(seq: Sequence[Job], prev_article: Optional[str]) -> List[float]:
    out: List[float] = []
    last = prev_article
    for j in seq:
        out.append(j.stycktid if (last is not None and j.art_nr == last)
                   else j.duration_full)
        last = j.art_nr
    return out


def _projected_tardiness(cal: WorkCalendar, kal: int, cursor: datetime,
                         seq: Sequence[Job], prev_article: Optional[str]) -> float:
    if not seq:
        return 0.0
    ends = cal.project(kal, cursor, _projected_durations(seq, prev_article))
    total = 0.0
    for job, end in zip(seq, ends):
        if job.ord_ber_lev_dat is None or end is None:
            continue
        total += job.damage_days(end + job.downstream_delta)
    return total


def _pick_next(cal: WorkCalendar, kal: int, cursor: datetime,
               remaining: List[Job], prev_article: Optional[str],
               policy: ClusterPolicy) -> Tuple[Job, Optional[float]]:
    head = remaining[0]
    if prev_article is None or head.art_nr == prev_article:
        return head, None
    head_due = head.ord_ber_lev_dat or FAR_FUTURE
    limit = head_due + timedelta(days=policy.window_days)
    candidates = [j for j in remaining[1:]
                  if j.art_nr == prev_article and j.stalltid > 0
                  and (j.ord_ber_lev_dat or FAR_FUTURE) <= limit]
    if not candidates:
        return head, None
    base = _projected_tardiness(cal, kal, cursor, remaining, prev_article)
    for cand in candidates:
        alt = [cand] + [j for j in remaining if j is not cand]
        added = _projected_tardiness(cal, kal, cursor, alt, prev_article) - base
        if added <= policy.budget_days_per_hour * cand.stalltid + 1e-9:
            return cand, max(0.0, added)
    return head, None


@dataclass
class Placement:
    start: datetime
    end: datetime
    flags: List[str]
    setup_saved: float
    cluster_ref: Optional[Job]


def _candidate_rank(job: Job, placement: Placement,
                    policy: Optional[ClusterPolicy] = None) -> tuple:
    policy = policy or ClusterPolicy()
    completion = placement.end + job.downstream_delta
    late = tardiness_days_between(job.ord_ber_lev_dat, completion)
    cap_excess = max(0.0, late - job.permitted_tardiness_days())
    green = job.status_for(completion) == "Grön"
    early = max(0.0, -(
        pd.Timestamp(completion) - pd.Timestamp(job.ord_ber_lev_dat)
    ).total_seconds() / 86400.0) if job.ord_ber_lev_dat is not None else 0.0
    due = job.ord_ber_lev_dat or FAR_FUTURE
    return (1 if cap_excess > CAP_EPSILON_DAYS else 0, cap_excess,
            -job.customer_weight if green else 0,
            job.customer_weight * tardiness_score(late, policy.score_bands), late, early,
            -placement.setup_saved, due, placement.start, job.ao_nr)


def plan_objective(jobs: Sequence[Job],
                   policy: Optional[ClusterPolicy] = None) -> tuple:
    policy = policy or ClusterPolicy()
    cap_excesses: List[float] = []
    lateness_values: List[float] = []
    score_total = 0.0
    earliness_total = 0.0
    green_weight = 0.0
    setup_total = 0.0
    reroutes = 0
    changed = 0
    for job in jobs:
        if job.ord_ber_lev_dat is None:
            continue
        if job.ai_tislutdat is None:
            if job.movable:
                cap_excesses.append(1e9)
                lateness_values.append(1e9)
                score_total += 1e12
            continue
        late = tardiness_days_between(job.ord_ber_lev_dat, job.ai_tislutdat)
        cap_excesses.append(max(0.0, late - job.permitted_tardiness_days()))
        lateness_values.append(late)
        score_total += job.customer_weight * tardiness_score(late, policy.score_bands)
        if job.status_for(job.ai_tislutdat) == "Grön":
            green_weight += job.customer_weight
        earliness_total += max(0.0, -(
            pd.Timestamp(job.ai_tislutdat) - pd.Timestamp(job.ord_ber_lev_dat)
        ).total_seconds() / 86400.0)
        setup_total += job.setup_saved
        reroutes += bool(job.rerouted_from)
        changed += bool(job.orig_start is not None and job.ai_start is not None
                        and job.orig_start != job.ai_start)
    breached = [v for v in cap_excesses if v > CAP_EPSILON_DAYS]
    return (len(breached), sum(cap_excesses), max(cap_excesses, default=0.0),
            -green_weight, score_total, max(lateness_values, default=0.0),
            earliness_total, -setup_total, reroutes, changed)


def _projected_sequence_objective(
        machine: Machine, cal: WorkCalendar, cursor: datetime,
        committed: Sequence[Interval], sequence: Sequence[Job],
        first_placement: Placement, policy: ClusterPolicy) -> tuple:
    projected_cursor = cursor
    projected_intervals = list(committed)
    placements: List[Tuple[Job, Optional[Placement]]] = []
    unplanned_count = 0
    for index, job in enumerate(sequence):
        if index == 0:
            placement = first_placement
        else:
            remaining = sequence[index:]
            edd_head = remaining[0]
            head_due = edd_head.ord_ber_lev_dat or FAR_FUTURE
            job_due = job.ord_ber_lev_dat or FAR_FUTURE
            allow_setup = (job is edd_head
                           or job_due <= head_due + timedelta(days=policy.window_days))
            placement = _place(machine, cal, projected_cursor, job,
                               projected_intervals, allow_setup=allow_setup)
        placements.append((job, placement))
        if placement is None:
            unplanned_count += 1
            continue
        projected_intervals.append(Interval(placement.start, placement.end, job, False))
        projected_intervals.sort(key=lambda interval: interval.start)
        projected_cursor = placement.end
    cap_excesses: List[float] = []
    tardiness_values: List[float] = []
    tardiness_score_total = 0.0
    green_weight = 0.0
    earliness_total = 0.0
    setup_total = 0.0
    for job, placement in placements:
        if job.ord_ber_lev_dat is None:
            continue
        if placement is None:
            cap_excesses.append(1e9)
            tardiness_values.append(1e9)
            tardiness_score_total += 1e12
            continue
        completion = placement.end + job.downstream_delta
        late = tardiness_days_between(job.ord_ber_lev_dat, completion)
        cap_excesses.append(max(0.0, late - job.permitted_tardiness_days()))
        tardiness_values.append(late)
        tardiness_score_total += job.customer_weight * tardiness_score(
            late, policy.score_bands)
        if job.status_for(completion) == "Grön":
            green_weight += job.customer_weight
        earliness_total += max(0.0, -(pd.Timestamp(completion)
                                    - pd.Timestamp(job.ord_ber_lev_dat)
                                    ).total_seconds() / 86400.0)
        setup_total += placement.setup_saved
    breached = [value for value in cap_excesses if value > CAP_EPSILON_DAYS]
    return (len(breached), sum(cap_excesses), max(cap_excesses, default=0.0),
            -green_weight, tardiness_score_total, max(tardiness_values, default=0.0),
            earliness_total, -setup_total, unplanned_count)


def _place(machine: Machine, cal: WorkCalendar, cursor: datetime, job: Job,
           committed: Sequence[Interval], allow_setup: bool = True
           ) -> Optional[Placement]:
    duration = job.duration_full
    start = end = None
    flags: List[str] = []
    placed = False
    for _ in range(200):
        start, end, flags = cal.schedule(machine.kalendernr, cursor, duration)
        if start is None or end is None:
            return None
        clash = machine.conflict(start, end)
        if clash is None:
            placed = True
            break
        cursor = clash.end
    if not placed or start is None or end is None:
        return None
    pred_iv = None
    for iv in committed:
        if iv.end <= start + timedelta(seconds=EPS_SECONDS):
            if pred_iv is None or iv.end > pred_iv.end:
                pred_iv = iv
    setup_saved = 0.0
    cluster_ref: Optional[Job] = None
    if (allow_setup and pred_iv is not None
            and pred_iv.job.art_nr == job.art_nr and job.stalltid > 0):
        setup_saved = job.stalltid
        cluster_ref = pred_iv.job
        start, end, flags = cal.schedule(
            machine.kalendernr, start, job.duration_full - setup_saved)
        if start is None or end is None:
            return None
    return Placement(start, end, flags, setup_saved, cluster_ref)


def schedule_machine(machine: Machine, cal: WorkCalendar, now: datetime,
                     policy: Optional[ClusterPolicy] = None) -> None:
    policy = policy or ClusterPolicy()
    for j in machine.movable:
        j.setup_saved = 0.0
        j.cluster_ref = None
        j.predecessor = None
        j.successor = None
        j.pulled_forward = False
        j.cluster_cost_days = 0.0
        j.unplanned_reason = ""
        j.ai_start = None
        j.ai_end = None
        j.flags = [f for f in j.flags if not f.startswith("KAL:")]
    remaining = edd_order(machine.movable)
    committed: List[Interval] = list(machine.fixed)
    cursor = now
    prev_article: Optional[str] = None
    while remaining:
        edd_head = remaining[0]
        head_due = edd_head.ord_ber_lev_dat or FAR_FUTURE
        ranked: List[Tuple[tuple, Job, Placement]] = []
        for candidate in remaining:
            candidate_due = candidate.ord_ber_lev_dat or FAR_FUTURE
            within_cluster_window = (
                candidate is edd_head
                or candidate_due <= head_due + timedelta(days=policy.window_days))
            placement = _place(machine, cal, cursor, candidate, committed,
                               allow_setup=within_cluster_window)
            if placement is not None:
                tentative_sequence = [candidate] + [
                    job for job in remaining if job is not candidate]
                forecast = _projected_sequence_objective(
                    machine, cal, cursor, committed, tentative_sequence, placement, policy)
                ranked.append((forecast, candidate, placement))
        if not ranked:
            for job in remaining:
                job.unplanned_reason = (
                    f"rymmer inte inom känd kalendertäckning för kalendernr "
                    f"{machine.kalendernr}")
                job.flags.append("KAL: " + job.unplanned_reason)
            break
        _, job, placement = min(ranked, key=lambda item: item[0])
        remaining.remove(job)
        job.setup_saved = placement.setup_saved
        job.cluster_ref = placement.cluster_ref
        job.pulled_forward = (job is not edd_head and placement.setup_saved > 0
                              and placement.cluster_ref is not None)
        if job.pulled_forward:
            job.cluster_cost_days = max(
                0.0, tardiness_days_between(job.ord_ber_lev_dat,
                                           placement.end + job.downstream_delta)
                - tardiness_days_between(job.ord_ber_lev_dat, job.orig_tislutdat))
        job.prodgr_ai = machine.prodgr
        job.ai_start = placement.start
        job.ai_end = placement.end
        for f in placement.flags:
            job.flags.append("KAL: " + f)
        committed.append(Interval(placement.start, placement.end, job, False))
        committed.sort(key=lambda i: i.start)
        cursor = placement.end
        prev_article = job.art_nr
    machine.sequence = sorted(committed, key=lambda i: (i.start, i.end))
    for i, iv in enumerate(machine.sequence):
        iv.job.predecessor = machine.sequence[i - 1].job if i > 0 else None
        iv.job.successor = machine.sequence[i + 1].job if i + 1 < len(machine.sequence) else None


def apply_downstream(job: Job) -> None:
    if job.movable and job.ai_end is not None:
        job.ai_tislutdat = job.ai_end + job.downstream_delta
    elif job.movable and job.unplanned_reason:
        job.ai_start = None
        job.ai_end = None
        job.ai_tislutdat = None
        job.prodgr_ai = job.prodgr_org
    else:
        job.ai_start = job.orig_start
        job.ai_end = job.orig_end
        job.ai_tislutdat = job.orig_tislutdat
        job.prodgr_ai = job.prodgr_org
    job.ai_color_name = job.status_for(job.ai_tislutdat)
    job.ai_color_code = COLOR_CODES.get(job.ai_color_name, COLOR_CODES["Okänd"])


def repair_cap_violations(jobs: Sequence[Job], machines: Dict[str, Machine],
                          cal: WorkCalendar, now: datetime,
                          policy: Optional[ClusterPolicy] = None,
                          log: LogFn = _noop) -> int:
    policy = policy or ClusterPolicy()
    locked_count = 0
    for _ in range(len(jobs) + 1):
        offenders: List[Job] = []
        for job in jobs:
            if (not job.movable or job.cap_locked_original
                    or job.ord_ber_lev_dat is None):
                continue
            if job.ai_tislutdat is None and job.unplanned_reason:
                offenders.append(job)
                continue
            if job.ai_tislutdat is None:
                continue
            actual_late = tardiness_days_between(job.ord_ber_lev_dat, job.ai_tislutdat)
            baseline_late = tardiness_days_between(job.ord_ber_lev_dat, job.orig_tislutdat)
            if actual_late - job.permitted_tardiness_days() > CAP_EPSILON_DAYS:
                offenders.append(job)
        if not offenders:
            return locked_count
        changed = 0
        offenders.sort(key=lambda job: (job.ord_ber_lev_dat or FAR_FUTURE,
                                        job.orig_start or FAR_FUTURE, job.ao_nr))
        for job in offenders:
            if job.orig_start is None or job.orig_end is None:
                continue
            for machine in machines.values():
                if job in machine.movable:
                    machine.movable.remove(job)
            original_pg = job.prodgr_org
            if original_pg is None:
                continue
            machine = machines.get(original_pg)
            if machine is None:
                machine = Machine(original_pg, job.kalendernr)
                machines[original_pg] = machine
            if not any(interval.job is job for interval in machine.fixed):
                machine.add_fixed(job)
            job.cap_locked_original = True
            job.cap_repair_reason = (
                job.unplanned_reason
                or "kandidaten ökade orderns faktiska försening jämfört med originalet")
            job.prodgr_ai = original_pg
            job.ai_start = job.orig_start
            job.ai_end = job.orig_end
            job.ai_tislutdat = job.orig_tislutdat
            job.ai_color_name = job.status_for(job.ai_tislutdat)
            job.ai_color_code = COLOR_CODES.get(job.ai_color_name, COLOR_CODES["Okänd"])
            job.rerouted_from = None
            job.unplanned_reason = ""
            job.setup_saved = 0.0
            job.cluster_ref = None
            job.pulled_forward = False
            job.cluster_cost_days = 0.0
            job.flags = [flag for flag in job.flags if not flag.startswith("KAL:")]
            job.flags.append(
                "V7: återställd till originaltid/-maskin för att skydda maxförseningen")
            locked_count += 1
            changed += 1
            log(f"  Takreparation: {job.key} låses till originalplanen på {original_pg}")
        if not changed:
            return locked_count
        for machine in machines.values():
            schedule_machine(machine, cal, now, policy)
        for job in jobs:
            apply_downstream(job)
    return locked_count


def build_machines(jobs: Sequence[Job], prodgr_cal: Dict[str, int]) -> Dict[str, Machine]:
    machines: Dict[str, Machine] = {}

    def get(pg: str, kal: int) -> Machine:
        if pg not in machines:
            machines[pg] = Machine(pg, int(prodgr_cal.get(pg, kal)))
        return machines[pg]

    for j in jobs:
        pg = j.prodgr_ai or j.prodgr_org
        if pg is None:
            continue
        m = get(pg, j.kalendernr)
        if j.movable:
            m.movable.append(j)
        elif j.op_nr == 10:
            m.add_fixed(j)
    return machines


def detect_fixed_overlaps(machines: Dict[str, Machine]) -> List[str]:
    issues: List[str] = []
    for pg, m in sorted(machines.items()):
        blocks = sorted(m.fixed, key=lambda i: i.start)
        for a in range(len(blocks)):
            for b in range(a + 1, len(blocks)):
                if blocks[b].start >= blocks[a].end - timedelta(seconds=EPS_SECONDS):
                    break
                issues.append(
                    f"ProdGr {pg}: låsta operationer AO#{blocks[a].job.ao_nr} "
                    f"({fmt_dt(blocks[a].start)}–{fmt_dt(blocks[a].end)}) och "
                    f"AO#{blocks[b].job.ao_nr} ({fmt_dt(blocks[b].start)}–"
                    f"{fmt_dt(blocks[b].end)}) överlappar redan i källdatat. "
                    f"Båda är frysta och passerar oförändrade – "
                    f"maskinbeläggningen behöver ses över i Jeeves.")
    return issues


def restore_original_plan(jobs: Sequence[Job], machines: Dict[str, Machine]) -> None:
    for job in jobs:
        job.prodgr_ai = job.prodgr_org
        job.ai_start = job.orig_start
        job.ai_end = job.orig_end
        job.ai_tislutdat = job.orig_tislutdat
        job.ai_color_name = job.status_for(job.ai_tislutdat)
        job.ai_color_code = COLOR_CODES.get(job.ai_color_name, COLOR_CODES["Okänd"])
        job.cap_locked_original = False
        job.cap_repair_reason = ""
        job.setup_saved = 0.0
        job.cluster_ref = None
        job.pulled_forward = False
        job.cluster_cost_days = 0.0
        job.rerouted_from = None
        job.unplanned_reason = ""
        job.predecessor = None
        job.successor = None
        job.flags = [flag for flag in job.flags if not flag.startswith("KAL:")]
    for machine in machines.values():
        machine.movable = []
        machine.fixed = []
        machine.sequence = []
    for job in jobs:
        if job.op_nr != 10 or job.prodgr_org is None:
            continue
        machine = machines.get(job.prodgr_org)
        if machine is None:
            machine = Machine(job.prodgr_org, job.kalendernr)
            machines[job.prodgr_org] = machine
        if job.movable:
            machine.movable.append(job)
        else:
            machine.add_fixed(job)
    for machine in machines.values():
        machine.sequence = sorted(
            (Interval(job.orig_start, job.orig_end, job, not job.movable)
             for job in jobs if job.op_nr == 10 and job.prodgr_org == machine.prodgr
             and job.orig_start is not None and job.orig_end is not None),
            key=lambda interval: (interval.start, interval.end, interval.job.ao_nr))
        for index, interval in enumerate(machine.sequence):
            interval.job.predecessor = machine.sequence[index - 1].job if index > 0 else None
            interval.job.successor = (machine.sequence[index + 1].job
                                     if index + 1 < len(machine.sequence) else None)


def original_schedule_overlaps(jobs: Sequence[Job]) -> List[str]:
    by_machine: Dict[str, List[Job]] = {}
    for job in jobs:
        if (job.op_nr == 10 and job.prodgr_org is not None
                and job.orig_start is not None and job.orig_end is not None
                and job.orig_end > job.orig_start):
            by_machine.setdefault(job.prodgr_org, []).append(job)
    warnings: List[str] = []
    for prodgr, group in sorted(by_machine.items()):
        ordered = sorted(group, key=lambda job: (job.orig_start, job.orig_end))
        active: List[Job] = []
        for job in ordered:
            active = [prior for prior in active if prior.orig_end > job.orig_start]
            for prior in active:
                warnings.append(
                    f"Originalplanen har redan överlappande Op10 på ProdGr {prodgr}: "
                    f"AO#{prior.ao_nr} ({fmt_dt(prior.orig_start)}–"
                    f"{fmt_dt(prior.orig_end)}) och AO#{job.ao_nr} "
                    f"({fmt_dt(job.orig_start)}–{fmt_dt(job.orig_end)}).")
            active.append(job)
    return warnings


def build_prio_map(prio_df: pd.DataFrame) -> Dict[str, List[str]]:
    cols = [c for c in ["Prio1", "Prio2", "Prio3", "Prio4", "Prio5", "Prio6", "Prio7", "Prio8"]
            if c in prio_df.columns]
    out: Dict[str, List[str]] = {}
    for _, row in prio_df.iterrows():
        art = str(row["_artnr"])
        seq: List[str] = []
        for c in cols:
            pg = normalize_prodgr(row.get(c))
            if pg and pg not in seq:
                seq.append(pg)
        if seq:
            out[art] = seq
    return out


def _machine_red_set(machine: Machine) -> set:
    return {iv.job.idx for iv in machine.sequence
            if iv.job.movable and iv.job.ai_color_name == "Röd"}


def alternative_routing(machines: Dict[str, Machine], jobs: Sequence[Job],
                        prio_map: Dict[str, List[str]], cal: WorkCalendar,
                        now: datetime, prodgr_cal: Dict[str, int],
                        policy: Optional[ClusterPolicy] = None,
                        log: LogFn = _noop) -> int:
    policy = policy or ClusterPolicy()
    moved = 0
    for _pass in range(MAX_ROUTING_PASSES):
        moved_this_pass = 0
        candidates = [j for j in jobs if j.movable and j.ai_color_name != "Grön"
                      and j.prodgr_ai and not j.rerouted_from]
        candidates.sort(key=lambda j: (j.ord_ber_lev_dat or datetime(2999, 12, 31), j.ao_nr))
        for job in candidates:
            options = [pg for pg in prio_map.get(job.art_nr, []) if pg != job.prodgr_ai]
            if not options:
                continue
            source = machines[job.prodgr_ai]
            for target_pg in options:
                target = machines.get(target_pg)
                if target is None:
                    target = Machine(target_pg, int(prodgr_cal.get(target_pg, job.kalendernr)))
                    machines[target_pg] = target
                if not cal.has(target.kalendernr):
                    continue
                before_objective = plan_objective(jobs, policy)
                snapshot_t = _snapshot(target)
                snapshot_s = _snapshot(source)
                source.movable.remove(job)
                target.movable.append(job)
                schedule_machine(target, cal, now, policy)
                for iv in target.sequence:
                    apply_downstream(iv.job)
                schedule_machine(source, cal, now, policy)
                for iv in source.sequence:
                    apply_downstream(iv.job)
                job.rerouted_from = source.prodgr
                for candidate in jobs:
                    apply_downstream(candidate)
                if plan_objective(jobs, policy) < before_objective:
                    moved += 1
                    moved_this_pass += 1
                    log(f"  Omrutad {job.key}: {source.prodgr} -> {target_pg}")
                    break
                job.rerouted_from = None
                target.movable.remove(job)
                source.movable.append(job)
                _restore(target, snapshot_t, cal, now, policy)
                _restore(source, snapshot_s, cal, now, policy)
        if moved_this_pass == 0:
            break
    return moved


def _snapshot(machine: Machine) -> List[Job]:
    return list(machine.movable)


def _restore(machine: Machine, jobs_snapshot: List[Job], cal: WorkCalendar,
             now: datetime, policy: Optional[ClusterPolicy] = None) -> None:
    machine.movable = list(jobs_snapshot)
    schedule_machine(machine, cal, now, policy)
    for iv in machine.sequence:
        apply_downstream(iv.job)


def assign_priorities(jobs: Sequence[Job], log: LogFn = _noop) -> None:
    by_pg: Dict[str, List[Job]] = {}
    for j in jobs:
        pg = j.prodgr_ai or j.prodgr_org
        if pg is None:
            continue
        by_pg.setdefault(pg, []).append(j)
    far = datetime(2999, 12, 31)
    for pg, group in by_pg.items():
        far_end = datetime(2999, 12, 31)
        with_time = [j for j in group if j.ai_start is not None]
        without = [j for j in group if j.ai_start is None]
        with_time.sort(key=lambda j: (j.ai_start, j.ai_end or far_end, j.ao_nr))
        without.sort(key=lambda j: j.ao_nr)
        prio = 100
        for j in with_time + without:
            j.ai_prio = prio
            prio -= 1
    for pg, group in by_pg.items():
        prios = [j.ai_prio for j in group]
        if len(set(prios)) != len(prios):
            log(f"VARNING: prioritetskrock pa ProdGr {pg}")


def build_comments(jobs: Sequence[Job], machines: Dict[str, Machine],
                   cal: Optional["WorkCalendar"] = None,
                   optimization_fallback: bool = False,
                   policy: Optional[ClusterPolicy] = None) -> None:
    policy = policy or ClusterPolicy()
    freed: Dict[str, List[Job]] = {}
    for j in jobs:
        if j.rerouted_from:
            freed.setdefault(j.rerouted_from, []).append(j)

    def delay_txt(job: Job) -> str:
        if not DELAY_IN_WORKDAYS or cal is None:
            return ""
        n, estimated = lateness(job, job.ai_tislutdat, cal)
        if n <= 0:
            return ""
        ref = delay_calendar_label(delay_calendar_for(job, cal))
        extra = ", delvis uppskattad utanför kalendern" if estimated else ""
        return (f" Försening {int(n)} arbetsdagar ({ref}, helgdagar exkluderade; "
                f"{int(job.lateness_days(job.ai_tislutdat))} kalenderdygn{extra}).")

    for job in jobs:
        parts: List[str] = [f"AO#{job.ao_nr} (Order: {fmt_order(job.order_nr)}):"]
        if job.customer_numbers:
            parts.append(
                f"Kundorder {' | '.join(job.customer_order_numbers) or 'saknas'}; "
                f"kund(er) {' | '.join(job.customer_numbers)}; "
                f"kundvikt {job.customer_weight:g}; "
                f"maxförsening {job.max_tardiness_days:g} kalenderdygn.")
        else:
            parts.append(
                f"Kund saknas/okänd; standardvikt {job.customer_weight:g}; "
                f"generellt max {job.max_tardiness_days:g} kalenderdygn.")
        base = job.baseline_status_rule
        ai = job.ai_color_name or base
        if not job.movable:
            if job.already_started:
                parts.append(
                    f"Redan påbörjad (start {fmt_dt(job.orig_start)}) – ej omplanerad, "
                    f"ligger fast enligt ursprungligt schema på {job.prodgr_org}.")
            elif job.op_nr != 10:
                parts.append(
                    f"Op{job.op_nr} – endast Op10 omplaneras. Ligger fast på "
                    f"{job.prodgr_org} enligt ursprungligt schema.")
            elif job.ord_ber_lev_dat is None:
                parts.append(
                    "Saknar OrdBerLevDat – kan ej statusbedömas eller sekvenseras, "
                    f"fryst på {job.prodgr_org} med originalvärden.")
            elif job.frozen_reason.startswith("OpStatus"):
                txt = f" ({job.op_status_text})" if job.op_status_text else ""
                parts.append(
                    f"OpStatus {job.op_status}{txt} – ej omplaneringsbar, ligger fast "
                    f"på {job.prodgr_org}.")
            else:
                parts.append(f"Fryst: {job.frozen_reason}.")
            if job.op_nr == 10 and job.prodgr_ai in machines:
                pred, succ = job.predecessor, job.successor
                if pred is not None:
                    parts.append(
                        f"Föregås av AO#{pred.ao_nr}/Order:{fmt_order(pred.order_nr)} "
                        f"på {job.prodgr_ai}.")
                if succ is not None:
                    parts.append(
                        f"Nästa i maskinsekvensen: AO#{succ.ao_nr}/"
                        f"Order:{fmt_order(succ.order_nr)} (start {fmt_dt(succ.ai_start)}).")
            if job.ord_ber_lev_dat is None:
                parts.append(f"Status: {ai} (originalfärg behållen).")
            elif ai == base:
                parts.append(f"Status oförändrad: {ai}.")
            else:
                parts.append(f"Status: {base} -> {ai}.")
            late = delay_txt(job)
            if late:
                parts.append(late.strip())
        else:
            if optimization_fallback:
                parts.append(
                    "V7-säkerhetsåterfall: originaltid och originalmaskin behålls "
                    "eftersom V7-kandidaten bröt mot ett eller flera "
                    "godkännandekrav; kandidaten godkändes inte.")
            elif job.cap_locked_original:
                parts.append(
                    "Låst till originaltid och originalmaskin i V7:s lokala "
                    f"takreparation ({job.cap_repair_reason}); övriga säkra "
                    "omplaneringar behålls.")
            if ai != base:
                parts.append(f"Status ändrad: {base} -> {ai}.")
            else:
                parts.append(f"Status oförändrad: {ai}.")
            if job.rerouted_from:
                margin = job.margin_days(job.ai_tislutdat)
                outcome = f"slutstatus {ai}"
                if margin is not None:
                    outcome += f", marginal {margin:+d} dygn"
                parts.append(
                    f"Omrutad från {job.rerouted_from} → {job.prodgr_ai} "
                    f"(V7 valde alternativmaskinen; {outcome}).")
            if job.setup_saved > 0 and job.cluster_ref is not None:
                ref = job.cluster_ref
                frozen_txt = " (redan påbörjad order)" if not ref.movable else ""
                parts.append(
                    f"Ställtid sparad {fmt_hours(job.setup_saved)} "
                    f"(artikel-klustring på {job.art_nr} mot AO#{ref.ao_nr}{frozen_txt}).")
                if job.pulled_forward:
                    kostnad = ("utan att någon order tappar en leveransdag"
                               if job.cluster_cost_days <= 0 else
                               f"till en kostnad av {job.cluster_cost_days:g} "
                               f"förseningsdygn totalt")
                    parts.append(
                        f"Framdragen förbi leveransdatumordningen för klustringen – "
                        f"{kostnad}.")
            pred, succ = job.predecessor, job.successor
            if pred is not None:
                frozen_txt = " [fryst/redan påbörjad]" if not pred.movable else ""
                parts.append(
                    f"Körs efter AO#{pred.ao_nr}/Order:{fmt_order(pred.order_nr)}"
                    f"{frozen_txt} på {job.prodgr_ai} (väntar på avslut "
                    f"{fmt_dt(pred.ai_end)}).")
            else:
                parts.append(f"Först i kön på {job.prodgr_ai}.")
            if succ is not None:
                parts.append(
                    f"Påverkar start för AO#{succ.ao_nr}/"
                    f"Order:{fmt_order(succ.order_nr)} (väntar på avslut).")
            margin = job.margin_days(job.ai_tislutdat)
            margin_txt = "" if margin is None else f" Marginal {margin:+d} dygn → {ai}."
            parts.append(
                f"Ny Op10: {fmt_dt(job.ai_start)}–{fmt_dt(job.ai_end)} "
                f"({fmt_hours(job.duration_effective)}), "
                f"AI_TiSlutDat {fmt_dt(job.ai_tislutdat)} mot OrdBerLevDat "
                f"{fmt_dt(job.ord_ber_lev_dat, with_time=False)}.{margin_txt}"
                f"{delay_txt(job)}")
        released = freed.get(job.prodgr_ai or "", [])
        if released and job.movable and not job.rerouted_from:
            names = ", ".join(f"AO#{r.ao_nr}" for r in released[:3])
            parts.append(f"Kapacitet frigjord på {job.prodgr_ai} av omrutade: {names}.")
        for f in job.flags:
            parts.append("OBS: " + f.replace("KAL: ", "") + ".")
        job.comment = " ".join(parts)


def jobs_to_frame(jobs: Sequence[Job], run_ts: datetime,
                  include_extra: bool = True,
                  policy: Optional[ClusterPolicy] = None) -> pd.DataFrame:
    policy = policy or ClusterPolicy()
    rows = []
    for j in jobs:
        row = {
            "AoNr": j.ao_nr, "AoPos": j.ao_pos, "OpNr": j.op_nr,
            "ProdGr": j.prodgr_org, "ArtNr": j.art_nr, "AI_ProdGr": j.prodgr_ai,
            "Orginal_AoStartDatTid": j.orig_start, "Orginal_AoSlutDatTid": j.orig_end,
            "Orginal_TiSlutDat": j.orig_tislutdat, "Orginal_ColorCode": j.orig_color_code,
            "Orginal_ColorName": j.orig_color_name, "Orginal_OpkoPrioritet": j.orig_prio,
            "AI_AoStartDatTid": j.ai_start, "AI_AoSlutDatTid": j.ai_end,
            "AI_TiSlutDat": j.ai_tislutdat, "AI_ColorCode": j.ai_color_code,
            "AI_ColorName": j.ai_color_name, "AI_OpkoPrioritet": j.ai_prio,
            "AI_LogCreatDateTime": run_ts, "AI_Kommentar": j.comment,
        }
        if include_extra:
            row["Orginal_OrdBerLevDat"] = j.ord_ber_lev_dat
            row["KundOrderNr"] = " | ".join(j.customer_order_numbers) or None
            row["Kundnr"] = " | ".join(j.customer_numbers) or None
            row["Kundvikt"] = j.customer_weight
            row["MaxFörseningsdagar"] = j.max_tardiness_days
            original_late = (tardiness_days_between(j.ord_ber_lev_dat, j.orig_tislutdat)
                             if j.ord_ber_lev_dat is not None else None)
            ai_late = (tardiness_days_between(j.ord_ber_lev_dat, j.ai_tislutdat)
                       if j.ord_ber_lev_dat is not None and j.ai_tislutdat is not None else None)
            row["Orginal_TardinessScore"] = (
                tardiness_score(original_late, policy.score_bands)
                if original_late is not None else None)
            row["AI_TardinessScore"] = (
                tardiness_score(ai_late, policy.score_bands)
                if ai_late is not None else None)
            row["AI_CapExcessDygn"] = (
                max(0.0, ai_late - j.permitted_tardiness_days())
                if ai_late is not None else None)
            row["Orginal_WeightedTardinessScore"] = (
                j.customer_weight * tardiness_score(original_late, policy.score_bands)
                if original_late is not None else None)
            row["AI_WeightedTardinessScore"] = (
                j.customer_weight * tardiness_score(ai_late, policy.score_bands)
                if ai_late is not None else None)
        rows.append(row)
    cols = TEMPLATE_COLUMNS + (EXTRA_COLUMNS if include_extra else [])
    return pd.DataFrame(rows, columns=cols)


@dataclass
class RunResult:
    xlsx_path: str
    csv_path: str
    result: pd.DataFrame
    summary: List[Tuple[str, object]]
    stats: Dict[str, object]
    warnings: List[str]
    log_lines: List[str]


def delay_unit() -> str:
    return "arbetsdagar" if DELAY_IN_WORKDAYS else "dygn"


def _configured_calendar(job: Job):
    if DELAY_CALENDAR == COMPANY_CALENDAR:
        return COMPANY_CALENDAR
    if DELAY_CALENDAR in (None, "egen"):
        return job.kalendernr
    return int(DELAY_CALENDAR)


def delay_calendar_for(job: Job, cal: Optional["WorkCalendar"]):
    if cal is None:
        return None
    for kal in (_configured_calendar(job), COMPANY_CALENDAR):
        if kal is not None and cal.has_workdays(kal):
            return cal._key(kal)
    return None


def delay_basis() -> str:
    if not DELAY_IN_WORKDAYS:
        return "kalenderdygn"
    if DELAY_CALENDAR == COMPANY_CALENDAR:
        return "företagskalender"
    if DELAY_CALENDAR in (None, "egen"):
        return "orderns egen kalender"
    return f"kal {int(DELAY_CALENDAR)}"


def delay_calendar_label(kal) -> str:
    if kal is None:
        return "saknar kalender"
    if kal == COMPANY_CALENDAR:
        return "företagskalender"
    return f"kal {kal}"


def lateness(job: Job, finish: Optional[datetime],
             cal: Optional["WorkCalendar"] = None) -> Tuple[float, bool]:
    if job.ord_ber_lev_dat is None or finish is None:
        return 0.0, False
    if not DELAY_IN_WORKDAYS or cal is None:
        return job.lateness_days(finish), False
    kal = delay_calendar_for(job, cal)
    due = pd.Timestamp(job.ord_ber_lev_dat).date()
    end = pd.Timestamp(finish).date()
    if kal is None:
        return float(max(0, (end - due).days)), True
    n, estimated = cal.working_days_after(kal, due, end)
    return float(n), estimated


def tardiness_stats(jobs: Sequence[Job],
                    cal: Optional["WorkCalendar"] = None) -> Dict[str, object]:
    before_total = after_total = 0.0
    before_red_total = after_red_total = 0.0
    worst_job = None
    worst_days = 0.0
    later = 0
    estimated_orders = 0
    for j in jobs:
        if j.ord_ber_lev_dat is None:
            continue
        b, est_b = lateness(j, j.orig_tislutdat, cal)
        if j.unplanned_reason:
            a, est_a = b, est_b
        else:
            a, est_a = lateness(j, j.ai_tislutdat, cal)
        if (est_b and b) or (est_a and a):
            estimated_orders += 1
        before_total += b
        after_total += a
        if j.baseline_status_rule == "Röd":
            before_red_total += b
            after_red_total += a
        if a > b:
            later += 1
            if a - b > worst_days:
                worst_days = a - b
                worst_job = j
    return {
        "late_days_before": round(before_total, 1),
        "late_days_after": round(after_total, 1),
        "late_days_before_red": round(before_red_total, 1),
        "late_days_after_red": round(after_red_total, 1),
        "worse_count": later, "worst_days": round(worst_days, 1),
        "worst_ao": worst_job.ao_nr if worst_job else None,
        "late_unit": delay_unit(), "late_basis": delay_basis(),
        "late_estimated_orders": estimated_orders,
    }


def build_summary(jobs: Sequence[Job], now: datetime, run_ts: datetime,
                  moved: int, cal: WorkCalendar, warnings: Sequence[str],
                  policy: Optional[ClusterPolicy] = None,
                  optimization_fallback: bool = False,
                  rejected_candidate: Optional[Dict[str, object]] = None,
                  lock_horizon_hours: float = LOCK_HORIZON_HOURS
                  ) -> List[Tuple[str, object]]:
    lock_horizon_hours = validate_lock_horizon_hours(lock_horizon_hours)
    _lock_horizon_end(now, lock_horizon_hours)
    policy = policy or ClusterPolicy()
    rejected_candidate = rejected_candidate or {}
    jeeves = {"Grön": 0, "Gul": 0, "Röd": 0, "Okänd": 0}
    before = {"Grön": 0, "Gul": 0, "Röd": 0, "Okänd": 0}
    after = {"Grön": 0, "Gul": 0, "Röd": 0, "Okänd": 0}
    transitions: Dict[Tuple[str, str], int] = {}
    for j in jobs:
        jeeves[j.baseline_status] = jeeves.get(j.baseline_status, 0) + 1
        b = j.baseline_status_rule
        a = j.ai_color_name or b
        before[b] = before.get(b, 0) + 1
        after[a] = after.get(a, 0) + 1
        transitions[(b, a)] = transitions.get((b, a), 0) + 1
    clustered = [j for j in jobs if j.setup_saved > 0]
    saved_hours = sum(j.setup_saved for j in clustered)
    frozen_notop10 = sum(1 for j in jobs if j.op_nr != 10)
    frozen_started = sum(1 for j in jobs if j.op_nr == 10 and j.already_started)
    frozen_lock = sum(1 for j in jobs if j.locked_horizon)
    frozen_nostart = sum(1 for j in jobs if j.frozen_reason == "saknar ursprunglig Op10-start")
    frozen_status = sum(1 for j in jobs if j.frozen_reason.startswith("OpStatus"))
    frozen_nodue = sum(1 for j in jobs if j.frozen_reason == "saknar OrdBerLevDat")
    frozen_calendar = sum(1 for j in jobs if j.frozen_reason.startswith("saknar användbar kalender"))
    frozen_duration = sum(1 for j in jobs if j.frozen_reason == "saknar Op10-operationstid")
    movable = sum(1 for j in jobs if j.movable)
    pulled = sum(1 for j in jobs if j.pulled_forward)
    td = tardiness_stats(jobs, cal)
    v7 = v7_tardiness_metrics(jobs, policy)
    green_weight_before = sum(j.customer_weight for j in jobs
                              if j.baseline_status_rule == "Grön")
    green_weight_after = sum(j.customer_weight for j in jobs
                             if (j.ai_color_name or j.baseline_status_rule) == "Grön")
    rows: List[Tuple[str, object]] = [
        ("AI-Optimering V7 – Sammanfattning", None),
        ("Datum", run_ts.strftime("%Y-%m-%d %H:%M:%S")),
        ("NOW_Stockholm (fryslinje)", now.strftime("%Y-%m-%d %H:%M:%S")),
        ("Motorversion", f"v{VERSION}"),
        ("Låshorisont (timmar)", lock_horizon_hours),
        (None, None),
        ("URSPRUNGLIG STATUS", "Antal"),
        ("Grön", before.get("Grön", 0)), ("Gul", before.get("Gul", 0)),
        ("Röd", before.get("Röd", 0)), ("Okänd", before.get("Okänd", 0)),
        ("Totalt", len(jobs)),
        ("(bedömd med samma statusgräns som AI – jämförbar)", None),
        (None, None),
        ("JEEVES EGEN FÄRG I UNDERLAGET", "Antal"),
        ("Grön", jeeves.get("Grön", 0)), ("Gul", jeeves.get("Gul", 0)),
        ("Röd", jeeves.get("Röd", 0)), ("Okänd", jeeves.get("Okänd", 0)),
        ("(kolumnen ColorName, oförändrad – annan gräns än AI:s)", None),
        (None, None),
        ("EFTER OPTIMERING", "Antal"),
        ("Grön", after.get("Grön", 0)), ("Gul", after.get("Gul", 0)),
        ("Röd", after.get("Röd", 0)), ("Okänd", after.get("Okänd", 0)),
        ("Totalt", len(jobs)),
        (None, None), ("FÖRBÄTTRING", None),
        ("Röda → Grön", transitions.get(("Röd", "Grön"), 0)),
        ("Röda → Gul", transitions.get(("Röd", "Gul"), 0)),
        ("Gula → Grön", transitions.get(("Gul", "Grön"), 0)),
        ("Gröna → Röd (försämring)", transitions.get(("Grön", "Röd"), 0)),
        ("Gula → Röd (försämring)", transitions.get(("Gul", "Röd"), 0)),
        ("Kundviktad grönprioritet", f"{green_weight_before:g} → {green_weight_after:g}"),
        ("Ordrar som fick alternativ maskin", moved), (None, None),
        ("Fortfarande röda i vald plan", after.get("Röd", 0)), (None, None),
        (f"FÖRSENING I {td['late_unit'].upper()}", "Före → Efter"),
        (f"Totalt antal förseningsdagar ({td['late_unit']})",
         f"{td['late_days_before']:g} → {td['late_days_after']:g}"),
        ("Varav order som var röda i baslinjen",
         f"{td['late_days_before_red']:g} → {td['late_days_after_red']:g}"),
        ("Antal order som blivit mer försenade", td["worse_count"]),
        (f"Största enskilda försämring ({td['late_unit']})",
         f"{td['worst_days']:g}" + (f"  (AO#{td['worst_ao']})" if td["worst_ao"] else "")),
        (None, None), ("V7-MÅL OCH FÖRSENINGSSTAK", "Före → Efter"),
        ("Kundviktad förseningspoäng",
         f"{v7['tardiness_score_before']:g} → {v7['tardiness_score_after']:g}"),
        ("Order över förseningsstaket", v7["cap_breach_count"]),
        ("Order låsta till originalslot för att skydda taket",
         sum(1 for j in jobs if j.cap_locked_original)),
        ("Total ökning över förseningsstaket (kalenderdygn)", v7["cap_excess_days"]),
        ("Största ökning för en order (kalenderdygn)", v7["worst_cap_excess_days"]),
        ("Order över angivet max i originalplan", v7["baseline_over_limit_count"]),
        ("Order över angivet max i vald plan", v7["after_over_limit_count"]),
        ("Generellt max förseningsdagar", policy.global_max_tardiness_days),
        ("Förseningsstaket uppnått", "Ja" if v7["cap_met"] else "Nej – kandidat avvisad"),
        ("V7-planstatus", "Originalplan återställd – kandidat underkänd"
         if optimization_fallback else "V7-förslag"),
        ("Avvisad kandidats order över taket", rejected_candidate.get("cap_breach_count", 0)),
        ("Avvisad kandidats totala taköverskridande (dygn)",
         rejected_candidate.get("cap_excess_days", 0.0)),
        ("Oplanerade order i avvisad kandidat", rejected_candidate.get("unplanned_count", 0)),
        ("Order ändrade jämfört med originalet", sum(1 for j in jobs if j.movable and (
            j.ai_start != j.orig_start or j.prodgr_ai != j.prodgr_org))),
        ("Oplanerade order utan kalendertäckning", v7["unplanned_count"]),
        ("Poängtrappa (hela dagar: från–till = poäng)",
         "; ".join(
             f"{lower}–{upper if upper is not None else 'därefter'} = {score:g}"
             for lower, upper, score in policy.score_bands)),
        ("Ordervikt", "Kundvikt; okänd/saknad kund = 1; stycktid påverkar bara kapacitet"),
    ] + ([("Arbetsdagar räknas mot", td["late_basis"])] if DELAY_IN_WORKDAYS else []) + [
        (None, None), ("STÄLLTIDSOPTIMERING", None),
        ("Antal ställtidsbesparingar (klustring)", len(clustered)),
        ("Totalt sparade ställtidstimmar", round(saved_hours, 2)),
        ("Order framdragna förbi EDD för klustring", pulled),
        ("Klusterfönster (dygn)", policy.window_days),
        (None, None), ("STATUSGRÄNS", None),
        ("Grön", f"marginal > {GREEN_MARGIN_DAYS} dygn till OrdBerLevDat"),
        ("Gul", f"marginal = {GREEN_MARGIN_DAYS} dygn"),
        ("Röd", f"marginal < {GREEN_MARGIN_DAYS} dygn (inkl. exakt på leveransdagen)"),
        (None, None), ("POPULATION OCH FRYSNING", None),
        ("Rader totalt i underlaget", len(jobs)),
        ("Omplanerade (rörliga) Op10-rader", movable),
        ("Frysta: redan påbörjade (aostartdattid ≤ NOW_Stockholm)", frozen_started),
        (f"Frysta: inom {lock_horizon_hours:g}-timmars horisont", frozen_lock),
        ("Frysta: saknar ursprunglig Op10-start", frozen_nostart),
        ("Frysta: OpStatus ≠ 0", frozen_status),
        ("Frysta: saknar OrdBerLevDat", frozen_nodue),
        ("Frysta: saknar användbar kalender", frozen_calendar),
        ("Frysta: saknar Op10-operationstid", frozen_duration),
        ("Frysta: ej Op10", frozen_notop10),
        ("Summa frysta", len(jobs) - movable),
        (None, None), ("KALENDER", None), ("Kalendertäckning", cal.coverage_text()),
    ]
    if warnings:
        rows.append((None, None))
        rows.append(("DATAVALIDERING – ANMÄRKNINGAR", len(warnings)))
        for w in warnings:
            rows.append(("• " + w, None))
    return rows


HEADER_FILL = PatternFill("solid", fgColor="1F3864")
HEADER_FONT = Font(color="FFFFFF", bold=True, size=10)
THIN = Side(style="thin", color="BFBFBF")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
ROW_FILLS = {
    "Grön": PatternFill("solid", fgColor="D8F0D0"),
    "Röd": PatternFill("solid", fgColor="FBD5CB"),
    "Gul": PatternFill("solid", fgColor="FFF4C2"),
    "Blå": PatternFill("solid", fgColor="D6E6FA"),
    "Okänd": PatternFill("solid", fgColor="E5E8E8"),
}


def _write_frame(ws, df: pd.DataFrame, date_cols: Sequence[str],
                 color_col: Optional[str] = None) -> None:
    ws.append(list(df.columns))
    for cell in ws[1]:
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = BORDER
    date_idx = {df.columns.get_loc(c) + 1 for c in date_cols if c in df.columns}
    color_idx = df.columns.get_loc(color_col) + 1 if color_col in df.columns else None
    for record in df.itertuples(index=False, name=None):
        ws.append([_cell_value(v) for v in record])
        r = ws.max_row
        fill = None
        if color_idx:
            fill = ROW_FILLS.get(ws.cell(row=r, column=color_idx).value)
        for c in range(1, len(df.columns) + 1):
            cell = ws.cell(row=r, column=c)
            cell.border = BORDER
            if c in date_idx:
                cell.number_format = EXCEL_DATE_FORMAT
            if fill is not None:
                cell.fill = fill
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions


def _cell_value(v):
    if v is None:
        return None
    if isinstance(v, float) and pd.isna(v):
        return None
    if isinstance(v, pd.Timestamp):
        return None if pd.isna(v) else v.to_pydatetime()
    if hasattr(v, "item") and not isinstance(v, (str, bytes, datetime)):
        try:
            return v.item()
        except (ValueError, AttributeError):
            return v
    return v


def _autosize(ws, max_width: int = 60) -> None:
    widths: Dict[int, int] = {}
    for row in ws.iter_rows():
        for cell in row:
            if cell.value is None:
                continue
            length = len(str(cell.value))
            if isinstance(cell.value, datetime):
                length = 16
            widths[cell.column] = min(max(widths.get(cell.column, 10), length + 2), max_width)
    for col, w in widths.items():
        ws.column_dimensions[get_column_letter(col)].width = w


def write_outputs(src: SourceData, result: pd.DataFrame,
                  summary: List[Tuple[str, object]],
                  input_path: str, output_dir: str, run_ts: datetime,
                  log: LogFn = _noop) -> Tuple[str, str]:
    os.makedirs(output_dir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(input_path))[0]
    stamp = run_ts.strftime("%Y%m%d%H%M%S")
    xlsx_path = os.path.join(output_dir, f"{stem}_v7_resultat_{stamp}.xlsx")
    csv_path = os.path.join(output_dir, f"{stem}_v7_resultat_{stamp}.csv")
    wb = Workbook()
    wb.remove(wb.active)
    src_map = {
        SHEET_BASELINE: src.baseline,
        SHEET_OPERATIONS: src.operations.drop(columns=["_prodgr"], errors="ignore"),
        SHEET_CALENDAR: src.calendar.drop(columns=["_date"], errors="ignore"),
        SHEET_PRIO: src.prio.drop(columns=["_artnr"], errors="ignore"),
    }
    if not src.customer_config.empty:
        src_map[SHEET_CUSTOMER_CONFIG] = src.customer_config
    for name, df in src_map.items():
        ws = wb.create_sheet(name)
        dcols = [c for c in df.columns if pd.api.types.is_datetime64_any_dtype(df[c])]
        _write_frame(ws, df, dcols)
        _autosize(ws, 30)
        log(f"  Skrev källflik {name} ({len(df)} rader)")
    ws = wb.create_sheet(SHEET_RESULT)
    _write_frame(ws, result, DATE_COLUMNS, color_col="AI_ColorName")
    _autosize(ws, 70)
    ws.column_dimensions[get_column_letter(result.columns.get_loc("AI_Kommentar") + 1)].width = 100
    log(f"  Skrev {SHEET_RESULT} ({len(result)} rader)")
    ws = wb.create_sheet(SHEET_SUMMARY)
    title_font = Font(bold=True, size=12, color="1F3864")
    section_font = Font(bold=True, color="FFFFFF")
    section_fill = PatternFill("solid", fgColor="1F3864")
    for label, value in summary:
        ws.append([label, value])
        r = ws.max_row
        if label is None:
            continue
        text = str(label)
        if r == 1:
            ws.cell(row=r, column=1).font = title_font
        elif text.isupper() or text.startswith(("URSPRUNGLIG", "EFTER", "FÖRBÄTTRING")):
            for c in (1, 2):
                ws.cell(row=r, column=c).font = section_font
                ws.cell(row=r, column=c).fill = section_fill
        elif text in ROW_FILLS:
            ws.cell(row=r, column=1).fill = ROW_FILLS[text]
            ws.cell(row=r, column=2).fill = ROW_FILLS[text]
    ws.column_dimensions["A"].width = 52
    ws.column_dimensions["B"].width = 46
    for row in ws.iter_rows(min_col=2, max_col=2):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    wb.save(xlsx_path)
    log(f"Excel skriven: {xlsx_path}")
    csv_df = result.copy()
    for c in DATE_COLUMNS:
        if c in csv_df.columns:
            csv_df[c] = pd.to_datetime(csv_df[c], errors="coerce").dt.strftime(CSV_DATE_FORMAT)
    csv_df.to_csv(csv_path, sep=";", index=False, encoding="utf-8-sig",
                  quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
    log(f"CSV skriven: {csv_path}")
    return xlsx_path, csv_path


@dataclass
class PlanOutcome:
    jobs: List[Job]
    result: pd.DataFrame
    summary: List[Tuple[str, object]]
    stats: Dict[str, object]
    warnings: List[str]
    machines: Dict[str, Machine]
    calendar: "WorkCalendar"
    now: datetime
    run_ts: datetime


def compute_plan(src: SourceData, now: Optional[datetime] = None,
                 policy: Optional[ClusterPolicy] = None,
                 run_ts: Optional[datetime] = None,
                 log: LogFn = _noop,
                 lock_horizon_hours: float = LOCK_HORIZON_HOURS) -> PlanOutcome:
    """Beräkna en källagnostisk V7-plan utan filskrivning eller global mutation."""
    lock_horizon_hours = validate_lock_horizon_hours(lock_horizon_hours)
    policy = policy or ClusterPolicy()
    now = now or now_stockholm()
    _lock_horizon_end(now, lock_horizon_hours)
    run_ts = run_ts or datetime.now()
    _log = log
    _log(f"Planeringspolicy: {policy.describe(lock_horizon_hours)}")
    _log("Bygger skiftkalender ...")
    cal = WorkCalendar(src.calendar, now, _log)
    _log(f"  Kalendertäckning: {cal.coverage_text()}")
    jobs, warnings = build_jobs(
        src, cal, now, _log, lock_horizon_hours=lock_horizon_hours,
        max_tardiness_days=policy.global_max_tardiness_days)
    warnings.extend(cal.warnings)
    prodgr_cal = (src.operations.dropna(subset=["_prodgr"])
                  .groupby("_prodgr")["kalendernr"]
                  .agg(lambda s: int(s.mode().iloc[0])).to_dict())
    red_by_pg: Dict[str, int] = {}
    for j in jobs:
        if j.baseline_status == "Röd" and j.prodgr_org:
            red_by_pg[j.prodgr_org] = red_by_pg.get(j.prodgr_org, 0) + 1
    top = sorted(red_by_pg.items(), key=lambda kv: -kv[1])[:5]
    if top:
        _log("Flaskhalsar (flest röda): " + ", ".join(f"{pg} ({n})" for pg, n in top))
    _log("Sekvenserar och kapacitetsberäknar per produktionsgrupp ...")
    for j in jobs:
        j.prodgr_ai = j.prodgr_org
    machines = build_machines(jobs, prodgr_cal)
    overlap_issues = detect_fixed_overlaps(machines)
    for issue in overlap_issues:
        _log("VARNING: " + issue)
    warnings.extend(overlap_issues)
    for m in machines.values():
        schedule_machine(m, cal, now, policy)
    for j in jobs:
        apply_downstream(j)
    _log(f"  {len(machines)} produktionsgrupper schemalagda.")
    reds_before_routing = sum(1 for j in jobs if j.movable and j.ai_color_name == "Röd")
    _log(f"  Röda efter EDD + artikel-klustring: {reds_before_routing}")
    _log("Provar alternativruttning för kvarvarande röda order ...")
    prio_map = build_prio_map(src.prio)
    moved = alternative_routing(machines, jobs, prio_map, cal, now, prodgr_cal, policy, _log)
    _log(f"  {moved} order flyttade till alternativmaskin.")
    for m in machines.values():
        schedule_machine(m, cal, now, policy)
    for j in jobs:
        apply_downstream(j)
    candidate_before_repair = v7_tardiness_metrics(jobs, policy)
    cap_repaired_count = repair_cap_violations(jobs, machines, cal, now, policy, _log)
    rejected_candidate = v7_tardiness_metrics(jobs, policy)
    optimization_fallback = (not rejected_candidate["cap_met"]
                             or rejected_candidate["unplanned_count"] > 0)
    if cap_repaired_count:
        _log(f"  Takreparation: {cap_repaired_count} order låsta till originalslot; "
             f"{sum(1 for j in jobs if j.movable) - cap_repaired_count} övriga "
             "order får behålla V7-omplaneringen.")
        for job in jobs:
            if job.cap_locked_original:
                detail = (f"AO#{job.ao_nr}/Order:{fmt_order(job.order_nr)} låstes till "
                          f"originalslot i V7:s maxreparation: {job.cap_repair_reason}.")
                warnings.append(detail)
                _log("VARNING: " + detail)
        for issue in detect_fixed_overlaps(machines):
            if issue not in warnings:
                warnings.append(issue)
                _log("VARNING: " + issue)
    if optimization_fallback:
        msg = (
            "V7-SÄKERHETSÅTERFALL: optimeringskandidaten uppfyllde inte godkännandekraven: "
            f"{rejected_candidate['cap_breach_count']} order över individuellt "
            f"förseningsstak ({rejected_candidate['cap_excess_days']} extra dygn), "
            f"{rejected_candidate['unplanned_count']} oplanerade order. Kandidaten "
            "har avvisats och originaltider/ursprungsmaskiner behålls. Detta "
            "återfall visar inte att en förbättrad, komplett och cap-säker plan är omöjlig.")
        warnings.append(msg)
        _log("VARNING: " + msg)
        for job in jobs:
            if job.unplanned_reason:
                detail = (f"AO#{job.ao_nr}/Order:{fmt_order(job.order_nr)} var oplanerad "
                          f"i den avvisade V7-kandidaten: {job.unplanned_reason}.")
                warnings.append(detail)
                _log("VARNING: " + detail)
        restore_original_plan(jobs, machines)
        moved = 0
        cap_repaired_count = 0
        for issue in original_schedule_overlaps(jobs):
            warnings.append(issue)
            _log("VARNING: " + issue)
    assign_priorities(jobs, _log)
    build_comments(jobs, machines, cal, optimization_fallback, policy)
    for job in jobs:
        if job.unplanned_reason:
            msg = (f"AO#{job.ao_nr}/Order:{fmt_order(job.order_nr)} saknar "
                   f"planerad sluttid: {job.unplanned_reason}.")
            warnings.append(msg)
            _log("VARNING: " + msg)
        if job.ord_ber_lev_dat is not None:
            baseline_late = tardiness_days_between(job.ord_ber_lev_dat, job.orig_tislutdat)
            ai_late = (tardiness_days_between(job.ord_ber_lev_dat, job.ai_tislutdat)
                       if job.ai_tislutdat is not None else None)
            score_text = (
                f"Kundviktad förseningspoäng: original "
                f"{job.customer_weight * tardiness_score(baseline_late, policy.score_bands):.3f}, "
                f"AI {job.customer_weight * tardiness_score(ai_late, policy.score_bands):.3f}."
                if ai_late is not None else
                f"Kundviktad förseningspoäng: original "
                f"{job.customer_weight * tardiness_score(baseline_late, policy.score_bands):.3f}; "
                "AI ej beräkningsbar eftersom ordern saknar planerad sluttid.")
            job.comment += " " + score_text
            if ai_late is not None:
                cap_excess = max(0.0, ai_late - job.permitted_tardiness_days())
                if cap_excess > CAP_EPSILON_DAYS:
                    job.comment += (f" Förseningsstaket överskrids med {cap_excess:.3f} "
                                    "kalenderdygn.")
    td = tardiness_stats(jobs, cal)
    v7 = v7_tardiness_metrics(jobs, policy)
    if DELAY_IN_WORKDAYS:
        fixed = DELAY_CALENDAR not in (COMPANY_CALENDAR, None, "egen")
        if fixed and not cal.has_workdays(DELAY_CALENDAR):
            warnings.append(
                f"Förseningen ska räknas i arbetsdagar mot kalendernr "
                f"{DELAY_CALENDAR}, men den kalendern finns inte i underlaget. "
                f"Företagskalendern har använts i stället.")
            _log("VARNING: " + warnings[-1])
        if not cal.has_workdays(COMPANY_CALENDAR):
            warnings.append("Skiftkalendern innehåller inga arbetsdagar – förseningen har "
                            "räknats i kalenderdygn.")
            _log("VARNING: " + warnings[-1])
        if td["late_estimated_orders"]:
            first = min((lo for lo, _ in cal.day_coverage.values()), default=None)
            start = f" ({datetime.fromordinal(first):%Y-%m-%d})" if first else ""
            warnings.append(
                f"{td['late_estimated_orders']} order har en förseningsperiod som "
                f"går utanför skiftkalendern{start}. Arbetsdagarna där har räknats "
                f"efter kalenderns veckomönster – röda dagar utanför kalendern "
                f"kan inte identifieras och räknas därför som arbetsdagar.")
            _log("VARNING: " + warnings[-1])
    result = jobs_to_frame(jobs, run_ts, policy=policy)
    summary = build_summary(
        jobs, now, run_ts, moved, cal, warnings, policy,
        optimization_fallback=optimization_fallback,
        rejected_candidate=rejected_candidate if optimization_fallback else None,
        lock_horizon_hours=lock_horizon_hours,
    )
    before_red = sum(1 for j in jobs if j.baseline_status_rule == "Röd")
    after_red = sum(1 for j in jobs if (j.ai_color_name or j.baseline_status_rule) == "Röd")
    green_weight_before = sum(j.customer_weight for j in jobs
                              if j.baseline_status_rule == "Grön")
    green_weight_after = sum(j.customer_weight for j in jobs
                             if (j.ai_color_name or j.baseline_status_rule) == "Grön")
    stats = {
        "lock_horizon_hours": lock_horizon_hours,
        "rows": len(jobs), "movable": sum(1 for j in jobs if j.movable),
        "changed": sum(1 for j in jobs if j.movable and (
            j.ai_start != j.orig_start or j.prodgr_ai != j.prodgr_org)),
        "optimization_fallback": optimization_fallback,
        "cap_repaired_count": cap_repaired_count,
        "candidate_before_repair_cap_breach_count": candidate_before_repair["cap_breach_count"],
        "candidate_before_repair_cap_excess_days": candidate_before_repair["cap_excess_days"],
        "candidate_before_repair_unplanned_count": candidate_before_repair["unplanned_count"],
        "frozen_started": sum(1 for j in jobs if j.already_started),
        "frozen_lock_horizon": sum(1 for j in jobs if j.locked_horizon),
        "unplanned_count": v7["unplanned_count"],
        "red_before": before_red, "red_after": after_red, "red_fixed": before_red - after_red,
        "green_before": sum(1 for j in jobs if j.baseline_status_rule == "Grön"),
        "green_after": sum(1 for j in jobs if (j.ai_color_name or j.baseline_status_rule) == "Grön"),
        "green_weight_before": green_weight_before,
        "green_weight_after": green_weight_after,
        "yellow_before": sum(1 for j in jobs if j.baseline_status_rule == "Gul"),
        "yellow_after": sum(1 for j in jobs if (j.ai_color_name or j.baseline_status_rule) == "Gul"),
        "rerouted": moved, "pulled_forward": sum(1 for j in jobs if j.pulled_forward),
        "policy": policy, "clustered": sum(1 for j in jobs if j.setup_saved > 0),
        "setup_hours_saved": round(sum(j.setup_saved for j in jobs), 2),
        "machines": sum(1 for m in machines.values() if m.movable or m.fixed),
        "now_stockholm": now, "run_ts": run_ts,
    }
    stats.update(td)
    stats.update(v7)
    if optimization_fallback:
        stats.update({
            "rejected_cap_breach_count": rejected_candidate["cap_breach_count"],
            "rejected_cap_excess_days": rejected_candidate["cap_excess_days"],
            "rejected_worst_cap_excess_days": rejected_candidate["worst_cap_excess_days"],
            "rejected_unplanned_count": rejected_candidate["unplanned_count"],
        })
    unit = td["late_unit"]
    _log(f"KLART. Röd {before_red} → {after_red} "
         f"({before_red - after_red} lösta), {moved} omrutade, "
         f"{stats['clustered']} klustrade ({stats['setup_hours_saved']} h sparad "
         f"ställtid, varav {stats['pulled_forward']} framdragna förbi EDD).")
    _log(f"       Försening totalt ({unit}): {stats['late_days_before']:g} "
         f"→ {stats['late_days_after']:g}; {stats['worse_count']} order blev mer försenade "
         f"(värst {stats['worst_days']:g} {unit}).")
    _log(f"       V7 kundviktad poäng: {stats['tardiness_score_before']:g} → "
         f"{stats['tardiness_score_after']:g}; cap uppnått: "
         f"{'ja' if stats['cap_met'] else 'nej'}; oplanerade: {stats['unplanned_count']}.")
    if optimization_fallback:
        _log("       Säkerhetsåterfall: originalplanen behölls; "
             f"avvisad kandidat hade {rejected_candidate['cap_breach_count']} "
             "order över individuellt tak.")
    return PlanOutcome(jobs=jobs, result=result, summary=summary, stats=stats,
                       warnings=warnings, machines=machines, calendar=cal, now=now, run_ts=run_ts)


def run_replanning(input_path: str, output_dir: Optional[str] = None,
                   now: Optional[datetime] = None,
                   policy: Optional[ClusterPolicy] = None,
                   write_files: bool = True,
                   log: Optional[LogFn] = None,
                   lock_horizon_hours: float = LOCK_HORIZON_HOURS) -> RunResult:
    """Läs Excel, beräkna V7 och skriv valfria leveransfiler.

    lock_horizon_hours är körningslokala timmar (förval 4); strängar med
    decimalpunkt eller decimalkomma accepteras av samma validering som UI:t.
    Övriga argument och returvärden är kompatibla med V5.
    """
    lock_horizon_hours = validate_lock_horizon_hours(lock_horizon_hours)
    policy = policy or ClusterPolicy()
    lines: List[str] = []

    def _log(msg: str) -> None:
        lines.append(msg)
        if log:
            log(msg)

    run_ts = datetime.now()
    now = now or now_stockholm()
    _lock_horizon_end(now, lock_horizon_hours)
    _log(f"=== AI Omplanering v{VERSION} ===")
    _log(f"NOW_Stockholm = {now:%Y-%m-%d %H:%M:%S} ({TZ_NAME})")
    _log(f"Klustringspolicy: {policy.describe(lock_horizon_hours)}")
    _log(f"Statusgräns: marginal > {GREEN_MARGIN_DAYS} dygn = Grön, "
         f"= {GREEN_MARGIN_DAYS} dygn = Gul, därunder = Röd")
    if output_dir is None:
        output_dir = os.path.join(os.path.dirname(os.path.abspath(input_path)), "output")
    src = load_source(input_path, _log)
    outcome = compute_plan(src, now=now, policy=policy, run_ts=run_ts, log=_log,
                           lock_horizon_hours=lock_horizon_hours)
    if write_files:
        _log("Skriver leveransfiler ...")
        xlsx_path, csv_path = write_outputs(
            src, outcome.result, outcome.summary, input_path, output_dir, run_ts, _log)
    else:
        xlsx_path = csv_path = ""
    return RunResult(xlsx_path, csv_path, outcome.result, outcome.summary,
                     outcome.stats, outcome.warnings, lines)


if __name__ == "__main__":  # pragma: no cover
    import argparse

    def _cli_lock_horizon(value: str) -> float:
        try:
            return validate_lock_horizon_hours(value)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(str(exc)) from exc

    ap = argparse.ArgumentParser(description=f"AI Omplanering v{VERSION} - CLI (Excel)")
    ap.add_argument("input", help="Sökväg till AI omplanering.xlsx")
    ap.add_argument("-o", "--output", default=None, help="Utkatalog")
    ap.add_argument("--lock-horizon-hours", type=_cli_lock_horizon,
                    default=LOCK_HORIZON_HOURS,
                    help="Låshorisont i timmar (förval: 4; decimalpunkt/-komma tillåts)")
    args = ap.parse_args()
    res = run_replanning(args.input, args.output, log=lambda m: print(m, flush=True),
                         lock_horizon_hours=args.lock_horizon_hours)
    print()
    print("Excel:", res.xlsx_path)
    print("CSV  :", res.csv_path)