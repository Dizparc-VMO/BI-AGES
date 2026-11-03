# -*- coding: utf-8 -*-
"""
AI Omplanering – tjänst mot SQL Server
======================================

Läser planeringsunderlaget ur BIzparc_Direct_VMO_AI, kör samma motor som
skrivbordsappen (``omplanering_core``), och skriver resultatet tillbaka till
``tblAIAnglysisGetAoColorCodeList`` med en körlogg i ``tblAIAnglysisRun``.

Körlägen
--------

    python run_service.py --once
        En körning, avslutar. Använd detta från Windows Task Scheduler.

    python run_service.py --loop
        Långkörande process som kör på tiderna i config.SCHEDULE_TIMES
        (eller var N:e minut om SCHEDULE_INTERVAL_MINUTES är satt).

    python run_service.py --dry-run
        Läser och räknar, men skriver ingenting till databasen. Skriver ut
        nyckeltalen. Använd vid driftsättning och vid policyändringar.

    python run_service.py --check
        Kontrollerar bara anslutning, tabeller och behörigheter.

Alla lägen tar valfria ``--window`` för att ändra klusterfönstret från
standardvärdet i config. V5:s poängtrappa och förseningsstak är fasta
policyvärden i motorn.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import traceback
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config                                    # noqa: E402
import db                                        # noqa: E402
import service_log as slog                       # noqa: E402
import run_gate                                  # noqa: E402
import sql_sink_v5 as sql_sink                   # noqa: E402
import sql_source_v5 as sql_source               # noqa: E402
import omplanering_core_v5 as core               # noqa: E402


EXIT_OK = 0
EXIT_ERROR = 1
EXIT_LOCKED = 2
EXIT_SKIPPED = 3        # grinden staengd - inget att goera, inte ett fel

#: Aeldsta motorversion som tjaensten fungerar mot.
MIN_CORE_VERSION = (5, 0)

#: Delar av motorns API som tjaensten anvaender. Saknas naagon aer
#: omplanering_core.py en aeldre kopia aen tjaenstefilerna.
REQUIRED_CORE_API = [
    "compute_plan", "PlanOutcome", "ClusterPolicy", "SourceData",
    "dedupe_baseline", "BASELINE_KEY", "status_from_margin",
    "margin_days_between", "normalize_prodgr", "write_outputs",
    "GREEN_MARGIN_DAYS", "PROTECT_MARGIN_DAYS", "LOCK_HORIZON_HOURS",
    "tardiness_score", "plan_objective",
]


def _require_core_api() -> None:
    """Kontrollerar att motorn aer i takt med tjaenstefilerna.

    Tjaensten och ``omplanering_core.py`` maaste komma fraan samma leverans.
    Ligger en aeldre motor bredvid nyare tjaenstefiler yttrar det sig annars
    som ett svaartolkat ``AttributeError`` mitt i en koerning.
    """
    missing = [n for n in REQUIRED_CORE_API if not hasattr(core, n)]

    version = getattr(core, "VERSION", "0")
    try:
        parsed = tuple(int(p) for p in str(version).split(".")[:2])
    except ValueError:
        parsed = (0, 0)

    if not missing and parsed >= MIN_CORE_VERSION:
        return

    detalj = (f"saknar {', '.join(missing)}" if missing
              else f"är v{version}, kräver minst "
                   f"v{'.'.join(map(str, MIN_CORE_VERSION))}")
    raise SystemExit(
        "Motorn är inte i takt med tjänstefilerna.\n"
        f"  Laddad motor : {getattr(core, '__file__', '?')}\n"
        f"  Version      : v{version} ({detalj})\n"
        f"  Tjänstefiler : {os.path.dirname(os.path.abspath(__file__))}\n\n"
        "Kontrollera att omplanering_core_v5.py och V5-tjänstefilerna kommer\n"
        "från samma leverans och ligger i projektets rot/service-katalog.\n"
    )


def _apply_policy_config(window: float | None = None) -> core.ClusterPolicy:
    """Tar policyn ur config, med valfri override fraan kommandoraden."""
    core.PROTECT_MARGIN_DAYS = int(config.PROTECT_MARGIN_DAYS)
    core.GREEN_MARGIN_DAYS = int(config.GREEN_MARGIN_DAYS)
    core.DELAY_IN_WORKDAYS = bool(config.DELAY_IN_WORKDAYS)
    cal_setting = config.DELAY_CALENDAR
    if isinstance(cal_setting, str) and cal_setting.strip().lower() in (
            "foretag", "företag", "egen"):
        core.DELAY_CALENDAR = ("egen" if cal_setting.strip().lower() == "egen"
                               else core.COMPANY_CALENDAR)
    elif cal_setting is None:
        core.DELAY_CALENDAR = "egen"
    else:
        try:
            core.DELAY_CALENDAR = int(cal_setting)
        except (TypeError, ValueError):
            raise SystemExit(
                f'Ogiltigt DELAY_CALENDAR i config: {cal_setting!r}. '
                f'Tillåtet: "foretag", "egen" eller ett kalendernr, t.ex. 7.')
    return core.ClusterPolicy(
        window_days=int(config.CLUSTER_WINDOW_DAYS if window is None else window),
        budget_days_per_hour=0.0,
    )


def _log_summary(outcome: core.PlanOutcome) -> None:
    s = outcome.stats
    slog.log(f"Röd {s['red_before']} → {s['red_after']}  |  "
             f"Gul {s['yellow_before']} → {s['yellow_after']}  |  "
             f"Grön {s['green_before']} → {s['green_after']}")
    unit = s.get("late_unit", "dygn")
    slog.log(f"Försening ({unit}) {s['late_days_before']:g} → "
             f"{s['late_days_after']:g}  |  "
             f"{s['worse_count']} order blev mer försenade "
             f"(värst {s['worst_days']:g} {unit})")
    slog.log(f"V5-poäng {s['tardiness_score_before']:g} → "
             f"{s['tardiness_score_after']:g}  |  cap uppnått: "
             f"{'ja' if s['cap_met'] else 'nej'}  |  "
             f"capöverskridanden: {s['cap_breach_count']} order, "
             f"{s['cap_excess_days']:g} dygn")
    if s.get("optimization_fallback"):
        slog.warn(
            "V5-kandidaten avvisades; originalplanen behölls. "
            f"Kandidaten hade {s['rejected_cap_breach_count']} order över taket "
            f"({s['rejected_cap_excess_days']:g} extra dygn) och "
            f"{s['rejected_unplanned_count']} oplanerade order.")
    slog.log(f"Ställtid sparad {s['setup_hours_saved']} h över "
             f"{s['clustered']} order, varav {s['pulled_forward']} framdragna  |  "
             f"{s['rerouted']} omrutade")
    for w in outcome.warnings:
        slog.warn(w)


def run_once(policy: core.ClusterPolicy, dry_run: bool = False,
             force: bool = False, quiet_skip: bool = False) -> int:
    """En koerning. Returnerar en exitkod.

    Kontrollerar foerst styrtabellen ``sysRunScript``: koer bara naer
    laddnings-SP:n satt Status = 0. ``force`` foerbigaar grinden.
    ``quiet_skip`` daempar loggningen naer inget fanns att goera (pollning).
    """
    started = datetime.now()
    use_gate = config.USE_RUN_GATE and not force

    conn = None
    try:
        conn = db.connect()
    except Exception as exc:                       # noqa: BLE001
        slog.error(f"Kunde inte ansluta till {config.SERVER_NAME}: {exc}")
        return EXIT_ERROR

    try:
        # --- Grinden: har SP:n laddat ny data? ---------------------------
        gate_state = None
        if use_gate:
            try:
                go, gate_state, reason = run_gate.should_run(conn, slog.log)
            except Exception as exc:               # noqa: BLE001
                slog.error(f"Kunde inte läsa {config.TBL_RUN_GATE}: {exc}")
                return EXIT_ERROR
            if not go:
                if not quiet_skip:
                    slog.log(f"Ingen körning: {reason}")
                return EXIT_SKIPPED
            slog.log("=" * 72)
            slog.log(f"Grind öppen: {reason}")
        else:
            slog.log("=" * 72)
            if config.USE_RUN_GATE:
                slog.warn("--force: styrtabellen förbigås.")

        slog.log(f"AI Omplanering v{core.VERSION} startar "
                 f"({'TESTKÖRNING – skriver inget' if dry_run else 'skarp körning'})")
        slog.log(f"Policy: {policy.describe()}")
        slog.log(f"Statusgräns: marginal > {core.GREEN_MARGIN_DAYS} dygn = Grön, "
                 f"= {core.GREEN_MARGIN_DAYS} = Gul, därunder = Röd")
        if core.DELAY_IN_WORKDAYS:
            slog.log(f"Försening räknas i arbetsdagar mot {core.delay_basis()} "
                     f"(helger och röda dagar räknas inte)")

        with db.app_lock(conn) as acquired:
            if not acquired:
                slog.warn("En annan körning pågår redan – avslutar utan att "
                          "skriva något.")
                return EXIT_LOCKED

            try:
                src = sql_source.load_source_sql(conn, slog.log)
                outcome = core.compute_plan(src, policy=policy, log=slog.log)
            except Exception as exc:               # noqa: BLE001
                detail = traceback.format_exc()
                slog.error(f"Beräkningen misslyckades: {exc}")
                slog.log(detail)
                if not dry_run:
                    sql_sink.write_failure(conn, started, detail, slog.log)
                return EXIT_ERROR

            _log_summary(outcome)

            if dry_run:
                slog.log("TESTKÖRNING – ingenting skrevs till databasen.")
                return EXIT_OK

            try:
                run_id = sql_sink.write_outcome(conn, outcome, started, slog.log)
            except Exception as exc:               # noqa: BLE001
                detail = traceback.format_exc()
                slog.error(f"Kunde inte skriva resultatet: {exc}")
                slog.log(detail)
                sql_sink.write_failure(conn, started, detail, slog.log)
                return EXIT_ERROR

            sql_sink.purge(conn, log=slog.log)

            if config.EXPORT_DIR:
                _export_files(src, outcome, run_id)

            # Grinden stängs först när resultatet ligger i databasen. Vid fel
            # ovan lämnas Status = 0 så att nästa poll gör om försöket.
            if use_gate and gate_state is not None:
                try:
                    run_gate.mark_script_done(conn, gate_state, slog.log)
                except Exception as exc:           # noqa: BLE001
                    slog.error(f"Resultatet skrevs men {config.TBL_RUN_GATE} "
                               f"kunde inte uppdateras: {exc}. Nästa poll kör "
                               f"om på samma data.")

            slog.log(f"KLART på {(datetime.now() - started).total_seconds():.1f} s")
            return EXIT_OK
    finally:
        try:
            conn.close()
        except Exception:                          # noqa: BLE001
            pass
        slog.prune()


def _export_files(src, outcome, run_id: str) -> None:
    """Valfri Excel-/CSV-kopia, samma format som skrivbordsappen."""
    try:
        os.makedirs(config.EXPORT_DIR, exist_ok=True)
        stem = os.path.join(config.EXPORT_DIR, "AI_omplanering")
        xlsx, csv_path = core.write_outputs(
            src, outcome.result, outcome.summary, stem + ".xlsx",
            config.EXPORT_DIR, outcome.run_ts, slog.log)
        slog.log(f"Kopia skriven: {os.path.basename(xlsx)}")
    except Exception as exc:                       # noqa: BLE001
        slog.warn(f"Filkopian kunde inte skrivas: {exc}")


def check() -> int:
    """Kontrollerar anslutning, tabeller och skrivraettighet."""
    slog.log(f"Motor: v{core.VERSION} ({getattr(core, '__file__', '?')})")
    slog.log(f"Kontrollerar {config.SERVER_NAME}/{config.DATABASE} ...")
    try:
        with db.open_connection() as conn:
            cur = conn.cursor()
            slog.log(f"  Ansluten. Serverns tid: {db.server_now(conn)}")

            ok = True
            for table in (config.TBL_BASELINE, config.TBL_OPERATIONS,
                          config.TBL_CALENDAR, config.TBL_PRIO,
                          config.TBL_RESULT, config.TBL_RUN,
                          config.TBL_RUN_GATE):
                try:
                    n = cur.execute(
                        f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                    slog.log(f"  OK    {table:<48} {n} rader")
                except Exception as exc:           # noqa: BLE001
                    ok = False
                    slog.error(f"  SAKNAS {table}: {exc}")

            try:
                cur.execute(f"SELECT TOP 0 * FROM {config.TBL_RESULT}")
                cols = {d[0] for d in cur.description}
                missing = [c for c in sql_sink.RESULT_COLUMNS if c not in cols]
                if missing:
                    ok = False
                    slog.error("  Resultattabellen saknar kolumnerna: "
                               + ", ".join(missing))
                else:
                    slog.log("  OK    Resultattabellens kolumner stämmer")
            except Exception as exc:               # noqa: BLE001
                ok = False
                slog.error(f"  Kunde inte läsa resultattabellens kolumner: {exc}")

            with db.app_lock(conn) as acquired:
                slog.log("  OK    Applås kunde tas" if acquired
                         else "  Applåset är upptaget av en annan körning")

            try:
                state = run_gate.read(conn, slog.log)
                if not state.exists:
                    slog.warn(f"  {config.TBL_RUN_GATE} är tom – en styrrad "
                              f"läggs in i viloläge vid första körningen.")
                else:
                    label = ("redo för körning" if state.ready
                             else "väntar på ny data från SP:n")
                    slog.log(f"  OK    Grind: Status = {state.status} "
                             f"({label}); SP {state.senast_sp}, "
                             f"script {state.senast_script}")
            except Exception as exc:               # noqa: BLE001
                ok = False
                slog.error(f"  Kunde inte läsa {config.TBL_RUN_GATE}: {exc}")

            return EXIT_OK if ok else EXIT_ERROR
    except Exception as exc:                       # noqa: BLE001
        slog.error(f"Kontrollen misslyckades: {exc}")
        return EXIT_ERROR


def watch(policy: core.ClusterPolicy) -> int:
    """Pollar styrtabellen var ``POLL_INTERVAL_MINUTES``:e minut.

    Koer bara naer laddnings-SP:n satt Status = 0. Tysta pollar loggas inte,
    sa loggen visar bara faktiska koerningar och fel.
    """
    interval = max(1, int(config.POLL_INTERVAL_MINUTES)) * 60
    slog.log(f"Tjänsten startad. Pollar {config.TBL_RUN_GATE} var "
             f"{config.POLL_INTERVAL_MINUTES}:e minut och kör när "
             f"Status = {run_gate.STATUS_SP_KLAR}. Avsluta med Ctrl+C.")

    idle_since: datetime | None = None
    while True:
        try:
            code = run_once(policy, quiet_skip=True)
            if code == EXIT_SKIPPED:
                # Livstecken en gaang i timmen sa att loggen visar att
                # tjaensten lever utan att fyllas av pollrader.
                now = datetime.now()
                if idle_since is None:
                    idle_since = now
                elif (now - idle_since).total_seconds() >= 3600:
                    slog.log("Väntar fortfarande på att SP:n laddar ny data.")
                    idle_since = now
            else:
                idle_since = None
        except KeyboardInterrupt:
            slog.log("Avslutar på begäran.")
            return EXIT_OK
        except Exception as exc:                   # noqa: BLE001
            slog.error(f"Oväntat fel i pollningen: {exc}")
            slog.log(traceback.format_exc())

        try:
            time.sleep(interval)
        except KeyboardInterrupt:
            slog.log("Avslutar på begäran.")
            return EXIT_OK


def _next_scheduled(now: datetime) -> datetime:
    """Naesta koertidpunkt enligt config."""
    if config.SCHEDULE_INTERVAL_MINUTES:
        return now + timedelta(minutes=int(config.SCHEDULE_INTERVAL_MINUTES))

    times = []
    for text in config.SCHEDULE_TIMES:
        hh, _, mm = text.partition(":")
        times.append((int(hh), int(mm)))
    times.sort()

    for hh, mm in times:
        candidate = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if candidate > now:
            return candidate
    hh, mm = times[0]
    return (now + timedelta(days=1)).replace(hour=hh, minute=mm, second=0,
                                             microsecond=0)


def loop(policy: core.ClusterPolicy) -> int:
    """Laangkoerande laege. Ett fel i en koerning stoppar inte tjaensten."""
    plan = (f"var {config.SCHEDULE_INTERVAL_MINUTES}:e minut"
            if config.SCHEDULE_INTERVAL_MINUTES
            else "kl. " + ", ".join(config.SCHEDULE_TIMES))
    slog.log(f"Tjänsten startad. Kör {plan}. Avsluta med Ctrl+C.")

    while True:
        nxt = _next_scheduled(datetime.now())
        slog.log(f"Nästa körning {nxt:%Y-%m-%d %H:%M}")
        try:
            while datetime.now() < nxt:
                time.sleep(min(30, max(1, (nxt - datetime.now()).total_seconds())))
        except KeyboardInterrupt:
            slog.log("Avslutar på begäran.")
            return EXIT_OK

        try:
            run_once(policy)
        except KeyboardInterrupt:
            slog.log("Avslutar på begäran.")
            return EXIT_OK
        except Exception as exc:                   # noqa: BLE001
            slog.error(f"Oväntat fel i körningen: {exc}")
            slog.log(traceback.format_exc())


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=f"AI Omplanering v{core.VERSION} – SQL-tjänst")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true",
                      help="Kör en gång och avsluta (för Task Scheduler)")
    mode.add_argument("--loop", action="store_true",
                      help="Långkörande tjänst enligt schemat i config")
    mode.add_argument("--dry-run", action="store_true",
                      help="Räkna men skriv ingenting till databasen")
    mode.add_argument("--watch", action="store_true",
                      help=f"Pollar {config.TBL_RUN_GATE} var "
                           f"{config.POLL_INTERVAL_MINUTES}:e minut och kör "
                           f"när SP:n satt Status = 0")
    mode.add_argument("--check", action="store_true",
                      help="Kontrollera anslutning, tabeller och behörigheter")
    ap.add_argument("--force", action="store_true",
                    help="Kör även om styrtabellen inte signalerat ny data")
    ap.add_argument("--window", type=int, default=None,
                    help="Klusterfönster i dygn (override av config)")
    args = ap.parse_args(argv)

    _require_core_api()
    policy = _apply_policy_config(args.window)

    if args.check:
        return check()
    if args.watch:
        return watch(policy)
    if args.loop:
        return loop(policy)
    if args.dry_run:
        return run_once(policy, dry_run=True, force=args.force)
    return run_once(policy, force=args.force)


if __name__ == "__main__":
    sys.exit(main())
