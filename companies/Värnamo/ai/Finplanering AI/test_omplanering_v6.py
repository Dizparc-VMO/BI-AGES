import json
import os
import queue
import tempfile
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pandas as pd

import omplanering_app_v6 as app
import omplanering_core_v6 as core
import test_omplanering_v5 as v5_tests


class V6RegressionTests(v5_tests.V5CoreTests):
    """Run the existing safety tests against the independent V6 engine."""

    def setUp(self):
        replacement = patch.object(v5_tests, "core", core)
        replacement.start()
        self.addCleanup(replacement.stop)

    def test_excel_run_writes_v5_named_outputs(self):
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
                self.assertIn("_v6_resultat_", os.path.basename(path))
                self.assertTrue(os.path.isfile(path))
            self.assertEqual(result.stats["lock_horizon_hours"], 8)
            self.assertEqual(result.stats["frozen_lock_horizon"], 2)
            self.assertEqual(dict(result.summary)["Låshorisont (timmar)"], 8)
            summary = pd.read_excel(result.xlsx_path, sheet_name=core.SHEET_SUMMARY,
                                    header=None)
            self.assertEqual(summary.loc[
                summary[0] == "Låshorisont (timmar)", 1].iloc[0], 8)
            self.assertTrue(any("låshorisont 8 h" in line for line in result.log_lines))


class V6HorizonTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 8, 6)

    def jobs(self, offsets, hours=4):
        src = v5_tests._source(self.now, offsets)
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
        src = v5_tests._source(self.now, [1])
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
        src = v5_tests._source(self.now, [3, 5, 7])
        for hours, count in ((8, 3), (0, 0), (4, 1)):
            outcome = core.compute_plan(src, now=self.now, lock_horizon_hours=hours)
            self.assertEqual(outcome.stats["frozen_lock_horizon"], count)
            self.assertEqual(outcome.stats["lock_horizon_hours"], hours)
        default = core.compute_plan(src, now=self.now)
        self.assertEqual(default.stats["lock_horizon_hours"], 4)
        self.assertEqual(default.stats["frozen_lock_horizon"], 1)
        self.assertEqual(core.LOCK_HORIZON_HOURS, 4)


class V6UiTests(unittest.TestCase):
    def settings_stub(self):
        return SimpleNamespace(
            var_input=Mock(get=Mock(return_value="input.xlsx")),
            var_output=Mock(get=Mock(return_value="output")),
            var_window=Mock(get=Mock(return_value="30")),
            var_lock_horizon=Mock(get=Mock(return_value="2,5")),
        )

    def test_settings_round_trip_and_invalid_fallback(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            settings_path = os.path.join(tmpdir, "settings.json")
            with patch.object(app, "SETTINGS_FILE", settings_path):
                stub = self.settings_stub()
                app.App._save_settings(stub)
                app.App._load_settings(stub)
                stub.var_lock_horizon.set.assert_called_with("2.5")
                with open(settings_path, encoding="utf-8") as fh:
                    self.assertEqual(json.load(fh)["lock_horizon_hours"], 2.5)
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


if __name__ == "__main__":
    unittest.main()