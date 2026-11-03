"""Focused tests for V8 SQL connection and guarded procedure behavior."""

from __future__ import annotations

import json
import os
import queue
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "service"))

import config_v8
import db_v8
import omplanering_app_v8 as app
import sql_refresh_v8


class FakeCursor:
    def __init__(self):
        self.calls = []
        self.closed = False
        self.messages = []

    def execute(self, command, *parameters):
        self.calls.append((command, parameters))
        return self

    def nextset(self):
        return False

    def close(self):
        self.closed = True


class FakeConnection:
    def __init__(self):
        self.current_cursor = FakeCursor()
        self.committed = False
        self.rolled_back = False
        self.timeout = 300

    def cursor(self):
        return self.current_cursor

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


class V8SqlTests(unittest.TestCase):
    def test_connection_string_binds_runtime_password(self):
        with (
            patch.object(config_v8, "SERVER_NAME", "sql-host"),
            patch.object(config_v8, "DATABASE", "planning"),
            patch.object(config_v8, "USERNAME", "planner"),
        ):
            value = db_v8.connection_string("p;ass}word")

        self.assertIn("UID={planner};", value)
        self.assertIn("PWD={p;ass}}word};", value)
        self.assertNotIn("p;ass}word;", value)

    def test_user_config_has_no_password_field(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "connection.json")
            with (
                patch.object(config_v8, "APP_DIR", directory),
                patch.object(config_v8, "CONNECTION_CONFIG_PATH", path),
            ):
                values = config_v8.load_connection_config()
                with open(path, encoding="utf-8") as stream:
                    saved = stream.read()

        self.assertEqual(values, config_v8.DEFAULT_CONFIG)
        self.assertEqual(json.loads(saved), config_v8.DEFAULT_CONFIG)
        self.assertEqual(values["server_name"], "tcp:AHO-APP12,1433")
        self.assertEqual(values["database"], "BIzparc_Direct_VMO_AI")
        self.assertEqual(values["username"], "imad01")
        self.assertEqual(values["odbc_driver"], "ODBC Driver 18 for SQL Server")
        self.assertEqual(values["encrypt"], "yes")
        self.assertEqual(values["trust_server_certificate"], "yes")
        self.assertEqual(values["query_timeout"], 300)
        self.assertEqual(values["refresh_timeout"], 0)
        self.assertEqual(values["refresh_procedure"], "dbo.sp_Fill_All_Tables")
        self.assertNotIn("password", {key.lower() for key in values})
        self.assertNotIn("password", saved.lower())

    def test_existing_connection_config_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "connection.json")
            existing = {
                **config_v8.DEFAULT_CONFIG,
                "server_name": "tcp:synthetic-server,1444",
                "username": "synthetic-login",
                "trust_server_certificate": "no",
                "query_timeout": 900,
                "refresh_procedure": "",
            }
            original = json.dumps(existing, indent=2)
            with open(path, "w", encoding="utf-8") as stream:
                stream.write(original)
            with (
                patch.object(config_v8, "APP_DIR", directory),
                patch.object(config_v8, "CONNECTION_CONFIG_PATH", path),
            ):
                self.assertEqual(config_v8.load_connection_config(), existing)
                with open(path, encoding="utf-8") as stream:
                    self.assertEqual(stream.read(), original)

    def test_refresh_procedure_binds_values_and_commits(self):
        connection = FakeConnection()
        with (
            patch.object(config_v8, "REFRESH_PROCEDURE", "dbo.RefreshPlanning"),
            patch.object(config_v8, "REFRESH_PARAMETERS", [
                {"name": "BatchId", "value": "sample;value"},
            ]),
        ):
            sql_refresh_v8.run_refresh_procedure(connection)

        command, parameters = connection.current_cursor.calls[0]
        self.assertEqual(command, "EXEC [dbo].[RefreshPlanning] @BatchId = ?")
        self.assertEqual(parameters, ("sample;value",))
        self.assertTrue(connection.committed)
        self.assertFalse(connection.rolled_back)
        self.assertTrue(connection.current_cursor.closed)

    def test_refresh_rejects_unqualified_or_injected_procedure(self):
        connection = FakeConnection()
        with (
            patch.object(config_v8, "REFRESH_PROCEDURE", "dbo.Refresh; DROP TABLE x"),
            patch.object(config_v8, "REFRESH_PARAMETERS", []),
        ):
            with self.assertRaises(ValueError):
                sql_refresh_v8.run_refresh_procedure(connection)

        self.assertEqual(connection.current_cursor.calls, [])
        self.assertFalse(connection.committed)

    def test_refresh_logs_messages_from_execute_and_nextset(self):
        connection = FakeConnection()
        cursor = connection.current_cursor
        def execute(*_args):
            cursor.messages = [("01000", "Synthetic refresh started")]
        def nextset():
            cursor.messages = [("01000", "Synthetic refresh finished")]
            return False
        cursor.execute = execute
        cursor.nextset = nextset
        log = Mock()
        phase = Mock()
        with (
            patch.object(config_v8, "REFRESH_PROCEDURE", "dbo.RefreshPlanning"),
            patch.object(config_v8, "REFRESH_PARAMETERS", []),
            patch.object(config_v8, "REFRESH_TIMEOUT", 0),
        ):
            sql_refresh_v8.run_refresh_procedure(connection, log, phase)
        text = "\n".join(call.args[0] for call in log.call_args_list)
        self.assertIn("Synthetic refresh started", text)
        self.assertIn("Synthetic refresh finished", text)
        self.assertIn("ingen tidsgräns", text)
        self.assertEqual(len(phase.call_args_list), 2)
        self.assertTrue(connection.committed)

    def test_refresh_timeout_rolls_back_and_logs_available_messages(self):
        connection = FakeConnection()
        cursor = connection.current_cursor
        def execute(*_args):
            cursor.messages = [("01000", "Synthetic last completed step")]
            raise TimeoutError("HYT00", "Query timeout expired")
        cursor.execute = execute
        log = Mock()
        phase = Mock()
        with (
            patch.object(config_v8, "REFRESH_PROCEDURE", "dbo.RefreshPlanning"),
            patch.object(config_v8, "REFRESH_PARAMETERS", []),
        ):
            with self.assertRaises(TimeoutError):
                sql_refresh_v8.run_refresh_procedure(connection, log, phase)
        self.assertTrue(connection.rolled_back)
        self.assertFalse(connection.committed)
        self.assertTrue(cursor.closed)
        self.assertIn("rollback", phase.call_args.args[0])
        text = "\n".join(call.args[0] for call in log.call_args_list)
        self.assertIn("Synthetic last completed step", text)
        self.assertNotIn("committades", text)

    def test_sql_progress_shows_elapsed_time_and_timeout_without_percentage(self):
        stub = SimpleNamespace(
            _sql_busy="refresh", _sql_started_at=100.0,
            _sql_phase="Kör dbo.RefreshPlanning – väntar på SQL Server",
            lbl_sql_status=Mock(),
        )
        with patch.object(app.time, "monotonic", return_value=165.0):
            app.App._update_sql_progress(stub)
        text = stub.lbl_sql_status.configure.call_args.kwargs["text"]
        self.assertIn("01:05", text)
        self.assertIn("tidsgräns", text)
        self.assertNotIn("%", text)
        stub._sql_busy = None
        stub.lbl_sql_status.reset_mock()
        app.App._update_sql_progress(stub)
        stub.lbl_sql_status.configure.assert_not_called()

    def test_refresh_ui_starts_progress_and_invalidates_snapshot(self):
        stub = SimpleNamespace(
            worker=None, _sql_password="synthetic-session",
            _sql_identity=("synthetic-server", "synthetic-db"),
            _sql_source=object(), _pending_outcome=object(),
            _pending_started=datetime(2026, 1, 1),
            _sql_worker=Mock(), _log=Mock(), _update_sql_progress=Mock(),
            btn_connect_sql=Mock(), btn_refresh_sql=Mock(), btn_load_sql=Mock(),
            btn_run=Mock(), btn_write_sql=Mock(), btn_sql_config=Mock(),
            btn_cancel_refresh=Mock(),
            progress=Mock(), sql_progress=Mock(), nb=Mock(), var_status=Mock(),
        )
        with patch.object(app.threading, "Thread"):
            app.App._start_sql_worker(stub, "refresh")
        self.assertEqual(stub._sql_busy, "refresh")
        self.assertIsNone(stub._sql_source)
        self.assertIsNone(stub._pending_outcome)
        stub.sql_progress.start.assert_called_once()
        stub.btn_sql_config.configure.assert_called_with(state="disabled")
        stub.btn_cancel_refresh.configure.assert_called_with(state="normal")
        stub._update_sql_progress.assert_called_once()

    def test_refresh_timeout_ui_stops_progress_and_reports_unconfirmed_outcome(self):
        stub = SimpleNamespace(
            queue=queue.Queue(), _sql_busy="refresh", _sql_password="synthetic-session",
            _pending_outcome=None, _log=Mock(), after=Mock(), _pump=Mock(),
            _update_sql_progress=Mock(), progress=Mock(), sql_progress=Mock(),
            btn_connect_sql=Mock(), btn_refresh_sql=Mock(), btn_load_sql=Mock(),
            btn_run=Mock(), btn_write_sql=Mock(), btn_sql_config=Mock(),
            btn_cancel_refresh=Mock(),
            lbl_sql_status=Mock(), var_status=Mock(),
        )
        stub.queue.put(("sql_error", (
            "refresh", TimeoutError("HYT00", "Query timeout expired"), "synthetic trace")))
        with patch.object(app.messagebox, "showerror") as error:
            app.App._pump(stub)
        self.assertIsNone(stub._sql_busy)
        stub.sql_progress.stop.assert_called_once()
        stub.sql_progress.pack_forget.assert_called_once()
        self.assertIn("timeout", stub.lbl_sql_status.configure.call_args.kwargs["text"])
        self.assertIn("sidoeffekter", error.call_args.args[1])
        self.assertIn("refresh_timeout", error.call_args.args[1])
        stub.btn_write_sql.configure.assert_called_with(state="disabled")
        stub.btn_cancel_refresh.configure.assert_called_with(state="disabled")

    def test_ui_parameters_round_trip_without_password(self):
        class FakeVar:
            def __init__(self, value=""):
                self.value = value

            def get(self):
                return self.value

            def set(self, value):
                self.value = value

        stub = SimpleNamespace(
            var_input=FakeVar("planning.xlsx"),
            var_output=FakeVar("output"),
            var_window=FakeVar("25"),
            var_lock_horizon=FakeVar("2,5"),
            var_max_tardiness=FakeVar("10"),
            score_band_vars=[
                [FakeVar(str(lower)), FakeVar("" if upper is None else str(upper)),
                 FakeVar(str(score))]
                for lower, upper, score in app.core.DEFAULT_TARDINESS_SCORE_BANDS
            ],
        )
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "settings.json")
            with (
                patch.object(app, "SETTINGS_FILE", path),
                patch.object(app.tk, "StringVar", FakeVar),
                patch.object(app.messagebox, "showwarning"),
            ):
                app.App._save_settings(stub)
                app.App._load_settings(stub)
                with open(path, encoding="utf-8") as stream:
                    saved = stream.read().lower()

        self.assertEqual(stub.var_lock_horizon.get(), "2.5")
        self.assertEqual(stub.var_window.get(), "25")
        self.assertNotIn("password", saved)

    def test_sql_result_write_requires_explicit_confirmation(self):
        stub = SimpleNamespace(
            _pending_outcome=object(),
            _pending_started=datetime(2026, 1, 1),
            _sql_password="session-only",
            _start_sql_worker=Mock(),
        )
        with patch.object(app.messagebox, "askyesno", return_value=False):
            app.App._write_sql_result(stub)
        stub._start_sql_worker.assert_not_called()

    def test_sql_worker_rejects_changed_server_or_database(self):
        connection = SimpleNamespace(close=Mock())
        stub = SimpleNamespace(queue=queue.Queue())
        with (
            patch.object(app.sql_db, "connect", return_value=connection),
            patch.object(app.sql_db, "server_identity",
                         return_value=("new-server", "new-database")),
            patch.object(app.sql_source, "load_source_sql") as load_source,
        ):
            app.App._sql_worker(
                stub, "load", "session-only", None, None,
                ("configured-server", "configured-database"))

        event, payload = stub.queue.get_nowait()
        self.assertEqual(event, "sql_error")
        self.assertEqual(payload[0], "load")
        self.assertIn("har ändrats", str(payload[1]))
        load_source.assert_not_called()
        connection.close.assert_called_once()


class FakeVar:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


USER_LADDER = [
    ["-4", "0", "1.0"], ["1", "2", "2.0"], ["3", "4", "4.0"],
    ["5", "7", "9.0"], ["8", "9", "10.0"], ["10", "20000", "20.0"],
    ["-99", "-5", "20.0"],
]


def _ladder_stub(rows):
    return SimpleNamespace(
        score_band_vars=[[FakeVar(value) for value in row] for row in rows],
        _render_score_bands=Mock())


class V8RefreshTimeoutTests(unittest.TestCase):
    def test_refresh_timeout_is_applied_before_cursor_and_restored(self):
        connection = FakeConnection()
        seen = []
        original_cursor = connection.cursor
        def cursor():
            seen.append(connection.timeout)
            return original_cursor()
        connection.cursor = cursor
        with (
            patch.object(config_v8, "REFRESH_PROCEDURE", "dbo.RefreshPlanning"),
            patch.object(config_v8, "REFRESH_PARAMETERS", []),
            patch.object(config_v8, "REFRESH_TIMEOUT", 0),
        ):
            sql_refresh_v8.run_refresh_procedure(connection)
        self.assertEqual(seen, [0])
        self.assertEqual(connection.timeout, 300)
        self.assertTrue(connection.committed)

    def test_cancelled_refresh_rolls_back_and_releases_cursor(self):
        connection = FakeConnection()
        cursor = connection.current_cursor
        def execute(*_args):
            raise RuntimeError("HY008", "Operation canceled")
        cursor.execute = execute
        cursors = []
        with (
            patch.object(config_v8, "REFRESH_PROCEDURE", "dbo.RefreshPlanning"),
            patch.object(config_v8, "REFRESH_PARAMETERS", []),
            patch.object(config_v8, "REFRESH_TIMEOUT", 0),
        ):
            with self.assertRaises(RuntimeError):
                sql_refresh_v8.run_refresh_procedure(
                    connection, on_cursor=cursors.append)
        self.assertEqual(cursors, [cursor, None])
        self.assertTrue(connection.rolled_back)
        self.assertFalse(connection.committed)
        self.assertEqual(connection.timeout, 300)

    def test_config_validates_refresh_timeout(self):
        for bad in (-1, True, "0", 1.5):
            with tempfile.TemporaryDirectory() as directory:
                path = os.path.join(directory, "connection.json")
                with open(path, "w", encoding="utf-8") as stream:
                    json.dump({"refresh_timeout": bad}, stream)
                with (
                    patch.object(config_v8, "APP_DIR", directory),
                    patch.object(config_v8, "CONNECTION_CONFIG_PATH", path),
                ):
                    with self.assertRaises(ValueError, msg=repr(bad)):
                        config_v8.load_connection_config()

    def test_existing_config_without_refresh_timeout_waits_for_sql(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "connection.json")
            legacy = {key: value for key, value in config_v8.DEFAULT_CONFIG.items()
                      if key != "refresh_timeout"}
            with open(path, "w", encoding="utf-8") as stream:
                json.dump(legacy, stream)
            with (
                patch.object(config_v8, "APP_DIR", directory),
                patch.object(config_v8, "CONNECTION_CONFIG_PATH", path),
            ):
                self.assertEqual(config_v8.load_connection_config()["refresh_timeout"], 0)

    def test_cancel_button_requests_sql_cancel(self):
        cursor = Mock()
        stub = SimpleNamespace(
            _sql_busy="refresh", _refresh_cursor=cursor,
            _refresh_cancel_requested=False, btn_cancel_refresh=Mock(),
            _sql_phase="", _log=Mock())
        with patch.object(app.messagebox, "askyesno", return_value=True):
            app.App._cancel_refresh(stub)
        cursor.cancel.assert_called_once()
        self.assertTrue(stub._refresh_cancel_requested)
        stub.btn_cancel_refresh.configure.assert_called_with(state="disabled")

    def test_cancelled_refresh_is_reported_as_user_cancel(self):
        stub = SimpleNamespace(
            queue=queue.Queue(), _sql_busy="refresh", _sql_password="synthetic-session",
            _refresh_cancel_requested=True, _refresh_cursor=object(),
            _pending_outcome=None, _log=Mock(), after=Mock(), _pump=Mock(),
            _update_sql_progress=Mock(), progress=Mock(), sql_progress=Mock(),
            btn_connect_sql=Mock(), btn_refresh_sql=Mock(), btn_load_sql=Mock(),
            btn_run=Mock(), btn_write_sql=Mock(), btn_sql_config=Mock(),
            btn_cancel_refresh=Mock(), lbl_sql_status=Mock(), var_status=Mock(),
        )
        stub.queue.put(("sql_error", (
            "refresh", RuntimeError("HY008", "Operation canceled"), "trace")))
        with patch.object(app.messagebox, "showerror") as error:
            app.App._pump(stub)
        self.assertEqual(error.call_args.args[0], "Procedur avbruten")
        self.assertIn("avbröts av dig", error.call_args.args[1])
        self.assertFalse(stub._refresh_cancel_requested)
        self.assertIsNone(stub._refresh_cursor)


class V8ScoreLadderTests(unittest.TestCase):
    def test_validation_names_the_misplaced_row(self):
        with self.assertRaises(ValueError) as caught:
            app.core.validate_tardiness_score_bands(USER_LADDER)
        self.assertIn("Rad 7", str(caught.exception))

    def test_early_row_with_lower_score_is_valid(self):
        bands = app.core.validate_tardiness_score_bands(
            [[-99, -5, 0.5], [-4, 0, 0], [1, None, 2]])
        self.assertEqual(bands[0], (-99, -5, 0.5))

    def test_early_row_scoring_as_much_as_tardiness_is_rejected(self):
        with self.assertRaises(ValueError) as caught:
            app.core.validate_tardiness_score_bands(
                [[-99, -5, 2], [-4, 0, 0], [1, None, 2]])
        self.assertIn("Rad 1", str(caught.exception))
        self.assertIn("tidighetsraden", str(caught.exception))

    def test_early_days_use_signed_ladder(self):
        bands = app.core.validate_tardiness_score_bands(
            [[-30, -10, 0.5], [-9, 0, 0], [1, 2, 2], [3, None, 4]])
        score = app.core.tardiness_score
        self.assertEqual(score(-12.0, bands), 0.5)
        self.assertEqual(score(-200.0, bands), 0.5)
        self.assertEqual(score(-9.6, bands), 0)
        self.assertEqual(score(0.2, bands), 2)
        self.assertEqual(score(3.0, bands), 4)

    def test_ladder_starting_at_zero_keeps_early_orders_at_day_zero(self):
        bands = app.core.validate_tardiness_score_bands([[0, 0, 1], [1, None, 3]])
        self.assertEqual(app.core.tardiness_score(-15.0, bands), 1)
        self.assertEqual(
            app.core.score_days_between(datetime(2026, 5, 10), datetime(2026, 5, 7)), -3.0)

    def test_objective_penalizes_finishing_too_early(self):
        policy = app.core.ClusterPolicy(
            score_bands=[[-99, -10, 0.5], [-9, 0, 0], [1, None, 2]])
        due = datetime(2026, 5, 20)

        def job(finish):
            return SimpleNamespace(
                ord_ber_lev_dat=due, ai_tislutdat=finish, movable=True,
                customer_weight=1.0, permitted_tardiness_days=lambda: 10.0,
                status_for=lambda _: "Grön", setup_saved=0.0, rerouted_from=None,
                orig_start=None, ai_start=None)

        very_early = app.core.plan_objective([job(due - timedelta(days=20))], policy)
        on_time = app.core.plan_objective([job(due - timedelta(days=1))], policy)
        self.assertEqual(very_early[4], 0.5)
        self.assertEqual(on_time[4], 0)
        self.assertLess(on_time, very_early)

    def test_sort_and_fix_keeps_early_rows_and_reports_too_high_score(self):
        stub = _ladder_stub(USER_LADDER)
        with (
            patch.object(app.tk, "StringVar", FakeVar),
            patch.object(app.messagebox, "showinfo") as info,
            patch.object(app.messagebox, "showwarning") as warning,
        ):
            app.App._sort_score_bands(stub)
        info.assert_not_called()
        self.assertIn("tidighetsraden", warning.call_args.args[1])
        rows = [[value.get() for value in row] for row in stub.score_band_vars]
        self.assertEqual(rows[0], ["-99", "-5", "20.0"])
        self.assertEqual(rows[-1], ["10", "", "20.0"])
        self.assertEqual(len(rows), 7)
        rows[0][2] = "0.5"
        app.core.validate_tardiness_score_bands(rows)

    def test_sort_reports_remaining_gap_with_row_number(self):
        stub = _ladder_stub([["3", "", "4"], ["0", "1", "1"]])
        with (
            patch.object(app.tk, "StringVar", FakeVar),
            patch.object(app.messagebox, "showwarning") as warning,
        ):
            app.App._sort_score_bands(stub)
        self.assertIn("Rad 2", warning.call_args.args[1])

    def test_move_row_up_and_down(self):
        stub = _ladder_stub([["0", "1", "1"], ["2", "", "2"]])
        first = stub.score_band_vars[0]
        app.App._move_score_band(stub, 0, 1)
        self.assertIs(stub.score_band_vars[1], first)
        app.App._move_score_band(stub, 1, 1)
        self.assertIs(stub.score_band_vars[1], first)
        app.App._move_score_band(stub, 1, -1)
        self.assertIs(stub.score_band_vars[0], first)

    def test_invalid_ladder_keeps_saved_ladder_but_saves_other_fields(self):
        stub = SimpleNamespace(
            var_input=FakeVar("a.xlsx"), var_output=FakeVar("out"),
            var_window=FakeVar("12"), var_lock_horizon=FakeVar("4"),
            var_max_tardiness=FakeVar("10"),
            score_band_vars=[[FakeVar(value) for value in row]
                             for row in [["0", "", "1"]]],
            var_settings_status=FakeVar(""),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "settings.json")
            with patch.object(app, "SETTINGS_FILE", path):
                self.assertTrue(app.App._save_settings(stub))
                stub.score_band_vars = [[FakeVar(value) for value in row]
                                        for row in USER_LADDER]
                stub.var_window.set("20")
                with patch.object(app.messagebox, "showwarning") as warning:
                    self.assertFalse(app.App._save_settings(stub))
                with open(path, encoding="utf-8") as stream:
                    saved = json.load(stream)
        self.assertEqual(saved["window_days"], 20)
        self.assertEqual(saved["score_bands"], [[0, None, 1.0]])
        self.assertIn("Poängtrappa", warning.call_args.args[1])
        self.assertIn("Delvis", stub.var_settings_status.get())


if __name__ == "__main__":
    unittest.main()
