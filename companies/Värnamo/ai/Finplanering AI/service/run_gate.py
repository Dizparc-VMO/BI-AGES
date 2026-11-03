# -*- coding: utf-8 -*-
"""
Grind mot ``dbo.sysRunScript`` – handskakningen med laddnings-SP:n.

Floedet
-------

    1. SP:n laddar kaelltabellerna och saetter   Status = 0
       (+ SenastDTSPKor). Nollan betyder "data klar, redo foer scriptet".
    2. Tjaensten pollar var N:e minut. Ser den Status = 0 koer den hela vaegen.
    3. Naer koerningen lyckats saetts                Status = 1
       (+ SenastDTScriptKor). Ettan betyder "scriptet klart, vaentar pa ny data".

Misslyckas koerningen laemnas Status = 0, sa att naesta poll goer om foersoeket.
Varje foersoek loggas i ``tblAIAnglysisRun``.

Kapplöpningsskydd
-----------------
``SenastDTSPKor`` laeses av naer grinden oeppnas och skickas med naer den
staengs. Har SP:n hunnit ladda en **ny** batch under tiden koerningen pagick
matchar vaerdet inte laengre, uppdateringen traeffar noll rader och Status
laemnas pa 0 - sa den nya batchen blir omhaendertagen vid naesta poll i
staellet foer att tappas bort.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Optional

import config


LogFn = Callable[[str], None]


def _noop(_msg: str) -> None:
    pass


#: Vaerdet i Status-kolumnen. Sammanfaller med kommentaren i DDL:t.
STATUS_SP_KLAR = 0        # data laddad, redo foer scriptet
STATUS_SCRIPT_KLAR = 1    # scriptet klart, vaentar pa ny data


@dataclass
class GateState:
    exists: bool
    status: Optional[int]
    senast_sp: Optional[datetime]
    senast_script: Optional[datetime]
    rows: int = 0

    @property
    def ready(self) -> bool:
        return self.status == STATUS_SP_KLAR


def read(conn, log: LogFn = _noop) -> GateState:
    """Laeser styrraden. Vid flera rader anvaends den med senaste SP-koerning."""
    cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*) FROM {config.TBL_RUN_GATE}")
    rows = int(cur.fetchone()[0])

    if rows == 0:
        return GateState(False, None, None, None, 0)

    if rows > 1:
        log(f"VARNING: {config.TBL_RUN_GATE} har {rows} rader – "
            f"använder den med senaste SenastDTSPKor. Tabellen bör innehålla "
            f"exakt en rad.")

    cur.execute(
        f"SELECT TOP (1) Status, SenastDTSPKor, SenastDTScriptKor "
        f"FROM {config.TBL_RUN_GATE} "
        f"ORDER BY SenastDTSPKor DESC"
    )
    row = cur.fetchone()
    status = None if row[0] is None else int(row[0])
    return GateState(True, status, row[1], row[2], rows)


def ensure_row(conn, log: LogFn = _noop) -> None:
    """Saatter en tom styrtabell i viloläge (Status = 1).

    Viloläget aer det saekra utgaangslaeget: tjaensten koer inte foerraen
    SP:n uttryckligen har signalerat att data aer laddad.
    """
    state = read(conn, log)
    if state.exists:
        return
    conn.cursor().execute(
        f"INSERT INTO {config.TBL_RUN_GATE} "
        f"(Status, SenastDTSPKor, SenastDTScriptKor) VALUES (?, NULL, NULL)",
        STATUS_SCRIPT_KLAR,
    )
    conn.commit()
    log(f"{config.TBL_RUN_GATE} var tom – lade in en styrrad i viloläge "
        f"(Status = {STATUS_SCRIPT_KLAR}). Tjänsten kör när SP:n sätter "
        f"Status = {STATUS_SP_KLAR}.")


def should_run(conn, log: LogFn = _noop) -> tuple[bool, GateState, str]:
    """Avgoer om en koerning ska startas. Ger (koer, tillstaand, motivering)."""
    state = read(conn, log)

    if not state.exists:
        ensure_row(conn, log)
        return False, state, "styrtabellen var tom"

    if state.status is None:
        return False, state, (
            f"Status är NULL i {config.TBL_RUN_GATE} – kör inte förrän SP:n "
            f"satt {STATUS_SP_KLAR}")

    if state.ready:
        stamp = (f" (SP klar {state.senast_sp:%Y-%m-%d %H:%M:%S})"
                 if state.senast_sp else "")
        return True, state, f"Status = {STATUS_SP_KLAR} – ny data att köra på{stamp}"

    stamp = (f", senaste körning {state.senast_script:%Y-%m-%d %H:%M:%S}"
             if state.senast_script else "")
    return False, state, (f"Status = {state.status} – väntar på att SP:n "
                          f"laddar ny data{stamp}")


def mark_script_done(conn, state: GateState, log: LogFn = _noop) -> bool:
    """Saetter Status = 1 foer den batch koerningen faktiskt arbetade pa.

    Ger ``False`` om SP:n hunnit ladda en nyare batch under tiden - da
    laemnas Status pa 0 sa att naesta poll tar hand om den.
    """
    cur = conn.cursor()
    if state.senast_sp is None:
        cur.execute(
            f"UPDATE {config.TBL_RUN_GATE} "
            f"SET Status = ?, SenastDTScriptKor = GETDATE() "
            f"WHERE SenastDTSPKor IS NULL",
            STATUS_SCRIPT_KLAR,
        )
    else:
        cur.execute(
            f"UPDATE {config.TBL_RUN_GATE} "
            f"SET Status = ?, SenastDTScriptKor = GETDATE() "
            f"WHERE SenastDTSPKor = ?",
            STATUS_SCRIPT_KLAR, state.senast_sp,
        )
    affected = cur.rowcount
    conn.commit()

    if affected:
        log(f"{config.TBL_RUN_GATE}: Status satt till {STATUS_SCRIPT_KLAR} "
            f"(scriptet klart).")
        return True

    log(f"VARNING: {config.TBL_RUN_GATE} uppdaterades inte – SP:n verkar ha "
        f"laddat en nyare batch under körningen. Status lämnas på "
        f"{STATUS_SP_KLAR} så att nästa poll kör om.")
    return False
