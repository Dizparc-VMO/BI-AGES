import json
import os
import queue
import sys
import tempfile
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pandas as pd

import omplanering_app_v7 as app
import omplanering_core_v7 as core
import test_omplanering_v5 as v5_tests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "service"))
import sql_sink_v7


def _source(*args, **kwargs):
    with patch.object(v5_tests, "core", core):
        return v5_tests._source(*args, **kwargs)


class V7RegressionTests(v5_tests.V5CoreTests):
    """Run inherited calendar and lock safety tests against the V7 engine."""

    def setUp(self):
        replacement = patch.object(v5_tests, "core", core)
        replacement.start()
        self.addCleanup(replacement.stop)

    def test_excel_run_writes_v7_named_outputs(self):
        now = datetime(2026, 10, 8, 6)
        src = v5_tests._source(now, [3, 7])
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = os.path.join(tmpdir, "synthetic.xlsx")
            with pd.ExcelWriter(input_path) as writer:
                for frame, sheet, helper in (
                    (src.baseline, core.SHEET_BASELINE, None),
                    (src.operations, core.SHEET_OPERATIONS, "_prodgr"),
                    (src.calendar, core.SHEET_CALENDAR, "_date"),
                    (src.prio, core.SHEET_PRIO, "_artnr"),
                ):
                    frame.drop(columns=[helper], errors="ignore").to_excel(
                        writer, sheet_name=sheet, index=False)
            result = core.run_replanning(
                input_path, tmpdir, now=now, lock_horizon_hours=8)
            for path in (result.xlsx_path, result.csv_path):
                self.assertIn("_v7_resultat_", os.path.basename(path))
                self.assertTrue(os.path.isfile(path))
            self.assertEqual(result.stats["lock_horizon_hours"], 8)
            self.assertEqual(result.stats["frozen_lock_horizon"], 2)
            self.assertEqual(dict(result.summary)["Låshorisont (timmar)"], 8)
            summary = pd.read_excel(result.xlsx_path, sheet_name=core.SHEET_SUMMARY,
                                    header=None)
            self.assertEqual(summary.loc[
                summary[0] == "Låshorisont (timmar)", 1].iloc[0], 8)
            self.assertTrue(any("låshorisont 8 h" in line for line in result.log_lines))

    def test_excel_run_writes_v5_named_outputs(self):
        self.test_excel_run_writes_v7_named_outputs()

    def test_cap_breach_pins_only_offending_job_to_original_slot(self):
        now = datetime(2026, 10, 8, 6)
        src = _source(now, [5.0], duration_hours=100.0, calendar_days=25)
        outcome = core.compute_plan(
            src, now=now, policy=core.ClusterPolicy(global_max_tardiness_days=0))
        self.assertFalse(outcome.stats["optimization_fallback"])
        self.assertTrue(outcome.stats["cap_met"])
        self.assertEqual(outcome.stats["cap_repaired_count"], 1)
        self.assertTrue(outcome.jobs[0].cap_locked_original)

    def test_progressive_tardiness_score_boundaries(self):
        expected = {0: 1, 1: 2, 2: 2, 3: 4, 5: 9, 6: 9, 10: 20, 11: 20}
        for days, score in expected.items():
            with self.subTest(days=days):
                self.assertEqual(core.tardiness_score(days), score)
        self.assertEqual(core.tardiness_score(2.5), 4)

    def test_local_cap_repair_keeps_other_jobs_movable(self):
        now = datetime(2026, 10, 8, 6)
        src = _source(now, [5.0, 6.0])
        calendar = core.WorkCalendar(src.calendar, now)
        jobs, _ = core.build_jobs(src, calendar, now, max_tardiness_days=0)
        machines = core.build_machines(jobs, {"10122": 7})
        for job in jobs:
            job.max_tardiness_days = 0
            job.ai_start = job.orig_start
            job.ai_end = job.orig_end
            job.ai_tislutdat = job.orig_tislutdat
        offender = jobs[0]
        offender.ai_tislutdat = offender.ord_ber_lev_dat + pd.Timedelta(days=1)
        offender.ai_end = offender.ai_tislutdat - offender.downstream_delta
        pinned = core.repair_cap_violations(
            jobs, machines, calendar, now,
            policy=core.ClusterPolicy(global_max_tardiness_days=0))
        self.assertEqual(pinned, 1)
        self.assertTrue(offender.cap_locked_original)
        self.assertFalse(jobs[1].cap_locked_original)

    def test_order_score_does_not_scale_with_operation_duration(self):
        now = datetime(2026, 10, 8, 6)
        src = _source(now, [5.0, 5.0])
        src.operations.loc[1, "stycktid"] = 100.0
        jobs, _ = core.build_jobs(src, core.WorkCalendar(src.calendar, now), now)
        for job in jobs:
            job.ai_tislutdat = job.ord_ber_lev_dat + pd.Timedelta(days=3)
        self.assertEqual(core.v7_tardiness_metrics(jobs)["tardiness_score_after"], 8)


class V7HorizonTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 8, 6)

    def jobs(self, offsets, hours=4):
        src = _source(self.now, offsets)
        return core.build_jobs(src, core.WorkCalendar(src.calendar, self.now),
                               self.now, lock_horizon_hours=hours)[0]

    def test_custom_decimal_inclusive_boundary(self):
        jobs = self.jobs([2.499, 2.5, 2.501], "2,5")
        self.assertEqual([j.locked_horizon for j in jobs], [True, True, False])
        self.assertEqual([j.movable for j in jobs], [False, False, True])
        self.assertIn("2.5-timmars", jobs[0].frozen_reason)

    def test_zero_keeps_started_and_status_locked(self):
        jobs = self.jobs([-1, 0, 0.1], 0)
        self.assertEqual([j.movable for j in jobs], [False, False, True])
        self.assertFalse(any(j.locked_horizon for j in jobs))
        src = _source(self.now, [1])
        src.operations.loc[0, "OpStatus"] = 1
        jobs, _ = core.build_jobs(src, core.WorkCalendar(src.calendar, self.now),
                                  self.now, lock_horizon_hours=0)
        self.assertFalse(jobs[0].movable)

    def test_validation(self):
        for value in (-1, "", "abc", None, True, "nan", "inf", "-inf", 1e100):
            with self.subTest(value=value), self.assertRaises(ValueError):
                core.validate_lock_horizon_hours(value)
        self.assertEqual(core.validate_lock_horizon_hours(" 2,5 "), 2.5)
        self.assertEqual(core.validate_lock_horizon_hours("0"), 0)

    def test_runs_are_isolated_and_default_is_four(self):
        src = _source(self.now, [3, 5, 7])
        for hours, count in ((8, 3), (0, 0), (4, 1)):
            outcome = core.compute_plan(src, now=self.now, lock_horizon_hours=hours)
            self.assertEqual(outcome.stats["frozen_lock_horizon"], count)
            self.assertEqual(outcome.stats["lock_horizon_hours"], hours)
        default = core.compute_plan(src, now=self.now)
        self.assertEqual(default.stats["lock_horizon_hours"], 4)
        self.assertEqual(default.stats["frozen_lock_horizon"], 1)
        self.assertEqual(core.LOCK_HORIZON_HOURS, 4)


class V7UiTests(unittest.TestCase):
    def settings_stub(self):
        class FakeVar:
            def __init__(self, value=""):
                self.value = value

            def get(self):
                return self.value

            def set(self, value):
                self.value = value

        return SimpleNamespace(
            var_input=Mock(get=Mock(return_value="input.xlsx")),
            var_output=Mock(get=Mock(return_value="output")),
            var_window=Mock(get=Mock(return_value="30")),
            var_lock_horizon=Mock(get=Mock(return_value="2,5")),
            var_max_tardiness=Mock(get=Mock(return_value="10")),
            score_band_vars=[
                [FakeVar(str(lower)), FakeVar("" if upper is None else str(upper)),
                 FakeVar(str(score))]
                for lower, upper, score in core.DEFAULT_TARDINESS_SCORE_BANDS
            ],
        )

    def test_settings_round_trip_and_invalid_fallback(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            settings_path = os.path.join(tmpdir, "settings.json")
            class FakeVar:
                def __init__(self, value=""):
                    self.value = value

                def get(self):
                    return self.value

                def set(self, value):
                    self.value = value

            with patch.object(app, "SETTINGS_FILE", settings_path), \
                    patch.object(app.tk, "StringVar", FakeVar):
                stub = self.settings_stub()
                app.App._save_settings(stub)
                app.App._load_settings(stub)
                self.assertEqual(stub.var_lock_horizon.set.call_args.args[0], "2.5")
                with open(settings_path, encoding="utf-8") as fh:
                    saved = json.load(fh)
                    self.assertEqual(saved["lock_horizon_hours"], 2.5)
                    self.assertEqual(saved["max_tardiness_days"], 10)
                    self.assertEqual(saved["score_bands"], [
                        [-99, 0, 1.0], [1, 2, 2.0], [3, 4, 4.0],
                        [5, 7, 9.0], [8, 9, 10.0], [10, None, 20.0],
                    ])
                for data in ({"lock_horizon_hours": -1}, {}, []):
                    with open(settings_path, "w", encoding="utf-8") as fh:
                        json.dump(data, fh)
                    app.App._load_settings(stub)
                    self.assertEqual(float(stub.var_lock_horizon.set.call_args.args[0]), 4)

    def test_worker_forwards_snapshot(self):
        stub = SimpleNamespace(queue=queue.Queue())
        policy = core.ClusterPolicy()
        sentinel = object()
        with patch.object(core, "run_replanning", return_value=sentinel) as run:
            app.App._work(stub, "input.xlsx", "output", policy, 2.5)
        self.assertEqual(run.call_args.kwargs["lock_horizon_hours"], 2.5)
        self.assertEqual(stub.queue.get_nowait(), ("done", sentinel))

    def test_invalid_input_does_not_start_worker(self):
        stub = self.settings_stub()
        stub.var_lock_horizon.get.return_value = "nan"
        stub.worker = None
        with patch.object(app.os.path, "isfile", return_value=True), \
                patch.object(app.messagebox, "showerror") as error, \
                patch.object(app.threading, "Thread") as thread:
            app.App._run(stub)
        error.assert_called_once()
        thread.assert_not_called()


class V7CustomerPolicyTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 8, 6)

    def test_dynamic_bands_use_rounded_up_whole_days_and_inclusive_bounds(self):
        bands = core.validate_tardiness_score_bands([
            [-99, 0, 1], [1, 2, 2], [3, 4, 4],
            [5, 7, 9], [8, 9, 10], [10, None, 20],
        ])
        self.assertEqual(core.tardiness_score(0, bands), 1)
        self.assertEqual(core.tardiness_score(0.01, bands), 2)
        self.assertEqual(core.tardiness_score(1.2, bands), 2)
        self.assertEqual(core.tardiness_score(2.01, bands), 4)
        self.assertEqual(core.tardiness_score(9.01, bands), 20)
        self.assertEqual(core.tardiness_score(100, bands), 20)

    def test_dynamic_band_validation_requires_contiguous_inclusive_integer_ranges(self):
        with self.assertRaises(ValueError):
            core.validate_tardiness_score_bands([[0, 2, 1], [2, None, 3]])
        with self.assertRaises(ValueError):
            core.validate_tardiness_score_bands([[0, 1, 1], [3, None, 2]])
        with self.assertRaises(ValueError):
            core.validate_tardiness_score_bands([[0, 0, 1], [1, 2, 2]])
        with self.assertRaises(ValueError):
            core.validate_tardiness_score_bands([[0, None, 1], [1, None, 2]])
        with self.assertRaises(ValueError):
            core.validate_tardiness_score_bands([[0, 1.5, 1], [2, None, 2]])
        with self.assertRaises(ValueError):
            core.validate_customer_weight(0)
        with self.assertRaises(ValueError):
            core.validate_max_tardiness_days("inf")

    def test_add_band_splits_the_open_ended_final_range(self):
        class FakeVar:
            def __init__(self, value):
                self.value = value

            def get(self):
                return self.value

            def set(self, value):
                self.value = value

        stub = SimpleNamespace(score_band_vars=[
            [FakeVar("0"), FakeVar("0"), FakeVar("1")],
            [FakeVar("1"), FakeVar(""), FakeVar("2")],
        ], _render_score_bands=lambda: None)
        with patch.object(app.tk, "StringVar",
                          side_effect=lambda value: FakeVar(value)):
            app.App._add_score_band(stub)
        self.assertEqual(stub.score_band_vars[-2][1].get(), "1")
        self.assertEqual([value.get() for value in stub.score_band_vars[-1]], ["2", "", "2"])
        self.assertEqual(
            core.validate_tardiness_score_bands(
                [[value.get() for value in band] for band in stub.score_band_vars]),
            ((0, 0, 1.0), (1, 1, 2.0), (2, None, 2.0)))

    def test_unknown_color_stays_unknown(self):
        self.assertEqual(core.normalize_color(None), "Okänd")
        self.assertEqual(core.normalize_color("mystery"), "Okänd")
        self.assertEqual(core.status_from_margin(None), "Okänd")

    def test_customer_config_matches_order_number_before_ao_deduplication(self):
        src = _source(self.now, [5])
        second = src.baseline.iloc[0].copy()
        second["OrderNr"] = 299999
        second["OrdBerLevDat"] = second["OrdBerLevDat"] + pd.Timedelta(days=1)
        src.baseline = pd.concat([src.baseline, second.to_frame().T], ignore_index=True)
        src.customer_config = pd.DataFrame([
            {"OrderNumber": 200001, "Customer": 127, "Vikt": 10, "MaxLate": 7},
            {"OrderNumber": 299999, "Customer": 22, "Vikt": 5, "MaxLate": 3},
        ])
        policy = core.ClusterPolicy(global_max_tardiness_days=10)
        calendar = core.WorkCalendar(src.calendar, self.now)
        jobs, _ = core.build_jobs(
            src, calendar, self.now,
            max_tardiness_days=policy.global_max_tardiness_days)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].customer_order_numbers, ("200001", "299999"))
        self.assertEqual(jobs[0].customer_numbers, ("127", "22"))
        self.assertEqual(jobs[0].customer_weight, 10)
        self.assertEqual(jobs[0].max_tardiness_days, 3)

    def test_weighted_score_and_existing_over_limit_baseline(self):
        src = _source(self.now, [5, 6])
        src.customer_config = pd.DataFrame([
            {"OrderNumber": 200001, "Customer": "Volvo", "Vikt": 10, "MaxLate": 5},
            {"OrderNumber": 200002, "Customer": "Scania", "Vikt": 5, "MaxLate": 5},
        ])
        policy = core.ClusterPolicy(global_max_tardiness_days=10)
        outcome = core.compute_plan(src, now=self.now, policy=policy)
        jobs = outcome.jobs
        for job in jobs:
            job.ai_tislutdat = job.ord_ber_lev_dat + pd.Timedelta(days=3)
        metrics = core.v7_tardiness_metrics(jobs, policy)
        self.assertEqual(metrics["tardiness_score_after"], 60)

        first = jobs[0]
        first.max_tardiness_days = 2
        first.orig_tislutdat = first.ord_ber_lev_dat + pd.Timedelta(days=12)
        first.ai_tislutdat = first.ord_ber_lev_dat + pd.Timedelta(days=12)
        metrics = core.v7_tardiness_metrics(jobs, policy)
        self.assertGreater(metrics["baseline_over_limit_count"], 0)
        self.assertTrue(metrics["cap_met"])

    def test_excel_rows_separate_raw_and_weighted_scores(self):
        src = _source(self.now, [5])
        src.customer_config = pd.DataFrame([
            {"OrderNumber": 200001, "Customer": "Volvo", "Vikt": 10, "MaxLate": 5},
        ])
        policy = core.ClusterPolicy()
        jobs, _ = core.build_jobs(
            src, core.WorkCalendar(src.calendar, self.now), self.now,
            max_tardiness_days=policy.global_max_tardiness_days)
        jobs[0].ai_tislutdat = jobs[0].ord_ber_lev_dat + pd.Timedelta(days=3)
        frame = core.jobs_to_frame(jobs, self.now, policy=policy)
        self.assertEqual(frame.loc[0, "AI_TardinessScore"], 4)
        self.assertEqual(frame.loc[0, "AI_WeightedTardinessScore"], 40)

    def test_setup_savings_improve_objective_when_higher_goals_tie(self):
        src = _source(self.now, [5])
        jobs, _ = core.build_jobs(
            src, core.WorkCalendar(src.calendar, self.now), self.now)
        jobs[0].ai_start = jobs[0].orig_start
        jobs[0].ai_tislutdat = jobs[0].orig_tislutdat
        without_saving = core.plan_objective(jobs)
        jobs[0].setup_saved = 2
        with_saving = core.plan_objective(jobs)
        self.assertLess(with_saving, without_saving)

    def test_sql_result_rows_include_customer_policy_and_weighted_scores(self):
        src = _source(self.now, [5])
        src.customer_config = pd.DataFrame([
            {"OrderNumber": 200001, "Customer": "Volvo", "Vikt": 10, "MaxLate": 5},
        ])
        policy = core.ClusterPolicy()
        jobs, _ = core.build_jobs(
            src, core.WorkCalendar(src.calendar, self.now), self.now,
            max_tardiness_days=policy.global_max_tardiness_days)
        jobs[0].ai_tislutdat = jobs[0].ord_ber_lev_dat + pd.Timedelta(days=3)
        row = sql_sink_v7.jobs_to_rows(jobs, "run-id", self.now,
                                      policy=policy)[0]
        data = dict(zip(sql_sink_v7.RESULT_COLUMNS, row))
        self.assertEqual(data["CustomerNumbers"], "Volvo")
        self.assertEqual(data["CustomerWeight"], 10)
        self.assertEqual(data["AI_TardinessScore"], 4)
        self.assertEqual(data["AI_WeightedTardinessScore"], 40)


if __name__ == "__main__":
    unittest.main()