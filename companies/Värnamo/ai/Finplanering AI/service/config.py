# -*- coding: utf-8 -*-
"""
Instaellningar foer AI Omplanering som tjaenst.

Vaerdena nedan aer foervalen. De kan oeverstyras utan kodaendring av en
``config.json`` bredvid denna fil, t.ex.::

    {
      "SERVER_NAME": "AHO-APP12",
      "SCHEDULE_TIMES": ["05:30", "11:30", "17:30"],
      "CLUSTER_WINDOW_DAYS": 30,
      "TARDINESS_BUDGET_PER_SETUP_HOUR": 0
    }

Alla naycklar aer valfria - det som saknas behaaller foervalet.
"""

from __future__ import annotations

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))

# --- Databas ---------------------------------------------------------------
SERVER_NAME = "AHO-APP12"
DATABASE = "BIzparc_Direct_VMO_AI"
ODBC_DRIVER = "SQL Server"          # byt till "ODBC Driver 17 for SQL Server"
                                    # om den finns installerad - snabbare och
                                    # hanterar fast_executemany baettre
CONNECTION_TIMEOUT = 25
QUERY_TIMEOUT = 300

# --- Kaelltabeller ---------------------------------------------------------
TBL_BASELINE = "dbo.tblSTGetAoColorCodeList"
TBL_OPERATIONS = "dbo.tblSTAllOperationsForAoNr"
TBL_CALENDAR = "dbo.tblSTGetDateCalenderWorkingTime"
TBL_PRIO = "dbo.tblSTProductionGroupPrioOnItem"

# --- Styrtabell: handskakning med laddnings-SP:n ---------------------------
#: Tjaensten koer bara naer SP:n signalerat att kaelldatat aer laddat.
#:   Status = 0  SP:n klar - redo foer scriptet
#:   Status = 1  scriptet klart - vaentar pa ny data
TBL_RUN_GATE = "dbo.sysRunScript"

#: Saett False foer att koera oavsett vad styrtabellen saeger (t.ex. vid
#: manuell omkoerning). Kommandoradsflaggan --force goer samma sak per koerning.
USE_RUN_GATE = True

#: Hur ofta grinden pollas i --watch-laege (minuter).
POLL_INTERVAL_MINUTES = 5

# --- Resultattabeller ------------------------------------------------------
TBL_RESULT = "dbo.tblAIAnglysisGetAoColorCodeList"
TBL_RUN = "dbo.tblAIAnglysisRun"
SP_PURGE = "dbo.uspAIAnglysisPurge"

#: Antal koerningar som sparas. 0 = spara allt.
RETENTION_RUNS = 30

#: Om kaelltabellerna appendar i stallet foer att skrivas oever: saett till
#: True foer att bara laesa den senaste batchen (hoegsta LogCreatDateTime).
#: Foervalet False laeser allt, vilket aer raett naer tabellerna laddas om vid
#: varje uttag. Tjaensten varnar sjaelv om den ser flera batchar.
ONLY_LATEST_BATCH = False

# --- Planeringspolicy (instruktion 2.3 / 2.4) ------------------------------
#: N2 - hur maanga dygn framaat en order far dras foer att slippa staelltid.
CLUSTER_WINDOW_DAYS = 30
#: N3 - tillaatna tillkommande foerseningsdygn per sparad staelltidstimme.
#: 0 = klustra aldrig pa bekostnad av ett leveransdatum.
TARDINESS_BUDGET_PER_SETUP_HOUR = 0.0
#: N3 - vad som raeknas som skada. 0 = bara faktisk foersening.
PROTECT_MARGIN_DAYS = 0
#: 2.4 - marginal > detta = Groen, = detta = Gul, < detta = Roed.
GREEN_MARGIN_DAYS = 1

# --- Foerseningens enhet ---------------------------------------------------
#: ForseningDygn-kolumnerna och koerloggens LateDays* raeknas i arbetsdagar
#: enligt skiftkalendern: helger och roeda dagar raeknas inte som foersening.
#: Paaverkar inte statusfaergen eller AI_MarginalDygn - de aer kalenderdygn.
DELAY_IN_WORKDAYS = True
#: Vilka dagar som raeknas som arbetsdagar.
#:   "foretag" = samma kalender foer alla order, oavsett vilket kalendernr
#:               AoNr koer pa (foerval): maandag-fredag som aer arbetsdag i
#:               en klar majoritet av kalendrarna. Helger och roeda dagar
#:               raeknas inte.
#:   7         = ett bestaemt kalendernr foer alla order
#:   "egen"    = orderns egen Op10-kalender (kal 2/6 raeknar soendag)
DELAY_CALENDAR = "2"

# --- Schema ----------------------------------------------------------------
#: Tider paa dygnet da koerningen startar i --loop-laege (Europe/Stockholm).
SCHEDULE_TIMES = ["05:30", "11:30", "17:30"]
#: Alternativ till SCHEDULE_TIMES: koer var N:e minut. 0 = anvaend tiderna.
SCHEDULE_INTERVAL_MINUTES = 0

# --- Loggning --------------------------------------------------------------
LOG_DIR = os.path.join(HERE, "logs")
LOG_KEEP_DAYS = 30
#: Skriv aeven en Excel-/CSV-kopia av varje koerning hit. None = av.
EXPORT_DIR = None

# --- Skyddsraecken ---------------------------------------------------------
#: Applaas sa att tvaa instanser aldrig koer samtidigt mot samma databas.
APP_LOCK_NAME = "AI_Omplanering_Op10"
APP_LOCK_TIMEOUT_MS = 5000
#: Avbryt och skriv inget om kaelldatat ser orimligt tunt ut.
MIN_BASELINE_ROWS = 1


def _load_overrides() -> None:
    path = os.path.join(HERE, "config.json")
    if not os.path.isfile(path):
        return
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"Kunde inte läsa {path}: {exc}") from exc

    g = globals()
    unknown = [k for k in data if k not in g or k.startswith("_")]
    if unknown:
        raise RuntimeError(
            "Okända nycklar i config.json: " + ", ".join(sorted(unknown)))
    g.update(data)


_load_overrides()
