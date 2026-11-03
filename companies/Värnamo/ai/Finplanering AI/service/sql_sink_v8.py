# -*- coding: utf-8 -*-
"""
Skriver resultatet till SQL Server.

En koerning ger en rad i ``tblAIAnglysisRun`` och en rad per tillverknings-
order i ``tblAIAnglysisGetAoColorCodeList``, laenkade med ``RunId``.

Allt sker i **en transaktion**: antingen finns hela koerningen, eller ingen
del av den. En avbruten koerning laemnar foeregaaende resultat oroert.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import uuid
from datetime import datetime
from typing import Callable, List, Optional, Sequence

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config_v8 as config                       # noqa: E402
import omplanering_core_v8 as core               # noqa: E402


LogFn = Callable[[str], None]


def _noop(_msg: str) -> None:
    pass


#: Kolumnordning i tblAIAnglysisGetAoColorCodeList (utan AnalysisId).
RESULT_COLUMNS = [
    "RunId",
    "AoNr", "AoPos", "OpNr", "ProdGr", "ArtNr", "AI_ProdGr",
    "Orginal_AoStartDatTid", "Orginal_AoSlutDatTid", "Orginal_TiSlutDat",
    "Orginal_ColorCode", "Orginal_ColorName", "Orginal_OpkoPrioritet",
    "Orginal_OrdBerLevDat",
    "AI_AoStartDatTid", "AI_AoSlutDatTid", "AI_TiSlutDat",
    "AI_ColorCode", "AI_ColorName", "AI_OpkoPrioritet",
    "AI_LogCreatDateTime", "AI_Kommentar",
    "Orginal_MarginalDygn", "AI_MarginalDygn",
    "Orginal_ForseningDygn", "AI_ForseningDygn",
    "Orginal_ColorName_AIRegel",
    "AI_Fryst", "AI_FrysOrsak", "AI_Omrutad", "AI_OmrutadFran",
    "AI_StalltidSparadH", "AI_KlustradMotAoNr",
    "AI_Framdragen", "AI_FramdragenKostnadDygn",
    "Orginal_TardinessScore", "AI_TardinessScore", "AI_CapExcessDygn",
    "CustomerOrderNumbers", "CustomerNumbers", "CustomerWeight",
    "MaxTardinessDays", "Orginal_WeightedTardinessScore",
    "AI_WeightedTardinessScore",
]


def _cols(names: Sequence[str]) -> str:
    """Kolumnlista med hakparenteser.

    Obligatoriskt: ``Clustered`` aer ett reserverat ord i T-SQL, och flera
    andra kolumnnamn ligger naera. Hakparenteser goer INSERT-satsen
    okaenslig foer det.
    """
    return ", ".join(f"[{n}]" for n in names)


def _use_fast_executemany() -> bool:
    """``fast_executemany`` kraever ODBC Driver 17+.

    Den gamla drivrutinen "SQL Server" stoedjer inte parameterbindningen
    som flaggan foerutsaetter och kan ge svaartolkade fel.
    """
    return "odbc driver" in config.ODBC_DRIVER.lower()


def _py(value):
    """pandas/numpy -> rena Python-typer som pyodbc accepterar."""
    if value is None:
        return None
    if isinstance(value, float) and value != value:      # NaN
        return None
    if isinstance(value, pd.Timestamp):
        return None if pd.isna(value) else value.to_pydatetime()
    if hasattr(value, "item") and not isinstance(value, (str, bytes, datetime, bool)):
        try:
            return value.item()
        except (ValueError, AttributeError):
            return value
    return value


def jobs_to_rows(jobs: Sequence["core.Job"], run_id: str,
                 run_ts: datetime, cal=None,
                 policy: Optional["core.ClusterPolicy"] = None) -> List[tuple]:
    """Bygger inserterbara rader direkt ur motorns Job-objekt.

    Haerledda kolumner (marginal, foersening, jaemfoerbar baslinjestatus, vad
    motorn gjorde med raden) laeggs till haer i staellet foer i Excel-mallen,
    sa att tabellen gaar att fraaga pa utan att tolka fritexten i
    ``AI_Kommentar``.

    ``ForseningDygn`` raeknas via ``core.lateness`` - samma funktion som
    koerloggens LateDays*, sa att SUM(AI_ForseningDygn) alltid staemmer med
    LateDaysAfter. Med ``DELAY_IN_WORKDAYS`` aer vaerdet arbetsdagar enligt
    skiftkalendern (``cal``); ``MarginalDygn`` aer alltid kalenderdygn.
    """
    rows: List[tuple] = []
    policy = policy or core.ClusterPolicy()
    for j in jobs:
        m_before = j.margin_days(j.orig_tislutdat)
        m_after = j.margin_days(j.ai_tislutdat)
        late_before, _ = core.lateness(j, j.orig_tislutdat, cal)
        late_after, _ = core.lateness(j, j.ai_tislutdat, cal)
        rec = {
            "RunId": run_id,
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
            "Orginal_OrdBerLevDat": j.ord_ber_lev_dat,

            "AI_AoStartDatTid": j.ai_start,
            "AI_AoSlutDatTid": j.ai_end,
            "AI_TiSlutDat": j.ai_tislutdat,
            "AI_ColorCode": j.ai_color_code,
            "AI_ColorName": j.ai_color_name,
            "AI_OpkoPrioritet": j.ai_prio,
            "AI_LogCreatDateTime": run_ts,
            "AI_Kommentar": j.comment,

            "Orginal_MarginalDygn": m_before,
            "AI_MarginalDygn": m_after,
            "Orginal_ForseningDygn": int(late_before),
            "AI_ForseningDygn": int(late_after),
            "Orginal_ColorName_AIRegel": j.baseline_status_rule,

            "AI_Fryst": (not j.movable),
            "AI_FrysOrsak": (j.frozen_reason or None) if not j.movable else None,
            "AI_Omrutad": bool(j.rerouted_from),
            "AI_OmrutadFran": j.rerouted_from,
            "AI_StalltidSparadH": round(j.setup_saved, 4) if j.setup_saved else None,
            "AI_KlustradMotAoNr": (j.cluster_ref.ao_nr if j.cluster_ref else None),
            "AI_Framdragen": bool(j.pulled_forward),
            "AI_FramdragenKostnadDygn": (round(j.cluster_cost_days, 2)
                                         if j.pulled_forward else None),
            "Orginal_TardinessScore": (
                core.tardiness_score(
                    core.score_days_between(j.ord_ber_lev_dat, j.orig_tislutdat),
                    policy.score_bands) if j.ord_ber_lev_dat is not None else None),
            "AI_TardinessScore": (
                core.tardiness_score(
                    core.score_days_between(j.ord_ber_lev_dat, j.ai_tislutdat),
                    policy.score_bands)
                if j.ord_ber_lev_dat is not None and j.ai_tislutdat is not None else None),
            "AI_CapExcessDygn": (
                max(0.0, core.tardiness_days_between(j.ord_ber_lev_dat, j.ai_tislutdat)
                    - j.permitted_tardiness_days())
                if j.ord_ber_lev_dat is not None and j.ai_tislutdat is not None else None),
            "CustomerOrderNumbers": ";".join(j.customer_order_numbers) or None,
            "CustomerNumbers": ";".join(j.customer_numbers) or None,
            "CustomerWeight": j.customer_weight,
            "MaxTardinessDays": j.max_tardiness_days,
            "Orginal_WeightedTardinessScore": (
                round(j.customer_weight * core.tardiness_score(
                    core.score_days_between(j.ord_ber_lev_dat, j.orig_tislutdat),
                    policy.score_bands), 3) if j.ord_ber_lev_dat is not None else None),
            "AI_WeightedTardinessScore": (
                round(j.customer_weight * core.tardiness_score(
                    core.score_days_between(j.ord_ber_lev_dat, j.ai_tislutdat),
                    policy.score_bands), 3)
                if j.ord_ber_lev_dat is not None and j.ai_tislutdat is not None else None),
        }
        rows.append(tuple(_py(rec[c]) for c in RESULT_COLUMNS))
    return rows


def _run_values(run_id: str, outcome: "core.PlanOutcome", started: datetime,
                ended: Optional[datetime], status: str,
                error: Optional[str]) -> dict:
    s = outcome.stats if outcome else {}
    pol = s.get("policy")
    warnings = list(outcome.warnings) if outcome else []
    duration = ((ended - started).total_seconds() if ended else None)

    return {
        "RunId": run_id,
        "RunStart": started,
        "RunEnd": ended,
        "DurationSeconds": (round(duration, 2) if duration is not None else None),
        "Status": status,
        "ErrorMessage": error,
        "EngineVersion": f"v{core.VERSION}",
        "HostName": socket.gethostname()[:128],
        "NowStockholm": s.get("now_stockholm") or started,
        "MaxTardinessDays": (pol.global_max_tardiness_days if pol
                     else config.DEFAULT_MAX_TARDINESS_DAYS),
        "ScoreCutoffs": None,
        "ScoreRates": None,
        "ScoreBandsJson": json.dumps(
            pol.score_bands if pol else config.TARDINESS_SCORE_BANDS),
        "ClusterWindowDays": (pol.window_days if pol else config.CLUSTER_WINDOW_DAYS),
        "TardinessBudget": (pol.budget_days_per_hour if pol
                            else config.TARDINESS_BUDGET_PER_SETUP_HOUR),
        "ProtectMarginDays": core.PROTECT_MARGIN_DAYS,
        "GreenMarginDays": core.GREEN_MARGIN_DAYS,
        "RowsTotal": s.get("rows"),
        "RowsMovable": s.get("movable"),
        "FrozenStarted": s.get("frozen_started"),
        "Machines": s.get("machines"),
        "RedBefore": s.get("red_before"),
        "RedAfter": s.get("red_after"),
        "YellowBefore": s.get("yellow_before"),
        "YellowAfter": s.get("yellow_after"),
        "GreenBefore": s.get("green_before"),
        "GreenAfter": s.get("green_after"),
        "GreenWeightBefore": s.get("green_weight_before"),
        "GreenWeightAfter": s.get("green_weight_after"),
        "TardinessScoreBefore": s.get("tardiness_score_before"),
        "TardinessScoreAfter": s.get("tardiness_score_after"),
        "BaselineOverLimitCount": s.get("baseline_over_limit_count"),
        "AfterOverLimitCount": s.get("after_over_limit_count"),
        "LateDaysBefore": s.get("late_days_before"),
        "LateDaysAfter": s.get("late_days_after"),
        "LateDaysBeforeRed": s.get("late_days_before_red"),
        "LateDaysAfterRed": s.get("late_days_after_red"),
        "WorseCount": s.get("worse_count"),
        "WorstDays": s.get("worst_days"),
        "WorstAoNr": s.get("worst_ao"),
        "Clustered": s.get("clustered"),
        "SetupHoursSaved": s.get("setup_hours_saved"),
        "PulledForward": s.get("pulled_forward"),
        "Rerouted": s.get("rerouted"),
        "WarningCount": len(warnings),
        "Warnings": ("\n".join(warnings) if warnings else None),
        # Enheten foer LateDays*/WorstDays och ForseningDygn-kolumnerna, och
        # vad arbetsdagarna raeknades mot. Ryms i nvarchar(20):
        #   "dygn" | "arbetsdagar/företag" | "arbetsdagar/kal 7" | "arbetsdagar/egen"
        "DelayUnit": _delay_unit_text(),
        # Satt bara naer ett bestaemt kalendernr anvaends.
        "DelayCalendarNr": (int(core.DELAY_CALENDAR)
                            if core.DELAY_IN_WORKDAYS and isinstance(
                                core.DELAY_CALENDAR, int) else None),
    }


def _delay_unit_text() -> str:
    """Enhet + grund i ett faelt (max 20 tecken), t.ex. 'arbetsdagar/företag'."""
    if not core.DELAY_IN_WORKDAYS:
        return "dygn"
    if core.DELAY_CALENDAR == core.COMPANY_CALENDAR:
        return "arbetsdagar/företag"
    if core.DELAY_CALENDAR in (None, "egen"):
        return "arbetsdagar/egen"
    return f"arbetsdagar/kal {int(core.DELAY_CALENDAR)}"[:20]


def _existing_columns(cur, table: str) -> set:
    """Kolumnerna som faktiskt finns i tabellen (gemener)."""
    cur.execute(f"SELECT TOP 0 * FROM {table}")
    return {d[0].lower() for d in cur.description}


def _fit(cols: Sequence[str], existing: set, table: str,
         log: LogFn) -> List[str]:
    """Behaaller bara kolumner som finns i tabellen.

    Nya kolumner laeggs till i koden foere de hunnit skapas i databasen. I
    staellet foer att hela skrivningen kraschar hoppas de oever, och det
    loggas vilka - kolumnerna skapas med ALTER-blocket i 01_create_tables.sql.
    Obligatoriska kolumner saknas aldrig tyst: da failar INSERT som vanligt.
    """
    kept = [c for c in cols if c.lower() in existing]
    missing = [c for c in cols if c.lower() not in existing]
    if missing:
        log(f"OBS: {table} saknar kolumnerna {', '.join(missing)} – de hoppas "
            f"över. Kör sql\\01_create_tables.sql igen för att lägga till dem.")
    return kept


def write_outcome(conn, outcome: "core.PlanOutcome", started: datetime,
                  log: LogFn = _noop) -> str:
    """Skriver koerlogg + resultatrader i en transaktion. Ger RunId."""
    run_id = str(uuid.uuid4())
    rows = jobs_to_rows(outcome.jobs, run_id, outcome.run_ts, outcome.calendar,
                        outcome.stats.get("policy"))
    ended = datetime.now()
    run_vals = _run_values(run_id, outcome, started, ended, "Klar", None)

    cur = conn.cursor()
    try:
        run_cols = _fit(list(run_vals), _existing_columns(cur, config.TBL_RUN),
                        config.TBL_RUN, log)
        res_cols = _fit(RESULT_COLUMNS, _existing_columns(cur, config.TBL_RESULT),
                        config.TBL_RESULT, log)
        pos = [RESULT_COLUMNS.index(c) for c in res_cols]
        rows = [tuple(r[i] for i in pos) for r in rows]

        cur.execute(
            f"INSERT INTO {config.TBL_RUN} ({_cols(run_cols)}) "
            f"VALUES ({', '.join('?' * len(run_cols))})",
            *[_py(run_vals[c]) for c in run_cols],
        )

        if _use_fast_executemany():
            try:
                cur.fast_executemany = True
            except AttributeError:  # pragma: no cover - aeldre pyodbc
                pass
        cur.executemany(
            f"INSERT INTO {config.TBL_RESULT} ({_cols(res_cols)}) "
            f"VALUES ({', '.join('?' * len(res_cols))})",
            rows,
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    log(f"Skrev {len(rows)} rader till {config.TBL_RESULT} (RunId {run_id})")
    return run_id


def write_failure(conn, started: datetime, error: str,
                  log: LogFn = _noop) -> Optional[str]:
    """Loggar en misslyckad koerning i koerloggen. Aldrig fatal i sig."""
    run_id = str(uuid.uuid4())
    vals = _run_values(run_id, None, started, datetime.now(), "Fel", error[:4000])
    try:
        cur = conn.cursor()
        cols = _fit(list(vals), _existing_columns(cur, config.TBL_RUN),
                    config.TBL_RUN, log)
        cur.execute(
            f"INSERT INTO {config.TBL_RUN} ({_cols(cols)}) "
            f"VALUES ({', '.join('?' * len(cols))})",
            *[_py(vals[c]) for c in cols],
        )
        conn.commit()
        log(f"Felet loggat i {config.TBL_RUN} (RunId {run_id})")
        return run_id
    except Exception as exc:                       # noqa: BLE001
        log(f"Kunde inte logga felet i databasen: {exc}")
        return None


def purge(conn, keep: Optional[int] = None, log: LogFn = _noop) -> None:
    keep = config.RETENTION_RUNS if keep is None else keep
    if not keep:
        return
    try:
        conn.cursor().execute(f"EXEC {config.SP_PURGE} @KeepRuns = ?", keep)
        conn.commit()
        log(f"Behåller de {keep} senaste körningarna.")
    except Exception as exc:                       # noqa: BLE001
        log(f"Städningen kunde inte köras: {exc}")
