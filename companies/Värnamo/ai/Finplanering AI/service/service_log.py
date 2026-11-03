# -*- coding: utf-8 -*-
"""
Loggning till fil och stdout.

Anvaender husets ``logToFile`` om modulen gaar att importera, sa att
felmeddelanden hamnar i samma loggflode som oevriga integrationer. Annars
skrivs en dygnsroterad fil i ``service/logs``.
"""

from __future__ import annotations

import glob
import os
import sys
import time
from datetime import datetime, timedelta

import config

try:                                   # husets loggmodul, om den finns
    import logToFile                   # type: ignore
    _HOUSE_LOG = True
except ImportError:
    logToFile = None                   # type: ignore
    _HOUSE_LOG = False


_PREFIX = "AI-Omplanering"


def _path() -> str:
    os.makedirs(config.LOG_DIR, exist_ok=True)
    return os.path.join(config.LOG_DIR,
                        f"omplanering_{datetime.now():%Y-%m-%d}.log")


def log(message: str, level: str = "INFO") -> None:
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S}  {level:<5}  {message}"
    try:
        print(line, flush=True)
    except (OSError, UnicodeEncodeError):
        pass                            # ingen konsol (tjaenstelaege)
    try:
        with open(_path(), "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def error(message: str) -> None:
    log(message, "FEL")
    if _HOUSE_LOG:
        try:
            logToFile.logInputErrToFile(f"{_PREFIX} -- {message}")
        except Exception:               # noqa: BLE001 - loggning far aldrig faella
            pass


def warn(message: str) -> None:
    log(message, "VARN")


def prune(days: int | None = None) -> None:
    """Tar bort loggfiler aeldre aen ``LOG_KEEP_DAYS``."""
    days = config.LOG_KEEP_DAYS if days is None else days
    if not days:
        return
    cutoff = time.time() - days * 86400
    for path in glob.glob(os.path.join(config.LOG_DIR, "omplanering_*.log")):
        try:
            if os.path.getmtime(path) < cutoff:
                os.remove(path)
        except OSError:
            pass
