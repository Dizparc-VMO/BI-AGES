# -*- coding: utf-8 -*-
"""
AI Omplanering - beraekningsmotor (v3)
======================================

Implementerar "AI Omplanering - Instruktion (v4)" i sin helhet:

  * Frysningsregler (OpStatus != 0, redan paaboerjad Op10, saknat OrdBerLevDat, OpNr != 10)
  * EDD-sekvensering per produktionsgrupp
  * Balanserad artikel-klustring: raeckviddsfoenster + skadeproevning, sa att
    staelltidsvinsten aldrig koeps med naagon annan orders leveransdag
  * Tregradig status ur leveransmarginalen (Groen / Gul / Roed)
  * Kalenderstyrd kapacitetsberaekning (komtid/gicktid/arbtimperdag)
  * Alternativruttning via Prio1-Prio8
  * Lead-time-propagation till AI_TiSlutDat
  * Prioritetstilldelning 100, 99, 98 ... per ProdGr efter faktisk koerordning
  * AI_Kommentar per rad enligt avsnitt 4
  * Excel- + CSV-leverans med tidsstaemplade filnamn

Modulen aer helt fristaaende fraan UI:t. `run_replanning()` aer enda ingaangspunkten
som behoevs utifraan.

Kodning: filen aer UTF-8. Svenska tecken anvaends i all text som naar anvaendaren
(kommentarer i resultatet, loggar, rubriker) men undviks i identifierare.
"""

from __future__ import annotations

import bisect
import csv
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import pandas as pd

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python < 3.9
    ZoneInfo = None  # type: ignore

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter


# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------

VERSION = "4.0"

TZ_NAME = "Europe/Stockholm"

#: Excel raeknar dagar fraan 1899-12-30 (1900-datumsystemet med skottaarsbuggen).
EXCEL_EPOCH = pd.Timestamp("1899-12-30")

SHEET_BASELINE = "tblSTGetAoColorCodeLis"
SHEET_OPERATIONS = "tblSTAllOperationsForAoNr"
SHEET_CALENDAR = "tblSTGetDateCalenderWorkingTime"
SHEET_PRIO = "tblSTProductionGroupPrioOnItem"
SHEET_RESULT = "tblAIAnglysisGetAoColorCodeList"
SHEET_SUMMARY = "AI_Sammanfattning"

SOURCE_SHEETS = [SHEET_BASELINE, SHEET_OPERATIONS, SHEET_CALENDAR, SHEET_PRIO]

#: Faergkoder haemtade ur kaelldatat sa att AI-utfallet anvaender samma palett som Jeeves.
COLOR_CODES = {
    "Grön": "#00ff00",
    "Röd": "#FF4500",
    "Gul": "#ffff66",
    "Blå": "#66b3ff",
    "Ljusblå": "#add8e6",
}

#: Faerger som far foerekomma i baslinjen. Ovriga (och null) tolkas som Groen (2.4).
KNOWN_COLORS = {"Grön", "Röd", "Gul", "Blå"}

#: Statusgraens i hela dygn (2.4). Leveransmarginalen aer
#: ``OrdBerLevDat - AI_TiSlutDat``; marginal **stoerre aen** detta vaerde ger
#: Groen, **exakt** detta vaerde ger Gul, och allt daerunder ger Roed.
#: Med foervalet 1: >= 2 dygns marginal = Groen, 1 dygn = Gul, 0 eller
#: foersenat = Roed.
GREEN_MARGIN_DAYS = 1

#: Mallens kolumnordning i tblAIAnglysisGetAoColorCodeList (avsnitt 5, Del 1).
TEMPLATE_COLUMNS = [
    "AoNr",
    "AoPos",
    "OpNr",
    "ProdGr",
    "ArtNr",
    "AI_ProdGr",
    "Orginal_AoStartDatTid",
    "Orginal_AoSlutDatTid",
    "Orginal_TiSlutDat",
    "Orginal_ColorCode",
    "Orginal_ColorName",
    "Orginal_OpkoPrioritet",
    "AI_AoStartDatTid",
    "AI_AoSlutDatTid",
    "AI_TiSlutDat",
    "AI_ColorCode",
    "AI_ColorName",
    "AI_OpkoPrioritet",
    "AI_LogCreatDateTime",
    "AI_Kommentar",
]

#: Avsnitt 5 listar OrdBerLevDat bland originalvaerdena men mallen saknar kolumnen.
#: Vi laegger den sist sa att mallens ordning bevaras exakt och underlaget aendaa
#: gaar att verifiera (Groen/Roed haerleds ur just denna kolumn).
EXTRA_COLUMNS = ["Orginal_OrdBerLevDat"]

DATE_COLUMNS = [
    "Orginal_AoStartDatTid",
    "Orginal_AoSlutDatTid",
    "Orginal_TiSlutDat",
    "Orginal_OrdBerLevDat",
    "AI_AoStartDatTid",
    "AI_AoSlutDatTid",
    "AI_TiSlutDat",
    "AI_LogCreatDateTime",
]

EXCEL_DATE_FORMAT = "yyyy-mm-dd hh:mm"
CSV_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

#: Tolerans i sekunder vid jaemfoerelse av intervallgraenser.
EPS_SECONDS = 30

#: Skyddsraecke mot oaendliga loopar i alternativruttningen.
MAX_ROUTING_PASSES = 4

# --- Klustringspolicy (N2 + N3) --------------------------------------------
#
# Artikel-klustring sparar staelltid genom att koera order med samma ArtNr i
# obruten foeljd. Priset aer att en order som dras framaat knuffar alla order
# den hoppar oever bakaat med hela sin **stycktid**. I det haer datat aer den
# vinsten ~3 h i snitt medan ett Op10-jobb aer ~83 h laangt - klustring aer
# alltsaa bara loensam naer de oeverhoppade ordrarna har marginal kvar.
#
# Tvaa spaerrar haaller bytet i balans:

#: N2 - raeckviddsgraens. En order far bara dras framaat om dess leveransdatum
#: ligger inom sa haer maanga dygn fraan den order som annars skulle koerts nu.
#: Hindrar att en januariorder slaas ihop med ett septemberkluster.
CLUSTER_WINDOW_DAYS = 30

# --- Foerseningens enhet ----------------------------------------------------
#
# Foerseningen (sammanfattningens foerseningsnyckeltal och tjaenstens
# ForseningDygn-kolumner) kan raeknas i kalenderdygn eller i arbetsdagar
# enligt skiftkalendern. I arbetsdagar raeknas bara dagar som finns i
# kalendern med arbtimperdag > 0 - helger och roeda dagar raeknas inte.
#
# Paaverkar INTE statusfaergen eller marginalen (2.4), och inte klustringens
# skadeproevning - de raeknar fortsatt i kalenderdygn.

#: False = kalenderdygn (skrivbordsappens foerval). Tjaensten saetter True.
DELAY_IN_WORKDAYS = False

#: Nyckel foer den gemensamma foeretagskalendern i WorkCalendar-indexet.
COMPANY_CALENDAR = "foretag"

#: Vilka dagar som raeknas som arbetsdagar.
#:   "foretag" = en gemensam kalender foer ALLA order, oavsett vilket
#:               kalendernr ordern koer pa (foerval). En dag aer arbetsdag om
#:               den aer maandag-fredag OCH arbetsdag i en klar majoritet av
#:               kalendrarna som taecker dagen. Helger raeknas aldrig; roeda
#:               dagar och julstaengning faller bort eftersom de saknas i de
#:               flesta kalendrar. Ingen enskild kalenders avvikelse avgoer.
#:   7         = ett bestaemt kalendernr foer alla order
#:   "egen"    = orderns egen Op10-kalender (kal 2/6 raeknar soendag)
DELAY_CALENDAR: object = COMPANY_CALENDAR

#: N3 - vad som raeknas som skada. Marginal under detta vaerde kostar.
#:   0 = bara faktisk foersening (foerval; "roeda blir inte mer roeda")
#:   1 = skydda aeven Gul-bandet
#:   2 = skydda hela Groen-marginalen
PROTECT_MARGIN_DAYS = 0

#: N3 - skadebudget. Tillaatna **tillkommande foerseningsdygn** (summerat oever
#: alla beroerda order pa maskinen) per **sparad staelltidstimme**.
#:   0.00 = klustra aldrig pa bekostnad av ett leveransdatum (foerval)
#:   0.25 = 4 h sparad staelltid faar kosta 1 foerseningsdygn
#:   stort taal = i praktiken alltid klustra (gamla beteendet)
TARDINESS_BUDGET_PER_SETUP_HOUR = 0.0


LogFn = Callable[[str], None]


def _noop(_msg: str) -> None:
    pass


# ---------------------------------------------------------------------------
# Hjaelpfunktioner
# ---------------------------------------------------------------------------

def now_stockholm() -> datetime:
    """Aktuell tidpunkt i Europe/Stockholm som naiv datetime.

    Jeeves/SQL Server lagrar aostartdattid naivt i lokal svensk tid. Vi
    lokaliserar 'nu' till Europe/Stockholm (hanterar CET/CEST) och tar
    sedan bort tidszonen sa att jaemfoerelsen blir aepplen mot aepplen.
    """
    if ZoneInfo is not None:
        return datetime.now(ZoneInfo(TZ_NAME)).replace(tzinfo=None)
    return datetime.now()  # pragma: no cover - fallback foer gamla Python


def excel_serial_to_datetime(value) -> Optional[pd.Timestamp]:
    """Konverterar ett Excel-serienummer till Timestamp. Tomt/0 -> None."""
    if value is None:
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        # Redan datetime?
        ts = pd.to_datetime(value, errors="coerce")
        return None if pd.isna(ts) else ts
    if pd.isna(num) or num == 0:
        return None
    return EXCEL_EPOCH + pd.to_timedelta(num, unit="D")


def normalize_prodgr(value) -> Optional[str]:
    """'10122.0' / 10122.0 / ' 10122 ' -> '10122'. Tomt -> None."""
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


def normalize_color(name) -> str:
    """Okaenda/tomma faerger raeknas som Groen vid statusberaekning (2.4)."""
    if name is None or (isinstance(name, float) and pd.isna(name)):
        return "Grön"
    text = str(name).strip()
    if text == "" or text.lower() in {"nan", "none", "null"}:
        return "Grön"
    return text if text in KNOWN_COLORS else "Grön"


def fmt_dt(value, with_time: bool = True) -> str:
    """Formaterar datum foer AI_Kommentar."""
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
    """Leveransmarginal i hela dygn: ``due - finish``. None om naagot saknas."""
    if due is None or finish is None:
        return None
    d, f = pd.Timestamp(due), pd.Timestamp(finish)
    if pd.isna(d) or pd.isna(f):
        return None
    return (d.normalize().date() - f.normalize().date()).days


def status_from_margin(margin: Optional[float], fallback: str = "Grön") -> str:
    """Marginal i dygn -> statusfaerg enligt 2.4 (se ``GREEN_MARGIN_DAYS``).

    Saknad marginal (None **eller** NaN) ger ``fallback``. NaN maaste fangas
    explicit: alla jaemfoerelser mot NaN aer falska, sa den skulle annars falla
    igenom till Roed och tysta klassa order utan OrdBerLevDat som foersenade.
    """
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


# ---------------------------------------------------------------------------
# Kalender
# ---------------------------------------------------------------------------

@dataclass
class WorkWindow:
    start: datetime
    end: datetime

    @property
    def hours(self) -> float:
        return (self.end - self.start).total_seconds() / 3600.0


class WorkCalendar:
    """Skiftkalender per kalendernr.

    Ett arbetsfoenster per kalenderdag byggs som::

        start = Date_komtid
        end   = min(Date_gicktid, start + kapacitet)

    daer kapaciteten aer ``arbtimperdag`` - utom foer innevarande dygn daer
    ``arbtimperdag_firstdaymode`` (aaterstaaende timmar idag) anvaends och
    foenstret dessutom kortas till att boerja tidigast 'nu'.

    Dagar som saknas i kalendern aer icke-arbetstid (helger, roeda dagar).
    Inget arbete planeras utanfoer komtid-gicktid, vilket innebaer att ett
    dygn med gicktid 23:59 ger 23h59m aeven om arbtimperdag aer 24 - skarven
    23:59-00:00 raeknas som stillestaand.
    """

    def __init__(self, cal_df: pd.DataFrame, now: datetime, log: LogFn = _noop):
        self.now = now
        self.windows: Dict[int, List[WorkWindow]] = {}
        self.window_starts: Dict[int, List[datetime]] = {}
        self.window_ends: Dict[int, List[datetime]] = {}
        self.coverage: Dict[int, Tuple[datetime, datetime]] = {}
        self.mean_daily_hours: Dict[int, float] = {}
        self.warnings: List[str] = []

        # Arbetsdagsindex foer foerseningsraekning i arbetsdagar. Bygger pa
        # hela dagens arbtimperdag - inte pa dagens aaterstaaende kapacitet,
        # eftersom en dag med 0 h kvar idag aendaa aer en arbetsdag.
        self.work_days: Dict[int, List[int]] = {}        # sorterade ordinaler
        self.work_weekdays: Dict[int, set] = {}          # 0 = maandag
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
                    f"operationer på denna kalender kan inte kalendervalideras."
                )
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

    # -- arbetsdagar --------------------------------------------------------

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

            # Veckomoenstret haerleds ur kalendern sjaelv: en veckodag raeknas
            # som arbetsdag om den aer det minst haelften av gaangerna inom
            # taeckningen. Roeda dagar (enstaka luckor) paaverkar inte moenstret.
            present = set(ords)
            hits, total = [0] * 7, [0] * 7
            for n in range(lo, hi + 1):
                wd = (n - 1) % 7              # ordinal 1 = maandag 0001-01-01
                total[wd] += 1
                hits[wd] += n in present
            self.work_weekdays[kal] = {wd for wd in range(7)
                                       if total[wd] and hits[wd] / total[wd] >= 0.5}

        self._build_company_calendar()

    def _build_company_calendar(self) -> None:
        """Gemensam foeretagskalender, oberoende av orderns kalendernr.

        En dag aer arbetsdag om den aer maandag-fredag OCH arbetsdag i en klar
        majoritet (> haelften) av de kalendrar vars taeckning inkluderar dagen.
        Helger raeknas aldrig. Roeda dagar och julstaengning faller bort
        eftersom de saknas i de flesta kalendrar, medan en enskild kalender
        som koer en helgdag (t.ex. kal 6 pa laangfredag) inte raecker foer att
        goera den till arbetsdag.
        """
        if not self.work_days:
            return
        sets = {k: set(v) for k, v in self.work_days.items()}
        lo = min(a for a, _ in self.day_coverage.values())
        hi = max(b for _, b in self.day_coverage.values())

        company: List[int] = []
        for n in range(lo, hi + 1):
            if (n - 1) % 7 >= 5:                    # loerdag/soendag
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
        """Antal ordinaler i [a, b] vars veckodag ingaar i ``weekdays``."""
        if b < a or not weekdays:
            return 0
        full, rest = divmod(b - a + 1, 7)
        start_wd = (a - 1) % 7
        return full * len(weekdays) + sum(
            1 for i in range(rest) if (start_wd + i) % 7 in weekdays)

    @staticmethod
    def _key(kal):
        """Kalendernr som int, eller foeretagskalenderns nyckel oroerd."""
        return kal if kal == COMPANY_CALENDAR else int(kal)

    def has_workdays(self, kal) -> bool:
        return self._key(kal) in self.work_days

    def working_days_after(self, kal, due, finish) -> Tuple[int, bool]:
        """Antal arbetsdagar ``d`` med ``due < d <= finish``.

        Andra vaerdet anger om naagon del av perioden laag utanfoer kalenderns
        taeckning. Den delen raeknas efter kalenderns veckomoenster; roeda
        dagar utanfoer taeckningen gaar inte att kaenna till och raeknas
        daerfoer som arbetsdagar om veckodagen aer det.
        """
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

    # -- publika metoder --------------------------------------------------

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
        """Placerar ``hours`` arbetstimmar tidigast vid ``earliest``.

        Returnerar (start, slut, flaggor). Start aer foersta oeppna
        kalenderminut >= earliest; slutet ackumuleras oever skift och
        stillestaandsdygn.
        """
        flags: List[str] = []
        kal = int(kal)
        hours = max(0.0, float(hours))

        if kal not in self.windows:
            # Ingen kalenderdata -> raekna kontinuerligt och flagga.
            flags.append(f"Ingen kalenderdata för kalendernr {kal}")
            start = earliest
            return start, start + timedelta(hours=hours), flags

        wins = self.windows[kal]
        ends = self.window_ends[kal]

        idx = bisect.bisect_right(ends, earliest)
        if idx >= len(wins):
            flags.append(
                f"Utanför kalendertäckning (kal {kal} slutar "
                f"{self.coverage[kal][1]:%Y-%m-%d})"
            )
            start = max(earliest, self.coverage[kal][1])
            return start, start + timedelta(hours=hours), flags

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

        # Kalendern tog slut mitt i jobbet: extrapolera med kalenderns
        # genomsnittliga dygnskapacitet och flagga tydligt.
        per_day = self.mean_daily_hours.get(kal) or 8.0
        extra_days = remaining / per_day
        end = wins[-1].end + timedelta(days=extra_days)
        flags.append(
            f"Slutdatum extrapolerat – kalendern för kal {kal} täcker bara t.o.m. "
            f"{self.coverage[kal][1]:%Y-%m-%d}"
        )
        return start, end, flags

    def project(self, kal: int, start: datetime,
                durations: Sequence[float]) -> List[datetime]:
        """Kedjeplacerar ``durations`` fraan ``start`` och returnerar sluttiderna.

        Anvaends av klustringens skadeproevning (N3) foer att uppskatta hur en
        taenkt koerordning slaar mot leveransdatumen. Ett enda svep oever
        kalenderfoenstren ger alla sluttider, till skillnad fraan upprepade
        ``schedule()``-anrop.

        Approximationen aer medveten: framtida **laasta block** raeknas inte in.
        Prognosen aer bara ett beslutsunderlag - den faktiska placeringen i
        ``schedule_machine()`` respekterar alltid de laasta blocken exakt.
        """
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
                # Kalendern slut - extrapolera med kalenderns snittdygn.
                cursor = cursor + timedelta(days=remaining / per_day)
            out.append(cursor)

        return out


# ---------------------------------------------------------------------------
# Datamodell
# ---------------------------------------------------------------------------

@dataclass
class Job:
    """En rad i resultatet - en operation ur baslinjen."""

    idx: int                       # radindex i baslinjen
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

    # Klassificering
    movable: bool = False
    frozen_reason: str = ""
    already_started: bool = False

    # Resultat
    prodgr_ai: Optional[str] = None
    ai_start: Optional[datetime] = None
    ai_end: Optional[datetime] = None
    ai_tislutdat: Optional[datetime] = None
    ai_color_name: Optional[str] = None
    ai_color_code: Optional[str] = None
    ai_prio: Optional[int] = None

    setup_saved: float = 0.0
    cluster_ref: Optional["Job"] = None
    #: Jobbet drogs framaat foerbi EDD-vinnaren foer att slippa staelltid (N3),
    #: och den uppskattade kostnaden i tillkommande foerseningsdygn.
    pulled_forward: bool = False
    cluster_cost_days: float = 0.0
    rerouted_from: Optional[str] = None
    predecessor: Optional["Job"] = None
    successor: Optional["Job"] = None
    flags: List[str] = field(default_factory=list)
    comment: str = ""

    # -- haerledda vaerden -------------------------------------------------

    @property
    def duration_full(self) -> float:
        return self.stalltid + self.stycktid

    @property
    def duration_effective(self) -> float:
        return self.duration_full - self.setup_saved

    @property
    def baseline_status(self) -> str:
        """Jeeves egen faerg ur ``ColorName`` (okaenda/tomma -> Groen, 2.4)."""
        return normalize_color(self.orig_color_name)

    @property
    def baseline_status_rule(self) -> str:
        """Utgaangslaeget bedoemt med **samma** regel som AI-statusen.

        Utan detta blir foere/efter-jaemfoerelsen missvisande: Jeeves egen
        faergsaettning anvaender en annan graens aen ``GREEN_MARGIN_DAYS``, sa
        en order skulle kunna visas som "Groen -> Roed" enbart foer att
        regeln bytts - inte foer att schemat blivit saemre.
        """
        if self.ord_ber_lev_dat is None or self.orig_tislutdat is None:
            return self.baseline_status
        return self.status_for(self.orig_tislutdat)

    def margin_days(self, tislutdat: Optional[datetime]) -> Optional[int]:
        """Leveransmarginal i hela dygn: OrdBerLevDat - klartid.

        Positivt = klart i foervaeg, 0 = exakt pa leveransdagen,
        negativt = foersenat.
        """
        return margin_days_between(self.ord_ber_lev_dat, tislutdat)

    def lateness_days(self, tislutdat: Optional[datetime]) -> float:
        """Antal foerseningsdygn (0 om i tid). Sammanfattningens maatt."""
        margin = self.margin_days(tislutdat)
        return 0.0 if margin is None else float(max(0, -margin))

    def damage_days(self, tislutdat: Optional[datetime]) -> float:
        """Skadematt foer N3: hur maanga dygn ordern saknar upp till den
        skyddade marginalen ``PROTECT_MARGIN_DAYS``."""
        margin = self.margin_days(tislutdat)
        return 0.0 if margin is None else float(
            max(0, PROTECT_MARGIN_DAYS - margin))

    def status_for(self, tislutdat: Optional[datetime]) -> str:
        """Statusfaerg ur leveransmarginalen (2.4).

        Marginalen aer skillnaden i hela dygn mellan ``OrdBerLevDat`` och
        orderns klartid ``AI_TiSlutDat``::

            > GREEN_MARGIN_DAYS   ->  Groen
            = GREEN_MARGIN_DAYS   ->  Gul
            < GREEN_MARGIN_DAYS   ->  Roed

        Med foervalet 1 innebaer det att en order maaste bli klar minst tvaa
        dygn foere leveransdagen foer att raeknas som Groen; exakt ett dygns
        marginal ger Gul; allt daerunder - inklusive att bli klar precis pa
        leveransdagen - ger Roed.
        """
        return status_from_margin(self.margin_days(tislutdat),
                                  fallback=self.baseline_status)

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
    """Kapacitetskurva foer en produktionsgrupp."""

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


# ---------------------------------------------------------------------------
# Inlaesning och validering
# ---------------------------------------------------------------------------

@dataclass
class SourceData:
    baseline: pd.DataFrame
    operations: pd.DataFrame
    calendar: pd.DataFrame
    prio: pd.DataFrame
    warnings: List[str] = field(default_factory=list)


def load_source(path: str, log: LogFn = _noop) -> SourceData:
    """Laeser arbetsboken och gor grundlaeggande strukturvalidering."""
    log(f"Läser arbetsbok: {os.path.basename(path)}")
    xl = pd.ExcelFile(path)
    present = set(xl.sheet_names)

    missing = [s for s in SOURCE_SHEETS if s not in present]
    if missing:
        raise ValueError(
            "Arbetsboken saknar obligatoriska flikar: " + ", ".join(missing) +
            ".\nHittade flikar: " + ", ".join(xl.sheet_names)
        )

    warnings: List[str] = []
    baseline = xl.parse(SHEET_BASELINE)
    operations = xl.parse(SHEET_OPERATIONS)
    calendar = xl.parse(SHEET_CALENDAR)
    prio = xl.parse(SHEET_PRIO)

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
            raise ValueError(
                f"Fliken '{name}' saknar kolumnerna: {', '.join(lack)}"
            )

    log(f"  {SHEET_BASELINE}: {len(baseline)} rader")
    log(f"  {SHEET_OPERATIONS}: {len(operations)} rader")
    log(f"  {SHEET_CALENDAR}: {len(calendar)} rader")
    log(f"  {SHEET_PRIO}: {len(prio)} rader")

    # --- normalisering -------------------------------------------------
    calendar = calendar.copy()
    calendar["_date"] = pd.to_datetime(calendar["dDate"], errors="coerce")
    bad_dates = int(calendar["_date"].isna().sum())
    if bad_dates:
        warnings.append(f"{bad_dates} kalenderrader har otolkbart dDate och ignoreras.")
        calendar = calendar[calendar["_date"].notna()]
    for col in ("Date_komtid", "Date_gicktid"):
        calendar[col] = pd.to_datetime(calendar[col], errors="coerce")
    # Om Date_komtid/Date_gicktid saknas: bygg dem ur komtid/gicktid-straengarna.
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

    return SourceData(baseline, operations, calendar, prio, warnings)


#: Nyckeln som identifierar en operation entydigt i baslinjen.
BASELINE_KEY = ["AoNr", "AoPos", "OpNr"]


def dedupe_baseline(baseline: pd.DataFrame, warnings: List[str],
                    log: LogFn = _noop) -> pd.DataFrame:
    """En rad per operation i baslinjen (steg 1).

    Samma ``(AoNr, AoPos, OpNr)`` kan foerekomma flera gaanger naer en
    tillverkningsorder taecker flera kundorder - raderna baer da olika
    ``OrderNr`` och ofta olika ``OrdBerLevDat``.

    Tvaa saker maaste haallas isaer:

    * **Kapaciteten** ska bokas *en* gaang. Skulle operationen schemalaeggas
      flera gaanger blaases maskinens belaeggning upp med tid som inte finns,
      och alla efterfoeljande order pa maskinen ser mer foersenade ut aen de aer.
    * **Statusen** ska bedoemas mot den *mest kraevande* kunden. Daerfoer
      behaalls raden med **tidigast** ``OrdBerLevDat``; haallar operationen det
      datumet haaller den aeven de senare.

    Urvalet aer helt deterministiskt (stabil sortering med ursprunglig
    radordning som sista nyckel), sa att Excel- och SQL-vaegen alltid vaeljer
    samma rad.
    """
    if not set(BASELINE_KEY) <= set(baseline.columns):
        return baseline

    dupes = int(baseline.duplicated(subset=BASELINE_KEY).sum())
    if not dupes:
        return baseline

    before = len(baseline)
    work = baseline.copy()
    work["_ord"] = range(len(work))

    # Tidigast leveransdatum vinner; tomma sist. mergesort aer stabil, sa
    # ``_ord`` avgoer entydigt vid lika vaerden.
    sort_by = (["OrdBerLevDat", "_ord"] if "OrdBerLevDat" in work.columns
               else ["_ord"])
    work = work.sort_values(sort_by, na_position="last", kind="mergesort")
    work = work.drop_duplicates(subset=BASELINE_KEY, keep="first")
    result = (work.sort_values("_ord", kind="mergesort")
                  .drop(columns=["_ord"])
                  .reset_index(drop=True))

    # Skilj pa ofarliga kopior och motstridiga rader - det senare aer en
    # affaersuppgift, inte ett laddningsfel, och maaste synas.
    conflicting = 0
    differing: Dict[str, int] = {}
    watch = [c for c in ("OrderNr", "OrdBerLevDat", "ColorName", "ProdGr",
                         "OpStatus") if c in baseline.columns]
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
               log: LogFn = _noop) -> Tuple[List[Job], List[str]]:
    """Bygger en Job per baslinjerad och klassificerar den (steg 1-2)."""
    warnings = list(src.warnings)
    # Avdubbleringen gaeller vilka jobb som schemalaeggs - inte kaellflikens
    # innehall. ``src.baseline`` maaste passera oroerd till write_outputs(),
    # eftersom leveransen kraever kaellflikarna oefoeraendrade (avsnitt 5).
    baseline_rows = dedupe_baseline(src.baseline, warnings, log)

    ops = src.operations
    ops_key = ops.set_index(["AoNr", "AoPos", "OpNr"])
    ops_key = ops_key[~ops_key.index.duplicated(keep="first")]

    # ProdGr -> kalendernr aer 1:1 i Jeeves-datat; anvaends vid alternativruttning.
    prodgr_cal = (ops.dropna(subset=["_prodgr"])
                     .groupby("_prodgr")["kalendernr"].agg(
                         lambda s: int(s.mode().iloc[0])).to_dict())

    # Fallback-varaktigheter (avsnitt 7).
    op10 = ops[ops["OpNr"] == 10].copy()
    op10["_dur"] = op10["stalltid"].fillna(0) + op10["stycktid"].fillna(0)
    nonzero = op10[op10["_dur"] > 0]
    med_by_prodgr = nonzero.groupby("_prodgr")["_dur"].median().to_dict()
    med_by_kal = nonzero.groupby("kalendernr")["_dur"].median().to_dict()
    med_global = float(nonzero["_dur"].median()) if len(nonzero) else 8.0

    jobs: List[Job] = []
    missing_ops = 0
    fallback_dur = 0

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

        # Datum: operationsfliken aer auktoritativ (aekta datetime),
        # baslinjen anvaends som fallback (Excel-serienummer).
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

        stalltid = float(op["stalltid"]) if op is not None and not pd.isna(
            op.get("stalltid")) else 0.0
        stycktid = float(op["stycktid"]) if op is not None and not pd.isna(
            op.get("stycktid")) else 0.0

        flags: List[str] = []
        if op_nr == 10 and stalltid + stycktid <= 0:
            fb = med_by_prodgr.get(prodgr)
            src_txt = "median per ProdGr"
            if fb is None or pd.isna(fb):
                fb = med_by_kal.get(kalendernr)
                src_txt = "median per kalendernr"
            if fb is None or pd.isna(fb):
                fb = med_global
                src_txt = "global median"
            stycktid = float(fb)
            fallback_dur += 1
            flags.append(f"Saknad operationstid – fallback {fmt_hours(stycktid)} ({src_txt})")

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
        )

        # --- Steg 1: filtrera & frys ------------------------------------
        job.already_started = (orig_start is not None and orig_start <= now)

        if op is None:
            job.movable = False
            job.frozen_reason = "saknar operationsdata"
        elif op_nr != 10:
            job.movable = False
            job.frozen_reason = f"Op{op_nr} – endast Op10 får omplaneras"
        elif job.already_started:
            job.movable = False
            job.frozen_reason = "redan påbörjad"
        elif op_status != 0:
            job.movable = False
            job.frozen_reason = f"OpStatus {op_status}"
        elif due is None:
            job.movable = False
            job.frozen_reason = "saknar OrdBerLevDat"
        else:
            job.movable = True

        if not cal.has(kalendernr) and job.movable:
            job.flags.append(f"Kalendernr {kalendernr} saknar kalenderdata")

        jobs.append(job)

    if missing_ops:
        warnings.append(
            f"{missing_ops} baslinjerader saknar matchande rad i "
            f"{SHEET_OPERATIONS} och kan inte omplaneras."
        )
    if fallback_dur:
        warnings.append(
            f"{fallback_dur} Op10-rader saknade operationstid "
            f"(stalltid+stycktid=0) och fick fallback-varaktighet."
        )

    n_move = sum(1 for j in jobs if j.movable)
    n_started = sum(1 for j in jobs if j.already_started)
    log(f"Klassificering: {n_move} omplaneringsbara, {len(jobs) - n_move} frysta "
        f"(varav {n_started} redan påbörjade).")
    return jobs, warnings


# ---------------------------------------------------------------------------
# Schemalaeggning
# ---------------------------------------------------------------------------

FAR_FUTURE = datetime(2999, 12, 31)


@dataclass
class ClusterPolicy:
    """Avvaegningen mellan sparad staelltid och leveransprecision (N2 + N3)."""

    window_days: int = CLUSTER_WINDOW_DAYS
    budget_days_per_hour: float = TARDINESS_BUDGET_PER_SETUP_HOUR

    def describe(self) -> str:
        if self.budget_days_per_hour <= 0:
            budget = "0 (ingen order far bli senare för ställtidens skull)"
        else:
            per_day = 1.0 / self.budget_days_per_hour
            budget = (f"{self.budget_days_per_hour:g} dygn per sparad timme "
                      f"(≈ {per_day:.1f} h ställtid motiverar 1 förseningsdygn)")
        return f"klusterfönster {self.window_days} dygn; skadebudget {budget}"


def edd_order(jobs: Sequence[Job]) -> List[Job]:
    """Ren EDD-sortering (steg 4). Tidigast OrdBerLevDat vinner."""
    return sorted(jobs, key=lambda j: (j.ord_ber_lev_dat or FAR_FUTURE, j.ao_nr))


def _projected_durations(seq: Sequence[Job], prev_article: Optional[str]) -> List[float]:
    """Varaktighet per jobb i en taenkt koerordning; staelltid noll vid
    obruten artikelfoeljd."""
    out: List[float] = []
    last = prev_article
    for j in seq:
        out.append(j.stycktid if (last is not None and j.art_nr == last)
                   else j.duration_full)
        last = j.art_nr
    return out


def _projected_tardiness(cal: WorkCalendar, kal: int, cursor: datetime,
                         seq: Sequence[Job], prev_article: Optional[str]) -> float:
    """Summa skadedygn oever ``seq`` om den koers i den ordningen.

    Skadan maets pa orderns klartid (Op10-slut + downstream-delta) mot
    OrdBerLevDat, pa datumnivaa, med ``PROTECT_MARGIN_DAYS`` som skyddsnivaa.
    """
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
    """Vaeljer naesta jobb: EDD-vinnaren eller en klustringskandidat.

    Klustring kraever att jobbet har **samma ArtNr som det nyss koerda** - da
    aer maskinen redan omstaelld och staelltiden faller bort. Att dra fram ett
    saadant jobb foerbi EDD-vinnaren kostar dock alla oeverhoppade order hela
    dess stycktid, sa kandidaten maaste passera tvaa spaerrar:

      N2  leveransdatumet far ligga hoegst ``window_days`` efter EDD-vinnarens
      N3  tillkommande foerseningsdygn oever **alla** kvarvarande order maaste
          rymmas i budgeten ``budget_days_per_hour`` x sparad staelltid

    Returnerar (valt jobb, uppskattad kostnad i foerseningsdygn eller None).
    """
    head = remaining[0]
    if prev_article is None or head.art_nr == prev_article:
        # EDD-vinnaren aer redan gratis - inget att vaega.
        return head, None

    head_due = head.ord_ber_lev_dat or FAR_FUTURE
    limit = head_due + timedelta(days=policy.window_days)

    candidates = [
        j for j in remaining[1:]
        if j.art_nr == prev_article
        and j.stalltid > 0                       # utan besparing finns inget att vinna
        and (j.ord_ber_lev_dat or FAR_FUTURE) <= limit   # N2
    ]
    if not candidates:
        return head, None

    base = _projected_tardiness(cal, kal, cursor, remaining, prev_article)
    for cand in candidates:
        alt = [cand] + [j for j in remaining if j is not cand]
        added = _projected_tardiness(cal, kal, cursor, alt, prev_article) - base
        if added <= policy.budget_days_per_hour * cand.stalltid + 1e-9:   # N3
            return cand, max(0.0, added)

    return head, None


@dataclass
class Placement:
    """Var ett jobb hamnar, och om staelltiden foll bort."""

    start: datetime
    end: datetime
    flags: List[str]
    setup_saved: float
    cluster_ref: Optional[Job]


def _place(machine: Machine, cal: WorkCalendar, cursor: datetime, job: Job,
           committed: Sequence[Interval]) -> Placement:
    """Placerar ett jobb tidigast vid ``cursor`` utan att aendra naagot.

    Hoppar oever laasta block (2.2) och nollar staelltiden om operationen
    precis foere pa maskinen - fryst eller ej - koer samma artikel (2.3).
    """
    duration = job.duration_full
    start = end = None
    flags: List[str] = []

    for _ in range(200):
        start, end, flags = cal.schedule(machine.kalendernr, cursor, duration)
        if start is None or end is None:
            break
        clash = machine.conflict(start, end)
        if clash is None:
            break
        cursor = clash.end
    if start is None or end is None:  # pragma: no cover - defensivt
        start, end = cursor, cursor + timedelta(hours=duration)

    # Vem koer precis foere pa maskinen?
    pred_iv = None
    for iv in committed:
        if iv.end <= start + timedelta(seconds=EPS_SECONDS):
            if pred_iv is None or iv.end > pred_iv.end:
                pred_iv = iv

    setup_saved = 0.0
    cluster_ref: Optional[Job] = None
    if pred_iv is not None and pred_iv.job.art_nr == job.art_nr and job.stalltid > 0:
        setup_saved = job.stalltid
        cluster_ref = pred_iv.job
        start, end, flags = cal.schedule(
            machine.kalendernr, start, job.duration_full - setup_saved)

    return Placement(start, end, flags, setup_saved, cluster_ref)


def schedule_machine(machine: Machine, cal: WorkCalendar, now: datetime,
                     policy: Optional[ClusterPolicy] = None) -> None:
    """Kapacitetsberaekning foer en maskin (steg 4-6).

    Frysta block ligger fast; de omplaneringsbara jobben placeras ett i taget
    i EDD-ordning. Vid varje steg proevas om ett jobb med samma ArtNr som det
    nyss koerda kan dras framaat utan att kosta naagon annan sin leveransdag -
    se ``_pick_next``. Staelltiden nollas nar foeregaaende operation pa
    maskinen - fryst eller ej - koer samma artikel (2.3).
    """
    policy = policy or ClusterPolicy()

    for j in machine.movable:
        j.setup_saved = 0.0
        j.cluster_ref = None
        j.predecessor = None
        j.successor = None
        j.pulled_forward = False
        j.cluster_cost_days = 0.0
        j.flags = [f for f in j.flags if not f.startswith("KAL:")]

    remaining = edd_order(machine.movable)
    committed: List[Interval] = list(machine.fixed)
    cursor = now
    prev_article: Optional[str] = None

    while remaining:
        job, cost = _pick_next(cal, machine.kalendernr, cursor, remaining,
                               prev_article, policy)
        placement = _place(machine, cal, cursor, job, committed)

        # En framdragning maaste faktiskt ge besparingen. Hamnar ett laast
        # block med annan artikel emellan uteblir den - da har vi foersenat
        # andra order i onoedan, och EDD-vinnaren tas i staellet.
        if cost is not None and placement.setup_saved <= 0:
            job, cost = remaining[0], None
            placement = _place(machine, cal, cursor, job, committed)

        remaining.remove(job)
        job.setup_saved = placement.setup_saved
        job.cluster_ref = placement.cluster_ref
        if cost is not None:
            job.pulled_forward = True
            job.cluster_cost_days = cost

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
    """Lead-time-propagation (steg 8) + statusfaergning (2.4)."""
    if job.movable and job.ai_end is not None:
        job.ai_tislutdat = job.ai_end + job.downstream_delta
    else:
        job.ai_start = job.orig_start
        job.ai_end = job.orig_end
        job.ai_tislutdat = job.orig_tislutdat
        job.prodgr_ai = job.prodgr_org

    job.ai_color_name = job.status_for(job.ai_tislutdat)
    job.ai_color_code = COLOR_CODES.get(job.ai_color_name, COLOR_CODES["Grön"])


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
            # Frysta Op10-rader reserverar sin ursprungliga tid (2.2).
            m.add_fixed(j)
    return machines


def detect_fixed_overlaps(machines: Dict[str, Machine]) -> List[str]:
    """Rapporterar krockar mellan laasta block i kaelldatat (avsnitt 6.1).

    Tvaa frysta Op10 pa samma ProdGr som oeverlappar i tid aer en
    inkonsekvens i underlaget: en maskin kan bara koera en operation i taget.
    Motorn kan inte flytta dem (de aer frysta per definition) och gissar
    daerfoer inte - den rapporterar.
    """
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
                    f"maskinbeläggningen behöver ses över i Jeeves."
                )
    return issues


# ---------------------------------------------------------------------------
# Alternativruttning
# ---------------------------------------------------------------------------

def build_prio_map(prio_df: pd.DataFrame) -> Dict[str, List[str]]:
    """ArtNr -> [Prio1, Prio2, ... Prio8] normaliserade till ProdGr-straengar."""
    cols = [c for c in
            ["Prio1", "Prio2", "Prio3", "Prio4", "Prio5", "Prio6", "Prio7", "Prio8"]
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
    """Steg 7: flytta roeda order till alternativmaskin naer det hjaelper.

    En flytt genomfoers bara om ordern **laemnar Roed** pa maalmaskinen *och*
    ingen order som inte redan var Roed daer blir Roed av flytten.
    Efter varje genomfoerd flytt raeknas baada maskinerna om, sa att den
    frigjorda kapaciteten kommer resterande order pa ursprungsmaskinen
    till godo.
    """
    policy = policy or ClusterPolicy()
    moved = 0

    for _pass in range(MAX_ROUTING_PASSES):
        moved_this_pass = 0
        reds = [j for j in jobs
                if j.movable and j.ai_color_name == "Röd" and j.prodgr_ai]
        reds.sort(key=lambda j: (j.ord_ber_lev_dat or datetime(2999, 12, 31), j.ao_nr))

        for job in reds:
            options = [pg for pg in prio_map.get(job.art_nr, []) if pg != job.prodgr_ai]
            if not options:
                continue

            source = machines[job.prodgr_ai]

            for target_pg in options:
                target = machines.get(target_pg)
                if target is None:
                    target = Machine(target_pg, int(prodgr_cal.get(
                        target_pg, job.kalendernr)))
                    machines[target_pg] = target
                if not cal.has(target.kalendernr):
                    continue

                before_red = _machine_red_set(target)
                snapshot_t = _snapshot(target)
                snapshot_s = _snapshot(source)

                source.movable.remove(job)
                target.movable.append(job)
                schedule_machine(target, cal, now, policy)
                for iv in target.sequence:
                    apply_downstream(iv.job)

                after_red = _machine_red_set(target)
                worsened = after_red - before_red - {job.idx}

                if job.ai_color_name != "Röd" and not worsened:
                    schedule_machine(source, cal, now, policy)
                    for iv in source.sequence:
                        apply_downstream(iv.job)
                    job.rerouted_from = source.prodgr
                    moved += 1
                    moved_this_pass += 1
                    log(f"  Omrutad {job.key}: {source.prodgr} -> {target_pg}")
                    break

                # Aangra
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


# ---------------------------------------------------------------------------
# Prioritet och kommentarer
# ---------------------------------------------------------------------------

def assign_priorities(jobs: Sequence[Job], log: LogFn = _noop) -> None:
    """Steg 9: 100 = koers foerst, unikt per ProdGr, efter faktisk koerordning."""
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
        # Tie-break pa sluttid gor ordningen entydig aeven for nolltidsjobb
        # (t.ex. en order vars hela varaktighet var staelltid som klustrats bort).
        with_time.sort(key=lambda j: (j.ai_start, j.ai_end or far_end, j.ao_nr))
        without.sort(key=lambda j: j.ao_nr)
        prio = 100
        for j in with_time + without:
            j.ai_prio = prio
            prio -= 1

    # Verifiera unikhet (avsnitt 7)
    for pg, group in by_pg.items():
        prios = [j.ai_prio for j in group]
        if len(set(prios)) != len(prios):  # pragma: no cover - defensivt
            log(f"VARNING: prioritetskrock pa ProdGr {pg}")


def build_comments(jobs: Sequence[Job], machines: Dict[str, Machine],
                   cal: Optional["WorkCalendar"] = None) -> None:
    """Avsnitt 4: AI_Kommentar per rad."""
    freed: Dict[str, List[Job]] = {}
    for j in jobs:
        if j.rerouted_from:
            freed.setdefault(j.rerouted_from, []).append(j)

    def delay_txt(job: Job) -> str:
        """Foerseningen i arbetsdagar, naer den raeknas sa (tjaensten).

        Samma tal som i AI_ForseningDygn: arbetsdagar efter OrdBerLevDat
        t.o.m. AI_TiSlutDat, helgdagar exkluderade enligt skiftkalendern.
        """
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
        # Utgaangslaeget bedoems med SAMMA statusregel som AI-vaerdet. Jeeves
        # egen faerg (ColorName) har en annan graens och skulle annars ge
        # "Status aendrad" pa order vars status inte aendrats alls.
        base = job.baseline_status_rule
        ai = job.ai_color_name or base

        if not job.movable:
            # --- Fryst rad ------------------------------------------------
            if job.already_started:
                parts.append(
                    f"Redan påbörjad (start {fmt_dt(job.orig_start)}) – ej omplanerad, "
                    f"ligger fast enligt ursprungligt schema på {job.prodgr_org}."
                )
            elif job.op_nr != 10:
                parts.append(
                    f"Op{job.op_nr} – endast Op10 omplaneras. Ligger fast på "
                    f"{job.prodgr_org} enligt ursprungligt schema."
                )
            elif job.ord_ber_lev_dat is None:
                parts.append(
                    "Saknar OrdBerLevDat – kan ej statusbedömas eller sekvenseras, "
                    f"fryst på {job.prodgr_org} med originalvärden."
                )
            elif job.frozen_reason.startswith("OpStatus"):
                txt = f" ({job.op_status_text})" if job.op_status_text else ""
                parts.append(
                    f"OpStatus {job.op_status}{txt} – ej omplaneringsbar, ligger fast "
                    f"på {job.prodgr_org}."
                )
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
            # --- Omplanerad rad -------------------------------------------
            if ai != base:
                parts.append(f"Status ändrad: {base} -> {ai}.")
            else:
                parts.append(f"Status oförändrad: {ai}.")

            if job.rerouted_from:
                parts.append(
                    f"Omrutad från {job.rerouted_from} → {job.prodgr_ai} "
                    f"(huvudmaskin full; alternativmaskin ger leverans i tid)."
                )

            if job.setup_saved > 0 and job.cluster_ref is not None:
                ref = job.cluster_ref
                frozen_txt = " (redan påbörjad order)" if not ref.movable else ""
                parts.append(
                    f"Ställtid sparad {fmt_hours(job.setup_saved)} "
                    f"(artikel-klustring på {job.art_nr} mot AO#{ref.ao_nr}{frozen_txt})."
                )
                if job.pulled_forward:
                    kostnad = ("utan att någon order tappar en leveransdag"
                               if job.cluster_cost_days <= 0 else
                               f"till en kostnad av {job.cluster_cost_days:g} "
                               f"förseningsdygn totalt")
                    parts.append(
                        f"Framdragen förbi leveransdatumordningen för klustringen – "
                        f"{kostnad}."
                    )

            pred, succ = job.predecessor, job.successor
            if pred is not None:
                frozen_txt = " [fryst/redan påbörjad]" if not pred.movable else ""
                parts.append(
                    f"Körs efter AO#{pred.ao_nr}/Order:{fmt_order(pred.order_nr)}"
                    f"{frozen_txt} på {job.prodgr_ai} (väntar på avslut "
                    f"{fmt_dt(pred.ai_end)})."
                )
            else:
                parts.append(f"Först i kön på {job.prodgr_ai}.")

            if succ is not None:
                parts.append(
                    f"Påverkar start för AO#{succ.ao_nr}/"
                    f"Order:{fmt_order(succ.order_nr)} (väntar på avslut)."
                )

            margin = job.margin_days(job.ai_tislutdat)
            margin_txt = ("" if margin is None else
                          f" Marginal {margin:+d} dygn → {ai}.")
            parts.append(
                f"Ny Op10: {fmt_dt(job.ai_start)}–{fmt_dt(job.ai_end)} "
                f"({fmt_hours(job.duration_effective)}), "
                f"AI_TiSlutDat {fmt_dt(job.ai_tislutdat)} mot OrdBerLevDat "
                f"{fmt_dt(job.ord_ber_lev_dat, with_time=False)}.{margin_txt}"
                f"{delay_txt(job)}"
            )

        released = freed.get(job.prodgr_ai or "", [])
        if released and job.movable and not job.rerouted_from:
            names = ", ".join(f"AO#{r.ao_nr}" for r in released[:3])
            parts.append(f"Kapacitet frigjord på {job.prodgr_ai} av omrutade: {names}.")

        for f in job.flags:
            parts.append("OBS: " + f.replace("KAL: ", "") + ".")

        job.comment = " ".join(parts)


# ---------------------------------------------------------------------------
# Resultat
# ---------------------------------------------------------------------------

def jobs_to_frame(jobs: Sequence[Job], run_ts: datetime,
                  include_extra: bool = True) -> pd.DataFrame:
    rows = []
    for j in jobs:
        row = {
            "AoNr": j.ao_nr,
            "AoPos": j.ao_pos,
            "OpNr": j.op_nr,
            "ProdGr": j.prodgr_org,
            "ArtNr": j.art_nr,
            "AI_ProdGr": j.prodgr_ai,
            "Orginal_AoStartDatTid": j.orig_start,
            "Orginal_AoSlutDatTid": j.orig_end,
            "Orginal_TiSlutDat": j.orig_tislutdat,
            "Orginal_ColorCode": j.orig_color_code,
            "Orginal_ColorName": j.orig_color_name,
            "Orginal_OpkoPrioritet": j.orig_prio,
            "AI_AoStartDatTid": j.ai_start,
            "AI_AoSlutDatTid": j.ai_end,
            "AI_TiSlutDat": j.ai_tislutdat,
            "AI_ColorCode": j.ai_color_code,
            "AI_ColorName": j.ai_color_name,
            "AI_OpkoPrioritet": j.ai_prio,
            "AI_LogCreatDateTime": run_ts,
            "AI_Kommentar": j.comment,
        }
        if include_extra:
            row["Orginal_OrdBerLevDat"] = j.ord_ber_lev_dat
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
    """Enhetens namn i text och i koerloggen."""
    return "arbetsdagar" if DELAY_IN_WORKDAYS else "dygn"


def _configured_calendar(job: Job):
    """Den kalender ``DELAY_CALENDAR`` pekar ut foer en order."""
    if DELAY_CALENDAR == COMPANY_CALENDAR:
        return COMPANY_CALENDAR
    if DELAY_CALENDAR in (None, "egen"):
        return job.kalendernr
    return int(DELAY_CALENDAR)


def delay_calendar_for(job: Job, cal: Optional["WorkCalendar"]):
    """Kalendern en orders foersening raeknas mot i arbetsdagslaege.

    Den konfigurerade i foersta hand; saknas den i underlaget faller vi
    tillbaka pa foeretagskalendern, som alltid finns om naagon kalender finns.
    Samma kalender anvaends foer original och AI, sa att foere/efter alltid
    maets med samma maattstock - aeven om ordern omrutats.
    """
    if cal is None:
        return None
    for kal in (_configured_calendar(job), COMPANY_CALENDAR):
        if kal is not None and cal.has_workdays(kal):
            return cal._key(kal)
    return None


def delay_basis() -> str:
    """Kort beskrivning av vad arbetsdagarna raeknas mot."""
    if not DELAY_IN_WORKDAYS:
        return "kalenderdygn"
    if DELAY_CALENDAR == COMPANY_CALENDAR:
        return "företagskalender"
    if DELAY_CALENDAR in (None, "egen"):
        return "orderns egen kalender"
    return f"kal {int(DELAY_CALENDAR)}"


def delay_calendar_label(kal) -> str:
    """Hur en enskild orders kalender beskrivs i AI_Kommentar."""
    if kal is None:
        return "saknar kalender"
    if kal == COMPANY_CALENDAR:
        return "företagskalender"
    return f"kal {kal}"


def lateness(job: Job, finish: Optional[datetime],
             cal: Optional["WorkCalendar"] = None) -> Tuple[float, bool]:
    """Foersening foer en klartid, i den enhet ``DELAY_IN_WORKDAYS`` anger.

    Enda definitionen av foersening i loesningen: bade sammanfattningens
    totaler och tjaenstens ForseningDygn-kolumner gaar hit, sa att summan av
    kolumnen alltid staemmer med koerloggens total.

    Andra vaerdet aer True om naagon del raeknades utanfoer kalendern.
    """
    if job.ord_ber_lev_dat is None or finish is None:
        return 0.0, False
    if not DELAY_IN_WORKDAYS or cal is None:
        return job.lateness_days(finish), False

    kal = delay_calendar_for(job, cal)
    due = pd.Timestamp(job.ord_ber_lev_dat).date()
    end = pd.Timestamp(finish).date()
    if kal is None:
        # Ingen anvaendbar kalender alls: kalenderdygn, flaggat.
        return float(max(0, (end - due).days)), True
    n, estimated = cal.working_days_after(kal, due, end)
    return float(n), estimated


def tardiness_stats(jobs: Sequence[Job],
                    cal: Optional["WorkCalendar"] = None) -> Dict[str, object]:
    """Foerseningsnyckeltal foere/efter.

    Antal roeda order raecker inte foer att se om en redan foersenad order
    blivit **mer** foersenad - det syns bara i foerseningens storlek.
    Enheten styrs av ``DELAY_IN_WORKDAYS`` (se ``lateness``).
    """
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
        "worse_count": later,
        "worst_days": round(worst_days, 1),
        "worst_ao": (worst_job.ao_nr if worst_job else None),
        "late_unit": delay_unit(),
        "late_basis": delay_basis(),
        "late_estimated_orders": estimated_orders,
    }


def build_summary(jobs: Sequence[Job], now: datetime, run_ts: datetime,
                  moved: int, cal: WorkCalendar, warnings: Sequence[str],
                  policy: Optional[ClusterPolicy] = None
                  ) -> List[Tuple[str, object]]:
    policy = policy or ClusterPolicy()
    # Foere/efter maaste bedoemas med SAMMA regel, annars visas rena
    # regelbyten som foersaemringar. Jeeves egen faerg redovisas separat.
    jeeves = {"Grön": 0, "Gul": 0, "Röd": 0}
    before = {"Grön": 0, "Gul": 0, "Röd": 0}
    after = {"Grön": 0, "Gul": 0, "Röd": 0}
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
    # Frysningsskaelen redovisas oemsesidigt uteslutande, i samma ordning som
    # build_jobs prioriterar dem, sa att de summerar till antalet frysta rader.
    frozen_notop10 = sum(1 for j in jobs if j.op_nr != 10)
    frozen_started = sum(1 for j in jobs if j.op_nr == 10 and j.already_started)
    frozen_status = sum(1 for j in jobs
                        if not j.movable and not j.already_started
                        and j.op_nr == 10 and j.op_status != 0)
    frozen_nodue = sum(1 for j in jobs
                       if not j.movable and not j.already_started
                       and j.op_nr == 10 and j.op_status == 0
                       and j.ord_ber_lev_dat is None)
    movable = sum(1 for j in jobs if j.movable)
    pulled = sum(1 for j in jobs if j.pulled_forward)
    td = tardiness_stats(jobs, cal)

    rows: List[Tuple[str, object]] = [
        ("AI-Optimering – Sammanfattning", None),
        ("Datum", run_ts.strftime("%Y-%m-%d %H:%M:%S")),
        ("NOW_Stockholm (fryslinje)", now.strftime("%Y-%m-%d %H:%M:%S")),
        ("Motorversion", f"v{VERSION}"),
        (None, None),
        ("URSPRUNGLIG STATUS", "Antal"),
        ("Grön", before.get("Grön", 0)),
        ("Gul", before.get("Gul", 0)),
        ("Röd", before.get("Röd", 0)),
        ("Totalt", len(jobs)),
        ("(bedömd med samma statusgräns som AI – jämförbar)", None),
        (None, None),
        ("JEEVES EGEN FÄRG I UNDERLAGET", "Antal"),
        ("Grön", jeeves.get("Grön", 0)),
        ("Gul", jeeves.get("Gul", 0)),
        ("Röd", jeeves.get("Röd", 0)),
        ("(kolumnen ColorName, oförändrad – annan gräns än AI:s)", None),
        (None, None),
        ("EFTER OPTIMERING", "Antal"),
        ("Grön", after.get("Grön", 0)),
        ("Gul", after.get("Gul", 0)),
        ("Röd", after.get("Röd", 0)),
        ("Totalt", len(jobs)),
        (None, None),
        ("FÖRBÄTTRING", None),
        ("Röda → Grön", transitions.get(("Röd", "Grön"), 0)),
        ("Röda → Gul", transitions.get(("Röd", "Gul"), 0)),
        ("Gula → Grön", transitions.get(("Gul", "Grön"), 0)),
        ("Gröna → Röd (försämring)", transitions.get(("Grön", "Röd"), 0)),
        ("Gula → Röd (försämring)", transitions.get(("Gul", "Röd"), 0)),
        ("Ordrar som fick alternativ maskin", moved),
        (None, None),
        ("Fortfarande röda (ej möjligt att lösa)", after.get("Röd", 0)),
        (None, None),
        (f"FÖRSENING I {td['late_unit'].upper()}", "Före → Efter"),
        (f"Totalt antal förseningsdagar ({td['late_unit']})",
         f"{td['late_days_before']:g} → {td['late_days_after']:g}"),
        ("Varav order som var röda i baslinjen",
         f"{td['late_days_before_red']:g} → {td['late_days_after_red']:g}"),
        ("Antal order som blivit mer försenade", td["worse_count"]),
        (f"Största enskilda försämring ({td['late_unit']})",
         f"{td['worst_days']:g}" + (f"  (AO#{td['worst_ao']})"
                                    if td["worst_ao"] else "")),
    ] + ([
        ("Arbetsdagar räknas mot", td["late_basis"]),
    ] if DELAY_IN_WORKDAYS else []) + [
        (None, None),
        ("STÄLLTIDSOPTIMERING", None),
        ("Antal ställtidsbesparingar (klustring)", len(clustered)),
        ("Totalt sparade ställtidstimmar", round(saved_hours, 2)),
        ("Order framdragna förbi EDD för klustring", pulled),
        ("Klusterfönster (dygn)", policy.window_days),
        ("Skadebudget (förseningsdygn per sparad ställtidstimme)",
         f"{policy.budget_days_per_hour:g}"),
        (None, None),
        ("STATUSGRÄNS", None),
        ("Grön", f"marginal > {GREEN_MARGIN_DAYS} dygn till OrdBerLevDat"),
        ("Gul", f"marginal = {GREEN_MARGIN_DAYS} dygn"),
        ("Röd", f"marginal < {GREEN_MARGIN_DAYS} dygn (inkl. exakt på leveransdagen)"),
        (None, None),
        ("POPULATION OCH FRYSNING", None),
        ("Rader totalt i underlaget", len(jobs)),
        ("Omplanerade (rörliga) Op10-rader", movable),
        ("Frysta: redan påbörjade (aostartdattid ≤ NOW_Stockholm)", frozen_started),
        ("Frysta: OpStatus ≠ 0", frozen_status),
        ("Frysta: saknar OrdBerLevDat", frozen_nodue),
        ("Frysta: ej Op10", frozen_notop10),
        ("Summa frysta", len(jobs) - movable),
        (None, None),
        ("KALENDER", None),
        ("Kalendertäckning", cal.coverage_text()),
    ]

    if warnings:
        rows.append((None, None))
        rows.append(("DATAVALIDERING – ANMÄRKNINGAR", len(warnings)))
        for w in warnings:
            rows.append(("• " + w, None))

    return rows


# ---------------------------------------------------------------------------
# Excel-/CSV-skrivning
# ---------------------------------------------------------------------------

HEADER_FILL = PatternFill("solid", fgColor="1F3864")
HEADER_FONT = Font(color="FFFFFF", bold=True, size=10)
THIN = Side(style="thin", color="BFBFBF")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)

ROW_FILLS = {
    "Grön": PatternFill("solid", fgColor="D8F0D0"),
    "Röd": PatternFill("solid", fgColor="FBD5CB"),
    "Gul": PatternFill("solid", fgColor="FFF4C2"),
    "Blå": PatternFill("solid", fgColor="D6E6FA"),
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
    xlsx_path = os.path.join(output_dir, f"{stem}_resultat_{stamp}.xlsx")
    csv_path = os.path.join(output_dir, f"{stem}_resultat_{stamp}.csv")

    wb = Workbook()
    wb.remove(wb.active)

    # 1-4: kaellflikarna, oefoeraendrat innehall
    src_map = {
        SHEET_BASELINE: src.baseline,
        SHEET_OPERATIONS: src.operations.drop(columns=["_prodgr"], errors="ignore"),
        SHEET_CALENDAR: src.calendar.drop(columns=["_date"], errors="ignore"),
        SHEET_PRIO: src.prio.drop(columns=["_artnr"], errors="ignore"),
    }
    for name, df in src_map.items():
        ws = wb.create_sheet(name)
        dcols = [c for c in df.columns
                 if pd.api.types.is_datetime64_any_dtype(df[c])]
        _write_frame(ws, df, dcols)
        _autosize(ws, 30)
        log(f"  Skrev källflik {name} ({len(df)} rader)")

    # 5: resultatfliken
    ws = wb.create_sheet(SHEET_RESULT)
    _write_frame(ws, result, DATE_COLUMNS, color_col="AI_ColorName")
    _autosize(ws, 70)
    ws.column_dimensions[get_column_letter(
        result.columns.get_loc("AI_Kommentar") + 1)].width = 100
    log(f"  Skrev {SHEET_RESULT} ({len(result)} rader)")

    # 6: sammanfattningen
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

    # CSV foer databasimport
    csv_df = result.copy()
    for c in DATE_COLUMNS:
        if c in csv_df.columns:
            csv_df[c] = pd.to_datetime(csv_df[c], errors="coerce").dt.strftime(CSV_DATE_FORMAT)
    csv_df.to_csv(csv_path, sep=";", index=False, encoding="utf-8-sig",
                  quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
    log(f"CSV skriven: {csv_path}")

    return xlsx_path, csv_path


# ---------------------------------------------------------------------------
# Orkestrering
# ---------------------------------------------------------------------------

@dataclass
class PlanOutcome:
    """Resultatet av sjaelva beraekningen, utan naagon leveransformatering.

    Delas av Excel-vaegen (``run_replanning``) och SQL-tjaensten i ``service/``
    sa att baada koer exakt samma motor.
    """

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
                 log: LogFn = _noop) -> PlanOutcome:
    """Koer hela algoritmen (steg 1-10) pa ett faerdiginlaest ``SourceData``.

    Kaellagnostisk: ``src`` kan komma fraan Excel (``load_source``) eller fraan
    SQL Server (``service/sql_source.py``). Skriver inga filer.
    """
    policy = policy or ClusterPolicy()
    now = now or now_stockholm()
    run_ts = run_ts or datetime.now()

    _log = log

    # Kalender
    _log("Bygger skiftkalender ...")
    cal = WorkCalendar(src.calendar, now, _log)
    _log(f"  Kalendertäckning: {cal.coverage_text()}")

    # 1-2. Klassificera + normalisera
    jobs, warnings = build_jobs(src, cal, now, _log)
    warnings.extend(cal.warnings)

    prodgr_cal = (src.operations.dropna(subset=["_prodgr"])
                  .groupby("_prodgr")["kalendernr"]
                  .agg(lambda s: int(s.mode().iloc[0])).to_dict())

    # 3. Flaskhalsar
    red_by_pg: Dict[str, int] = {}
    for j in jobs:
        if j.baseline_status == "Röd" and j.prodgr_org:
            red_by_pg[j.prodgr_org] = red_by_pg.get(j.prodgr_org, 0) + 1
    top = sorted(red_by_pg.items(), key=lambda kv: -kv[1])[:5]
    if top:
        _log("Flaskhalsar (flest röda): " +
             ", ".join(f"{pg} ({n})" for pg, n in top))

    # 4-6. Sekvensering, klustring, kapacitet
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

    # 7. Alternativruttning
    _log("Provar alternativruttning för kvarvarande röda order ...")
    prio_map = build_prio_map(src.prio)
    moved = alternative_routing(machines, jobs, prio_map, cal, now, prodgr_cal,
                                policy, _log)
    _log(f"  {moved} order flyttade till alternativmaskin.")

    # Slutlig omraekning sa att alla rader speglar sista schemat
    for m in machines.values():
        schedule_machine(m, cal, now, policy)
    for j in jobs:
        apply_downstream(j)

    # 9. Prioritet
    assign_priorities(jobs, _log)

    # 10. Kommentarer
    build_comments(jobs, machines, cal)

    # Foerseningsenhetens datavalidering - maaste in i warnings innan
    # sammanfattningen byggs, eftersom den listar anmaerkningarna sist.
    td = tardiness_stats(jobs, cal)
    if DELAY_IN_WORKDAYS:
        fixed = (DELAY_CALENDAR not in (COMPANY_CALENDAR, None, "egen"))
        if fixed and not cal.has_workdays(DELAY_CALENDAR):
            warnings.append(
                f"Förseningen ska räknas i arbetsdagar mot kalendernr "
                f"{DELAY_CALENDAR}, men den kalendern finns inte i underlaget. "
                f"Företagskalendern har använts i stället.")
            _log("VARNING: " + warnings[-1])
        if not cal.has_workdays(COMPANY_CALENDAR):
            warnings.append(
                "Skiftkalendern innehåller inga arbetsdagar – förseningen har "
                "räknats i kalenderdygn.")
            _log("VARNING: " + warnings[-1])
        if td["late_estimated_orders"]:
            first = min((lo for lo, _ in cal.day_coverage.values()), default=None)
            start = (f" ({datetime.fromordinal(first):%Y-%m-%d})"
                     if first else "")
            warnings.append(
                f"{td['late_estimated_orders']} order har en förseningsperiod som "
                f"går utanför skiftkalendern{start}. Arbetsdagarna där har räknats "
                f"efter kalenderns veckomönster – röda dagar utanför kalendern "
                f"kan inte identifieras och räknas därför som arbetsdagar.")
            _log("VARNING: " + warnings[-1])

    # Resultat
    result = jobs_to_frame(jobs, run_ts)
    summary = build_summary(jobs, now, run_ts, moved, cal, warnings, policy)

    before_red = sum(1 for j in jobs if j.baseline_status_rule == "Röd")
    after_red = sum(1 for j in jobs
                    if (j.ai_color_name or j.baseline_status_rule) == "Röd")
    stats = {
        "rows": len(jobs),
        "movable": sum(1 for j in jobs if j.movable),
        "frozen_started": sum(1 for j in jobs if j.already_started),
        "red_before": before_red,
        "red_after": after_red,
        "red_fixed": before_red - after_red,
        "green_before": sum(1 for j in jobs if j.baseline_status_rule == "Grön"),
        "green_after": sum(1 for j in jobs
                           if (j.ai_color_name or j.baseline_status_rule) == "Grön"),
        "yellow_before": sum(1 for j in jobs if j.baseline_status_rule == "Gul"),
        "yellow_after": sum(1 for j in jobs
                            if (j.ai_color_name or j.baseline_status_rule) == "Gul"),
        "rerouted": moved,
        "pulled_forward": sum(1 for j in jobs if j.pulled_forward),
        "policy": policy,
        "clustered": sum(1 for j in jobs if j.setup_saved > 0),
        "setup_hours_saved": round(sum(j.setup_saved for j in jobs), 2),
        # Endast maskiner som faktiskt har belaeggning i slutschemat - dicten
        # innehaaller aeven alternativmaskiner som provades och rullades tillbaka.
        "machines": sum(1 for m in machines.values() if m.movable or m.fixed),
        "now_stockholm": now,
        "run_ts": run_ts,
    }
    stats.update(td)
    unit = td["late_unit"]
    _log(f"KLART. Röd {before_red} → {after_red} "
         f"({before_red - after_red} lösta), {moved} omrutade, "
         f"{stats['clustered']} klustrade ({stats['setup_hours_saved']} h sparad "
         f"ställtid, varav {stats['pulled_forward']} framdragna förbi EDD).")
    _log(f"       Försening totalt ({unit}): {stats['late_days_before']:g} "
         f"→ {stats['late_days_after']:g}; "
         f"{stats['worse_count']} order blev mer försenade "
         f"(värst {stats['worst_days']:g} {unit}).")

    return PlanOutcome(jobs=jobs, result=result, summary=summary, stats=stats,
                       warnings=warnings, machines=machines, calendar=cal,
                       now=now, run_ts=run_ts)


def run_replanning(input_path: str, output_dir: Optional[str] = None,
                   now: Optional[datetime] = None,
                   policy: Optional[ClusterPolicy] = None,
                   write_files: bool = True,
                   log: Optional[LogFn] = None) -> RunResult:
    """Excel-vaegen: laes arbetsbok -> ``compute_plan`` -> skriv leveransfiler.

    Parameters
    ----------
    input_path  : sökväg till källarbetsboken (.xlsx)
    output_dir  : katalog för resultatfilerna (default: <indata>/output)
    now         : override av NOW_Stockholm (för test/reproducerbarhet)
    policy      : klustringspolicy (N2 + N3); default enligt modulkonstanterna
    write_files : sätt False för att bara räkna, utan att skriva Excel/CSV
    log         : callback som tar en textrad
    """
    policy = policy or ClusterPolicy()
    lines: List[str] = []

    def _log(msg: str) -> None:
        lines.append(msg)
        if log:
            log(msg)

    run_ts = datetime.now()
    now = now or now_stockholm()
    _log(f"=== AI Omplanering v{VERSION} ===")
    _log(f"NOW_Stockholm = {now:%Y-%m-%d %H:%M:%S} ({TZ_NAME})")
    _log(f"Klustringspolicy: {policy.describe()}")
    _log(f"Statusgräns: marginal > {GREEN_MARGIN_DAYS} dygn = Grön, "
         f"= {GREEN_MARGIN_DAYS} dygn = Gul, därunder = Röd")

    if output_dir is None:
        output_dir = os.path.join(os.path.dirname(os.path.abspath(input_path)), "output")

    src = load_source(input_path, _log)
    outcome = compute_plan(src, now=now, policy=policy, run_ts=run_ts, log=_log)

    if write_files:
        _log("Skriver leveransfiler ...")
        xlsx_path, csv_path = write_outputs(
            src, outcome.result, outcome.summary, input_path, output_dir,
            run_ts, _log)
    else:
        xlsx_path = csv_path = ""

    return RunResult(xlsx_path, csv_path, outcome.result, outcome.summary,
                     outcome.stats, outcome.warnings, lines)


if __name__ == "__main__":  # pragma: no cover
    import argparse

    ap = argparse.ArgumentParser(
        description=f"AI Omplanering v{VERSION} - CLI (Excel)")
    ap.add_argument("input", help="Sökväg till AI omplanering.xlsx")
    ap.add_argument("-o", "--output", default=None, help="Utkatalog")
    args = ap.parse_args()

    res = run_replanning(args.input, args.output, log=lambda m: print(m, flush=True))
    print()
    print("Excel:", res.xlsx_path)
    print("CSV  :", res.csv_path)
