import unittest
import os
import tempfile
from datetime import datetime, timedelta

import pandas as pd

import omplanering_core_v5 as core


def _source(now, start_offsets_hours, duration_hours=1.0, calendar_days=14):
    baseline_rows = []
    operation_rows = []
    for idx, offset in enumerate(start_offsets_hours, start=1):
        start = now + timedelta(hours=offset)
        end = start + timedelta(hours=duration_hours)
        due = now + timedelta(days=8)
        baseline_rows.append({
            "AoNr": idx,
            "AoPos": 10,
            "OpNr": 10,
            "ProdGr": 10122,
            "ArtNr": f"ART-{idx}",
            "OpStatus": 0,
            "AoStartDatTid": start,
            "AoSlutDatTid": end,
            "TiSlutDat": end,
            "OrderNr": 200000 + idx,
            "OrdBerLevDat": due,
            "ColorCode": "#00ff00",
            "ColorName": "Grön",
            "OpkoPrioritet": idx,
        })
        operation_rows.append({
            "AoNr": idx,
            "AoPos": 10,
            "OpNr": 10,
            "ProdGr": 10122,
            "_prodgr": "10122",
            "ArtNr": f"ART-{idx}",
            "OpStatus": 0,
            "TiSlutDat": end,
            "aostartdattid": start,
            "aoslutdattid": end,
            "stalltid": 0.0,
            "stycktid": duration_hours,
            "kalendernr": 7,
        })

    calendar_rows = []
    for day_offset in range(calendar_days):
        day = now.date() + timedelta(days=day_offset)
        shift_start = datetime.combine(day, datetime.min.time()).replace(
            hour=6)
        shift_end = shift_start + timedelta(hours=8, minutes=15)
        calendar_rows.append({
            "dDate": day.isoformat(),
            "_date": pd.Timestamp(day),
            "kalendernr": 7,
            "Date_komtid": shift_start,
            "Date_gicktid": shift_end,
            "arbtimperdag": 8.25,
            "arbtimperdag_firstdaymode": 8.25,
        })

    return core.SourceData(
        baseline=pd.DataFrame(baseline_rows),
        operations=pd.DataFrame(operation_rows),
        calendar=pd.DataFrame(calendar_rows),
        prio=pd.DataFrame(columns=["ArtNr", "OpNr", "Prio1", "_artnr"]),
    )


class V5CoreTests(unittest.TestCase):
    def test_progressive_tardiness_score_boundaries(self):
        expected = {
            0: 0,
            1: 1,
            2: 2,
            3: 5,
            5: 11,
            6: 17,
            10: 41,
            11: 51,
        }
        for days, score in expected.items():
            with self.subTest(days=days):
                self.assertEqual(core.tardiness_score(days), score)
        self.assertEqual(core.tardiness_score(2.5), 3.5)

    def test_four_hour_lock_boundary(self):
        now = datetime(2026, 10, 8, 6, 0)
        src = _source(now, [3.999, 4.0, 4.001])
        calendar = core.WorkCalendar(src.calendar, now)
        jobs, _ = core.build_jobs(src, calendar, now)

        self.assertTrue(jobs[0].locked_horizon)
        self.assertTrue(jobs[1].locked_horizon)
        self.assertFalse(jobs[0].movable)
        self.assertFalse(jobs[1].movable)
        self.assertFalse(jobs[2].locked_horizon)
        self.assertTrue(jobs[2].movable)

    def test_order_score_does_not_scale_with_operation_duration(self):
        now = datetime(2026, 10, 8, 6, 0)
        src = _source(now, [5.0, 5.0])
        src.operations.loc[1, "stycktid"] = 100.0
        calendar = core.WorkCalendar(src.calendar, now)
        jobs, _ = core.build_jobs(src, calendar, now)
        for job in jobs:
            job.ai_tislutdat = job.ord_ber_lev_dat + timedelta(days=3)

        metrics = core.v5_tardiness_metrics(jobs)
        self.assertEqual(metrics["tardiness_score_after"], 10.0)

    def test_missing_operation_duration_is_frozen_without_median_fallback(self):
        now = datetime(2026, 10, 8, 6, 0)
        src = _source(now, [5.0])
        src.operations.loc[0, "stycktid"] = 0.0
        calendar = core.WorkCalendar(src.calendar, now)
        jobs, warnings = core.build_jobs(src, calendar, now)

        self.assertFalse(jobs[0].movable)
        self.assertEqual(jobs[0].frozen_reason, "saknar Op10-operationstid")
        self.assertTrue(any("ingen varaktighet gissades" in warning
                            for warning in warnings))

    def test_cap_breach_pins_only_offending_job_to_original_slot(self):
        now = datetime(2026, 10, 8, 6, 0)
        src = _source(now, [5.0], duration_hours=100.0, calendar_days=25)
        outcome = core.compute_plan(src, now=now)

        self.assertFalse(outcome.stats["optimization_fallback"])
        self.assertTrue(outcome.stats["cap_met"])
        self.assertEqual(outcome.stats["cap_breach_count"], 0)
        self.assertEqual(outcome.stats["changed"], 0)
        self.assertEqual(outcome.stats["cap_repaired_count"], 1)
        self.assertGreater(outcome.stats[
            "candidate_before_repair_cap_excess_days"], 0)
        self.assertEqual(outcome.jobs[0].ai_tislutdat,
                         outcome.jobs[0].orig_tislutdat)
        self.assertTrue(outcome.jobs[0].cap_locked_original)

    def test_local_cap_repair_keeps_other_jobs_movable(self):
        now = datetime(2026, 10, 8, 6, 0)
        src = _source(now, [5.0, 6.0])
        calendar = core.WorkCalendar(src.calendar, now)
        jobs, _ = core.build_jobs(src, calendar, now)
        machines = core.build_machines(jobs, {"10122": 7})
        for job in jobs:
            job.ai_start = job.orig_start
            job.ai_end = job.orig_end
            job.ai_tislutdat = job.orig_tislutdat

        offender = jobs[0]
        offender.ai_tislutdat = offender.ord_ber_lev_dat + timedelta(days=1)
        offender.ai_end = offender.ai_tislutdat - offender.downstream_delta

        pinned = core.repair_cap_violations(
            jobs, machines, calendar, now)

        self.assertEqual(pinned, 1)
        self.assertTrue(offender.cap_locked_original)
        self.assertEqual(offender.ai_start, offender.orig_start)
        self.assertFalse(jobs[1].cap_locked_original)
        self.assertNotEqual(jobs[1].ai_start, jobs[1].orig_start)
        self.assertTrue(core.v5_tardiness_metrics(jobs)["cap_met"])

    def test_calendar_end_pins_unplanned_job_to_original_slot(self):
        now = datetime(2026, 10, 8, 6, 0)
        src = _source(now, [5.0], duration_hours=100.0, calendar_days=1)
        outcome = core.compute_plan(src, now=now)

        self.assertFalse(outcome.stats["optimization_fallback"])
        self.assertEqual(outcome.stats[
            "candidate_before_repair_unplanned_count"], 1)
        self.assertEqual(outcome.stats["unplanned_count"], 0)
        self.assertEqual(outcome.stats["cap_repaired_count"], 1)
        self.assertEqual(outcome.jobs[0].ai_tislutdat,
                         outcome.jobs[0].orig_tislutdat)
        self.assertTrue(outcome.jobs[0].cap_locked_original)
        self.assertIn("kalendertäckning", " ".join(outcome.warnings).lower())
        self.assertTrue(outcome.stats["cap_met"])

    def test_excel_run_writes_v5_named_outputs(self):
        now = datetime(2026, 10, 8, 6, 0)
        src = _source(now, [5.0])
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = os.path.join(tmpdir, "synthetic.xlsx")
            with pd.ExcelWriter(input_path) as writer:
                src.baseline.to_excel(
                    writer, sheet_name=core.SHEET_BASELINE, index=False)
                src.operations.drop(columns=["_prodgr"]).to_excel(
                    writer, sheet_name=core.SHEET_OPERATIONS, index=False)
                src.calendar.drop(columns=["_date"]).to_excel(
                    writer, sheet_name=core.SHEET_CALENDAR, index=False)
                src.prio.drop(columns=["_artnr"]).to_excel(
                    writer, sheet_name=core.SHEET_PRIO, index=False)

            result = core.run_replanning(
                input_path, output_dir=tmpdir, now=now)

            self.assertIn("_v5_resultat_", os.path.basename(result.xlsx_path))
            self.assertIn("_v5_resultat_", os.path.basename(result.csv_path))
            self.assertTrue(os.path.isfile(result.xlsx_path))
            self.assertTrue(os.path.isfile(result.csv_path))
            self.assertIn("AI_TardinessScore", result.result.columns)
            self.assertEqual(result.stats["rows"], 1)
            self.assertFalse(result.stats["optimization_fallback"])


if __name__ == "__main__":
    unittest.main()