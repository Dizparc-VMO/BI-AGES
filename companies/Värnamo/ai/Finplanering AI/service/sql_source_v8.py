# -*- coding: utf-8 -*-
"""
Laeser planeringsunderlaget fraan SQL Server och bygger samma
``omplanering_core_v8.SourceData`` som Excel-vaegen producerar, inklusive
``dbo.CustomerConfig``.

Skillnader mot Excel-kaellan som maaste hanteras haer:

  * Datumen aer aekta ``datetime`` - inga Excel-serienummer.
  * ``komtid`` / ``gicktid`` aer ``time(7)`` och kommer som ``datetime.time``.
  * ``arbtimperdag`` aer ``numeric`` och kommer som ``Decimal`` - maaste
    castas till float, annars slaar aritmetiken i kalendermotorn fel.
  * ``Prio1``-``Prio8`` aer ``nvarchar(5)``, inte float.
  * Tabellnamnet aer ``tblSTGetAoColorCodeList`` med ``t`` pa slutet, till
    skillnad fraan Excel-flikens avkortade ``...CodeLis``.
"""

from __future__ import annotations

import os
import sys
from typing import Callable, List

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config_v8 as config                       # noqa: E402
import omplanering_core_v8 as core               # noqa: E402


LogFn = Callable[[str], None]


def _noop(_msg: str) -> None:
    pass


# Kolumner som motorn kraever. Saknas naagon avbryts koerningen med besked.
REQUIRED = {
    "baseline": ["AoNr", "AoPos", "OpNr", "ProdGr", "OpStatus", "ArtNr",
                 "AoStartDatTid", "AoSlutDatTid", "TiSlutDat", "OrderNr",
                 "OrdBerLevDat", "ColorCode", "ColorName", "OpkoPrioritet"],
    "operations": ["AoNr", "AoPos", "OpNr", "ProdGr", "ArtNr", "OpStatus",
                   "TiSlutDat", "aostartdattid", "aoslutdattid", "stalltid",
                   "stycktid", "kalendernr"],
    "calendar": ["dDate", "kalendernr", "Date_komtid", "Date_gicktid",
                 "arbtimperdag"],
    "prio": ["ArtNr", "OpNr", "Prio1"],
    "customer_config": ["OrderNumber", "Customer", "Vikt", "MaxLate"],
}

NUMERIC_COLS = {
    "baseline": ["AoNr", "AoPos", "OpNr", "OpStatus", "OrderNr",
                 "OpkoPrioritet", "PlanInlev", "PlanBehov", "DayDiff"],
    "operations": ["AoNr", "AoPos", "OpNr", "OpStatus", "OpkoPrioritet",
                   "stalltid", "stycktid", "kotid", "kalendernr",
                   "stalltid_org", "stycktid_org", "prodgrtillgproc",
                   "Foretagkod"],
    "calendar": ["kalendernr", "arbtimperdag", "arbtimperdag_firstdaymode"],
    "prio": ["OpNr"],
    "customer_config": ["Vikt", "MaxLate"],
}

DATE_COLS = {
    "baseline": ["AoStartDatTid", "AoSlutDatTid", "TiSlutDat", "OrdBerLevDat",
                 "AO_Start_DateTime", "AO_Finish_DateTime", "LogCreatDateTime"],
    "operations": ["TiSlutDat", "aostartdattid", "aoslutdattid"],
    "calendar": ["Date_komtid", "Date_gicktid", "LogDateTime"],
    "prio": [],
    "customer_config": [],
}


def _read(conn, table: str, where: str = "") -> pd.DataFrame:
    sql = f"SELECT * FROM {table}"
    if where:
        sql += f" WHERE {where}"
    cur = conn.cursor()
    cur.execute(sql)
    cols = [d[0] for d in cur.description]
    rows = cur.fetchall()
    return pd.DataFrame.from_records(
        [tuple(r) for r in rows], columns=cols) if rows else pd.DataFrame(columns=cols)


def _coerce(df: pd.DataFrame, kind: str) -> pd.DataFrame:
    """Castar Decimal -> float och datum -> datetime64.

    pyodbc ger ``numeric`` som ``decimal.Decimal``, vilket pandas lagrar som
    object. Kalendermotorn raeknar i float, och Decimal blandat med float
    kastar TypeError - saa detta maaste goeras foere allt annat.
    """
    for col in NUMERIC_COLS.get(kind, []):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    for col in DATE_COLS.get(kind, []):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")
    return df


def load_source_sql(conn, log: LogFn = _noop) -> core.SourceData:
    """Läser källtabellerna och valfri CustomerConfig till SourceData."""
    warnings: List[str] = []

    log(f"Läser planeringsunderlag från {config.SERVER_NAME}/{config.DATABASE}")

    where = ""
    if config.ONLY_LATEST_BATCH:
        where = (f"LogCreatDateTime = (SELECT MAX(LogCreatDateTime) "
                 f"FROM {config.TBL_BASELINE})")

    baseline = _coerce(_read(conn, config.TBL_BASELINE, where), "baseline")
    operations = _coerce(_read(conn, config.TBL_OPERATIONS), "operations")
    calendar = _coerce(_read(conn, config.TBL_CALENDAR), "calendar")
    prio = _coerce(_read(conn, config.TBL_PRIO), "prio")
    try:
        customer_config = _coerce(
            _read(conn, config.TBL_CUSTOMER_CONFIG), "customer_config")
    except Exception as exc:  # noqa: BLE001
        customer_config = pd.DataFrame(columns=REQUIRED["customer_config"])
        warnings.append(
            f"Kunde inte läsa {config.TBL_CUSTOMER_CONFIG}; standardvikt och "
            f"generell maxförsening används: {exc}")

    for name, df, kind in (
        (config.TBL_BASELINE, baseline, "baseline"),
        (config.TBL_OPERATIONS, operations, "operations"),
        (config.TBL_CALENDAR, calendar, "calendar"),
        (config.TBL_PRIO, prio, "prio"),
        (config.TBL_CUSTOMER_CONFIG, customer_config, "customer_config"),
    ):
        lack = [c for c in REQUIRED[kind] if c not in df.columns]
        if lack:
            raise ValueError(
                f"Tabellen {name} saknar kolumnerna: {', '.join(lack)}")
        log(f"  {name}: {len(df)} rader")

    if len(baseline) < config.MIN_BASELINE_ROWS:
        raise ValueError(
            f"{config.TBL_BASELINE} innehåller bara {len(baseline)} rader "
            f"(minst {config.MIN_BASELINE_ROWS} krävs). Körningen avbryts så "
            f"att ett halvfärdigt uttag inte skriver över ett giltigt resultat."
        )

    # --- Batchhantering ---------------------------------------------------
    #
    # Kaelltabellen kan se ut pa tre satt, och alla tre maaste ge raett svar:
    #
    #   a) Laddas om vid varje uttag  -> ett LogCreatDateTime, inga dubletter
    #   b) Appendar hela batchar      -> maanga LogCreatDateTime, dubletter
    #                                    per AoNr; bara senaste faar anvaendas
    #   c) Tidsstaempel per rad inom  -> maanga LogCreatDateTime, men INGA
    #      samma laddning               dubletter; allt ska anvaendas
    #
    # Ett filter pa MAX(LogCreatDateTime) aer raett i (b) men katastrofalt i
    # (c) - da behaalls bara den sist inskrivna raden. Sjaelva avdubbleringen
    # goers daerfoer pa nyckeln, i core.dedupe_baseline(), sa att bade Excel-
    # och SQL-vaegen skyddas lika. Haer loggas bara diagnostiken.
    if "LogCreatDateTime" in baseline.columns:
        batches = int(baseline["LogCreatDateTime"].dropna().nunique())
        dupes = int(baseline.duplicated(subset=core.BASELINE_KEY).sum())
        if batches == 1:
            log(f"  Uttagets LogCreatDateTime: "
                f"{baseline['LogCreatDateTime'].dropna().iloc[0]}")
        else:
            log(f"  {batches} olika LogCreatDateTime, {dupes} dubblerade "
                f"operationer.")
            if not dupes:
                log("  Inga dubbletter – tidsstämplarna kommer från samma "
                    "laddning. Alla rader används.")

    dup_ops = operations.duplicated(subset=["AoNr", "AoPos", "OpNr"]).sum()
    if dup_ops:
        warnings.append(
            f"{config.TBL_OPERATIONS} har {int(dup_ops)} dubblerade rader på "
            f"(AoNr, AoPos, OpNr). Tabellen saknar LogCreatDateTime, så det "
            f"går inte att avgöra vilken som är aktuell – den först "
            f"förekommande används. Kontrollera att tabellen laddas om i "
            f"stället för att appenda."
        )
        log("VARNING: " + warnings[-1])

    # --- Normalisering, samma som Excel-vaegen -----------------------------
    calendar = calendar.copy()
    calendar["_date"] = pd.to_datetime(calendar["dDate"], errors="coerce")
    bad = int(calendar["_date"].isna().sum())
    if bad:
        warnings.append(f"{bad} kalenderrader har otolkbart dDate och ignoreras.")
        calendar = calendar[calendar["_date"].notna()]

    # Date_komtid/Date_gicktid ska finnas i SQL-tabellen. Saknas de byggs de
    # ur dDate + komtid/gicktid (time(7)).
    need = calendar["Date_komtid"].isna() | calendar["Date_gicktid"].isna()
    if need.any() and {"komtid", "gicktid"} <= set(calendar.columns):
        def _combine(row, col):
            t = row.get(col)
            if t is None or (isinstance(t, float) and pd.isna(t)):
                return pd.NaT
            try:
                return row["_date"] + pd.Timedelta(
                    hours=int(t.hour), minutes=int(t.minute),
                    seconds=int(getattr(t, "second", 0)))
            except AttributeError:
                return pd.NaT
        calendar.loc[need, "Date_komtid"] = calendar[need].apply(
            lambda r: _combine(r, "komtid"), axis=1)
        calendar.loc[need, "Date_gicktid"] = calendar[need].apply(
            lambda r: _combine(r, "gicktid"), axis=1)
        warnings.append(
            f"{int(need.sum())} kalenderrader saknade Date_komtid/Date_gicktid "
            f"och byggdes ur dDate + komtid/gicktid.")

    operations = operations.copy()
    operations["_prodgr"] = operations["ProdGr"].map(core.normalize_prodgr)

    prio = prio.copy()
    prio["_artnr"] = prio["ArtNr"].astype(str).str.strip()

    return core.SourceData(baseline, operations, calendar, prio, warnings,
                           customer_config)
