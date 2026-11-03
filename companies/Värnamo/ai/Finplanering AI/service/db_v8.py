"""SQL Server authentication and connection helpers for the V8 desktop app."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator, Optional

import config_v8 as config


def _odbc_value(value: str) -> str:
    return "{" + str(value).replace("}", "}}") + "}"


def connection_string(password: str, database: Optional[str] = None) -> str:
    if not config.SERVER_NAME or not config.DATABASE or not config.USERNAME:
        raise ValueError(
            f"Fyll i server_name, database och username i "
            f"{config.CONNECTION_CONFIG_PATH}.")
    if not password:
        raise ValueError("Ange SQL-lösenordet.")
    return (
        f"Driver={_odbc_value(config.ODBC_DRIVER)};"
        f"Server={_odbc_value(config.SERVER_NAME)};"
        f"Database={_odbc_value(database or config.DATABASE)};"
        f"UID={_odbc_value(config.USERNAME)};"
        f"PWD={_odbc_value(password)};"
        f"Encrypt={config.ENCRYPT};"
        f"TrustServerCertificate={config.TRUST_SERVER_CERTIFICATE};"
        f"Connection Timeout={config.CONNECTION_TIMEOUT};"
    )


def connect(password: str, database: Optional[str] = None):
    try:
        import pyodbc
    except ImportError as exc:
        raise RuntimeError(
            "SQL-läget kräver pyodbc och Microsoft ODBC Driver 18 for SQL Server."
        ) from exc
    conn = pyodbc.connect(connection_string(password, database), autocommit=False)
    conn.timeout = config.QUERY_TIMEOUT
    return conn


@contextmanager
def open_connection(password: str) -> Iterator:
    conn = connect(password)
    try:
        yield conn
    finally:
        conn.close()


def server_identity(conn) -> tuple[str, str]:
    row = conn.cursor().execute(
        "SELECT CONVERT(nvarchar(128), SERVERPROPERTY('ServerName')), DB_NAME()"
    ).fetchone()
    return str(row[0]), str(row[1])
