# -*- coding: utf-8 -*-
"""
Databasanslutning och applaas.

Foeljer husets moenster fraan DBConnection.py: Trusted Connection mot
namngiven server, inga loesenord i kod eller konfiguration.
"""

from __future__ import annotations

import contextlib
from typing import Iterator, Optional

try:
    import pyodbc
except ImportError as _exc:                        # pragma: no cover
    raise SystemExit(
        "pyodbc saknas. Installera drivrutinsbryggan med:\n"
        "    pip install pyodbc\n"
        "Modulen behövs bara för SQL-tjänsten – skrivbordsappen "
        "(omplanering_app.py) fungerar utan den."
    ) from _exc

import config_v7 as config


def connection_string(database: Optional[str] = None) -> str:
    return (
        f"Driver={{{config.ODBC_DRIVER}}};"
        f"Server={config.SERVER_NAME};"
        f"Database={database or config.DATABASE};"
        "Trusted_Connection=yes;"
        "TrustServerCertificate=yes;"
        f"Connection Timeout={config.CONNECTION_TIMEOUT};"
    )


def connect(database: Optional[str] = None, autocommit: bool = False):
    """Oeppnar en anslutning. Anroparen ansvarar foer att staenga den."""
    conn = pyodbc.connect(connection_string(database), autocommit=autocommit)
    conn.timeout = config.QUERY_TIMEOUT
    return conn


@contextlib.contextmanager
def open_connection(autocommit: bool = False) -> Iterator["pyodbc.Connection"]:
    conn = connect(autocommit=autocommit)
    try:
        yield conn
    finally:
        with contextlib.suppress(Exception):
            conn.close()


@contextlib.contextmanager
def app_lock(conn, name: Optional[str] = None,
             timeout_ms: Optional[int] = None) -> Iterator[bool]:
    """Sessionsbundet applaas via ``sp_getapplock``.

    Ger ``True`` om laaset togs. Tvaa instanser av tjaensten kan da aldrig
    skriva resultat samtidigt - den andra faar ``False`` och avslutar utan
    att roera naagot.

    Laaset aer sessionsbundet, sa det slaepps aeven om processen doer.
    """
    name = name or config.APP_LOCK_NAME
    timeout_ms = config.APP_LOCK_TIMEOUT_MS if timeout_ms is None else timeout_ms

    cur = conn.cursor()
    cur.execute(
        "DECLARE @rc int; "
        "EXEC @rc = sp_getapplock @Resource = ?, @LockMode = 'Exclusive', "
        "@LockOwner = 'Session', @LockTimeout = ?; "
        "SELECT @rc;",
        name, timeout_ms,
    )
    rc = cur.fetchone()[0]
    acquired = rc is not None and rc >= 0
    try:
        yield acquired
    finally:
        if acquired:
            with contextlib.suppress(Exception):
                conn.cursor().execute(
                    "EXEC sp_releaseapplock @Resource = ?, @LockOwner = 'Session';",
                    name)


def server_now(conn):
    """Serverns lokala tid. Anvaends bara foer loggning - frysningsregeln
    utgaar alltid fran Europe/Stockholm i motorn (instruktion 2.1)."""
    return conn.cursor().execute("SELECT GETDATE();").fetchone()[0]
