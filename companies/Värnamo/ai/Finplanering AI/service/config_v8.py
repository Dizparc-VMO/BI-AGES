"""V8 SQL settings and per-user configuration paths."""

from __future__ import annotations

import json
import os
import re
from typing import Any


APP_DIR = os.path.join(
    os.environ.get("APPDATA") or os.path.expanduser("~"),
    "VarnamoFinplaneringAI", "V8")
CONNECTION_CONFIG_PATH = os.path.join(APP_DIR, "connection.json")
USER_SETTINGS_PATH = os.path.join(APP_DIR, "settings.json")

DEFAULT_CONFIG = {
    "server_name": "tcp:AHO-APP12,1433",
    "database": "BIzparc_Direct_VMO_AI",
    "username": "imad01",
    "odbc_driver": "ODBC Driver 18 for SQL Server",
    "encrypt": "yes",
    "trust_server_certificate": "yes",
    "connection_timeout": 25,
    "query_timeout": 300,
    # 0 = proceduren får köra tills SQL Server svarar (avbryts manuellt i appen).
    "refresh_timeout": 0,
    "refresh_procedure": "dbo.sp_Fill_All_Tables",
    "refresh_parameters": [],
}

_KEYS = frozenset(DEFAULT_CONFIG)
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_QUALIFIED_IDENTIFIER = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*$")
_TABLES = {
    "TBL_BASELINE": "dbo.tblSTGetAoColorCodeList",
    "TBL_OPERATIONS": "dbo.tblSTAllOperationsForAoNr",
    "TBL_CALENDAR": "dbo.tblSTGetDateCalenderWorkingTime",
    "TBL_PRIO": "dbo.tblSTProductionGroupPrioOnItem",
    "TBL_CUSTOMER_CONFIG": "dbo.CustomerConfig",
    "TBL_RESULT": "dbo.tblAIAnglysisGetAoColorCodeList",
    "TBL_RUN": "dbo.tblAIAnglysisRun",
    "SP_PURGE": "dbo.uspAIAnglysisPurge",
}
globals().update(_TABLES)

# SQL-source safety and result retention defaults inherited from V7.
ONLY_LATEST_BATCH = False
MIN_BASELINE_ROWS = 1
RETENTION_RUNS = 30
DEFAULT_MAX_TARDINESS_DAYS = 10.0
TARDINESS_SCORE_BANDS = [
    [-99, 0, 1.0], [1, 2, 2.0], [3, 4, 4.0],
    [5, 7, 9.0], [8, 9, 10.0], [10, None, 20.0],
]
CLUSTER_WINDOW_DAYS = 30
TARDINESS_BUDGET_PER_SETUP_HOUR = 0.0


def _write_default_config() -> None:
    os.makedirs(APP_DIR, exist_ok=True)
    if os.path.exists(CONNECTION_CONFIG_PATH):
        return
    temporary = CONNECTION_CONFIG_PATH + ".tmp"
    with open(temporary, "w", encoding="utf-8") as stream:
        json.dump(DEFAULT_CONFIG, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    os.replace(temporary, CONNECTION_CONFIG_PATH)


def load_connection_config() -> dict[str, Any]:
    """Load/create the non-secret, per-user SQL configuration."""
    _write_default_config()
    try:
        with open(CONNECTION_CONFIG_PATH, encoding="utf-8") as stream:
            values = json.load(stream)
    except (OSError, ValueError) as exc:
        raise RuntimeError(
            f"Kunde inte läsa SQL-konfigurationen {CONNECTION_CONFIG_PATH}: {exc}") from exc
    if not isinstance(values, dict):
        raise ValueError("SQL-konfigurationen måste vara ett JSON-objekt.")
    unknown = sorted(set(values) - _KEYS)
    if unknown:
        raise ValueError("Okända SQL-konfigurationsnycklar: " + ", ".join(unknown))
    config = {**DEFAULT_CONFIG, **values}
    for name, label in (("server_name", "server_name"),
                        ("database", "database"),
                        ("username", "username")):
        if not isinstance(config[name], str):
            raise ValueError(f"{label} måste vara text.")
    procedure = config["refresh_procedure"]
    if not isinstance(procedure, str):
        raise ValueError("refresh_procedure måste vara text.")
    if procedure and not _QUALIFIED_IDENTIFIER.fullmatch(procedure):
        raise ValueError(
            "refresh_procedure ska anges som schema.procedur med giltiga namn.")
    parameters = config["refresh_parameters"]
    if not isinstance(parameters, list):
        raise ValueError("refresh_parameters måste vara en JSON-lista.")
    for parameter in parameters:
        if (not isinstance(parameter, dict)
                or set(parameter) != {"name", "value"}
                or not isinstance(parameter["name"], str)
                or not _IDENTIFIER.fullmatch(parameter["name"])):
            raise ValueError(
                "Varje procedurparameter ska innehålla ett giltigt name och value.")
    for key in ("encrypt", "trust_server_certificate"):
        if str(config[key]).lower() not in {"yes", "no"}:
            raise ValueError(f"{key} måste vara 'yes' eller 'no'.")
    for key in ("connection_timeout", "query_timeout"):
        if not isinstance(config[key], int) or config[key] <= 0:
            raise ValueError(f"{key} ska vara ett positivt heltal.")
    refresh_timeout = config["refresh_timeout"]
    if (isinstance(refresh_timeout, bool) or not isinstance(refresh_timeout, int)
            or refresh_timeout < 0):
        raise ValueError(
            "refresh_timeout ska vara ett heltal ≥ 0 (0 = ingen tidsgräns).")
    if not isinstance(config["odbc_driver"], str) or not config["odbc_driver"].strip():
        raise ValueError("odbc_driver måste vara ett icke-tomt drivrutinsnamn.")
    for key, table in _TABLES.items():
        if not _QUALIFIED_IDENTIFIER.fullmatch(table):
            raise ValueError(f"Ogiltigt SQL-objektnamn i {key}.")
    return config


def reload_config() -> None:
    values = load_connection_config()
    globals().update({
        "SERVER_NAME": values["server_name"],
        "DATABASE": values["database"],
        "USERNAME": values["username"],
        "ODBC_DRIVER": values["odbc_driver"],
        "ENCRYPT": values["encrypt"],
        "TRUST_SERVER_CERTIFICATE": values["trust_server_certificate"],
        "CONNECTION_TIMEOUT": values["connection_timeout"],
        "QUERY_TIMEOUT": values["query_timeout"],
        "REFRESH_TIMEOUT": values["refresh_timeout"],
        "REFRESH_PROCEDURE": values["refresh_procedure"],
        "REFRESH_PARAMETERS": values["refresh_parameters"],
    })


reload_config()
