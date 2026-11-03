"""Guarded invocation of the administrator-configured V8 refresh procedure."""

from __future__ import annotations

import re
from typing import Callable

import config_v8 as config

_PROCEDURE = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*$")
_PARAMETER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _log_messages(cursor, log: Callable[[str], None]) -> None:
    messages = cursor.messages or []
    for state, message in messages:
        log(f"SQL-meddelande ({state}): {message}")
    messages.clear()


def describe_refresh_timeout(seconds: int) -> str:
    if not seconds:
        return "ingen tidsgräns – appen väntar tills SQL Server svarar"
    return f"tidsgräns {seconds} sekunder"


def run_refresh_procedure(
        conn, log: Callable[[str], None] = lambda _message: None,
        phase: Callable[[str], None] = lambda _message: None,
        on_cursor: Callable[[object], None] = lambda _cursor: None) -> None:
    """Kör proceduren. ``on_cursor`` får markören (och None när steget är klart)
    så att UI-tråden kan avbryta anropet med ``cursor.cancel()``."""
    procedure = config.REFRESH_PROCEDURE
    if not procedure:
        raise ValueError(
            f"Konfigurera refresh_procedure i {config.CONNECTION_CONFIG_PATH} först.")
    if not _PROCEDURE.fullmatch(procedure):
        raise ValueError("Det konfigurerade procedurnamnet är ogiltigt.")

    parameters = config.REFRESH_PARAMETERS
    bindings = []
    assignments = []
    for parameter in parameters:
        name = parameter["name"]
        if not _PARAMETER.fullmatch(name):
            raise ValueError("En konfigurerad procedurparameter har ogiltigt namn.")
        assignments.append(f"@{name} = ?")
        bindings.append(parameter["value"])

    command = f"EXEC [{procedure.split('.')[0]}].[{procedure.split('.')[1]}]"
    if assignments:
        command += " " + ", ".join(assignments)

    previous_timeout = conn.timeout
    refresh_timeout = config.REFRESH_TIMEOUT
    # pyodbc läser conn.timeout när markören skapas; sätt den därför först.
    conn.timeout = refresh_timeout
    cursor = conn.cursor()
    on_cursor(cursor)
    try:
        phase(f"Kör {procedure} – väntar på svar från SQL Server")
        log(f"Startar {procedure}: {describe_refresh_timeout(refresh_timeout)}.")
        log("SQL-meddelanden (PRINT) visas i loggen när proceduren har svarat, "
            "inte medan den körs.")
        try:
            cursor.execute(command, *bindings)
        finally:
            _log_messages(cursor, log)
        while True:
            try:
                more_results = cursor.nextset()
            finally:
                _log_messages(cursor, log)
            if not more_results:
                break
        conn.timeout = previous_timeout
        phase("Proceduren har returnerat – committar transaktionen")
        conn.commit()
    except Exception:
        conn.timeout = previous_timeout
        phase("SQL-åtgärden misslyckades eller avbröts – väntar på rollback")
        log("Procedursteget avslutades utan commit. Begär rollback; ingen automatisk omkörning.")
        conn.rollback()
        log("Rollback-anropet är klart. Eventuella interna commits/sidoeffekter måste verifieras i SQL.")
        raise
    finally:
        on_cursor(None)
        cursor.close()
    log(f"Källdataproceduren {procedure} kördes och transaktionen committades.")
