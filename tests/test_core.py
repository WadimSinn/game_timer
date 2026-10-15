import json
import gc
import sqlite3
import tempfile
import time
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest import mock

from autostart_manager import AutostartManager
from hotkey_manager import HotkeyManager
from process_manager import ProcessManager
from settings_manager import SettingsManager
from timer_manager import TimerManager
from achievement_manager import AchievementManager
from game_timer import GameTimerApp
import game_timer


class DictSettings:
    def __init__(self, values):
        self.values = values

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value
        return True


class SettingsManagerTests(unittest.TestCase):
    def test_changes_are_persisted_immediately_and_atomically(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "settings.json"
            settings = SettingsManager(str(path))

            settings.set("custom_value", {"enabled": True})
            settings.set("another_value", 42)

            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["custom_value"], {"enabled": True})
            self.assertEqual(saved["another_value"], 42)
            self.assertEqual(list(Path(temp_dir).glob(".settings-*.tmp")), [])

    def test_legacy_settings_merge_without_overwriting_current_settings(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "settings.json"
            legacy_path = Path(temp_dir) / "timer_settings.json"
            legacy_path.write_text(
                json.dumps({
                    "hours": 1,
                    "processes": ["OldGame.exe", "game.exe"],
                    "presets": {"Legacy preset": {"hours": 0, "minutes": 20}},
                    "hotkeys": {"pause": "ctrl+space"},
                }),
                encoding="utf-8",
            )

            settings = SettingsManager(str(path))

            self.assertEqual(settings.get("hours"), 2)
            self.assertIn("OldGame.exe", settings.get("processes"))
            self.assertEqual(
                sum(
                    item.casefold() == "game.exe"
                    for item in settings.get("processes")
                ),
                1,
            )
            self.assertIn("Legacy preset", settings.get("presets"))
            self.assertEqual(
                settings.get("hotkeys")["pause"], "ctrl+space"
            )
            self.assertTrue(Path(str(path) + ".legacy-migrated").exists())

            legacy_path.write_text(
                json.dumps({"processes": ["LaterGame.exe"]}),
                encoding="utf-8",
            )
            settings.load()
            self.assertNotIn("LaterGame.exe", settings.get("processes"))
            self.assertTrue(legacy_path.exists())

    def test_frozen_install_imports_legacy_config_next_to_executable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            install_dir = Path(temp_dir) / "install"
            data_dir = Path(temp_dir) / "appdata" / "GameTimer"
            install_dir.mkdir()
            data_dir.mkdir(parents=True)
            legacy_path = install_dir / "timer_settings.json"
            legacy_path.write_text(
                json.dumps({"processes": ["InstalledGame.exe"]}),
                encoding="utf-8",
            )
            settings_path = data_dir / "settings.json"
            settings_path.write_text(
                json.dumps({"processes": ["CurrentGame.exe"]}),
                encoding="utf-8",
            )

            with (
                mock.patch("settings_manager.get_data_path", return_value=str(settings_path)),
                mock.patch("settings_manager.sys.frozen", True, create=True),
                mock.patch(
                    "settings_manager.sys.executable",
                    str(install_dir / "GameTimer.exe"),
                ),
            ):
                settings = SettingsManager()

            self.assertEqual(
                settings.get("processes"),
                ["CurrentGame.exe", "InstalledGame.exe"],
            )
            self.assertTrue(
                Path(str(settings_path) + ".legacy-migrated").exists()
            )
            self.assertTrue(legacy_path.exists())


class HotkeyManagerTests(unittest.TestCase):
    def test_legacy_pause_key_registers_as_pause_resume(self):
        manager = HotkeyManager()
        callback = lambda: None

        with mock.patch.object(manager, "add_hotkey") as add_hotkey:
            manager.register_from_settings(
                {"hotkeys": {"pause": "ctrl+space"}},
                {"pause_resume": callback},
            )

        add_hotkey.assert_called_once_with("ctrl+space", callback)
        self.assertEqual(
            manager.get_named_hotkeys(), {"pause_resume": "ctrl+space"}
        )


class AutostartManagerTests(unittest.TestCase):
    def test_source_autostart_command_quotes_python_and_script_paths(self):
        manager = AutostartManager()
        key = mock.MagicMock()

        with (
            mock.patch(
                "autostart_manager.winreg.CreateKeyEx"
            ) as create_key,
            mock.patch(
                "autostart_manager.winreg.SetValueEx"
            ) as set_value,
            mock.patch("autostart_manager.sys.executable", r"C:\Program Files\Python\python.exe"),
            mock.patch("autostart_manager.sys.argv", [r"C:\Game Timer\game_timer.py"]),
            mock.patch("autostart_manager.sys.frozen", False, create=True),
            mock.patch("autostart_manager.os.path.isfile", return_value=True),
        ):
            create_key.return_value.__enter__.return_value = key

            self.assertTrue(manager.set_autostart(True))

        self.assertEqual(
            set_value.call_args.args[-1],
            '"C:\\Program Files\\Python\\pythonw.exe" "C:\\Game Timer\\game_timer.py"',
        )

    def test_disabling_missing_autostart_entry_is_successful(self):
        manager = AutostartManager()
        key = mock.MagicMock()

        with (
            mock.patch("autostart_manager.winreg.CreateKeyEx") as create_key,
            mock.patch(
                "autostart_manager.winreg.DeleteValue",
                side_effect=FileNotFoundError,
            ),
        ):
            create_key.return_value.__enter__.return_value = key

            self.assertTrue(manager.set_autostart(False))


class ProcessManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "usage.db")
        self.settings = DictSettings({
            "usage_db_path": self.db_path,
            "process_check_interval_ms": 1000,
            "processes": ["game.exe"],
        })
        self.manager = ProcessManager(self.settings)

    def tearDown(self):
        self.manager.flush_pending_usage()
        del self.manager
        gc.collect()
        self.temp_dir.cleanup()

    def test_monitored_processes_can_be_added_and_removed_case_insensitively(self):
        self.assertTrue(self.manager.add_process_to_monitor(" minecraft.exe "))
        self.assertFalse(self.manager.add_process_to_monitor("MINECRAFT.exe"))
        self.assertTrue(self.manager.remove_process_from_monitor("Minecraft.EXE"))
        self.assertEqual(self.settings.get("processes"), ["game.exe"])

    def test_running_monitored_processes_include_fallback_matches(self):
        self.manager.get_active_processes = mock.Mock(return_value=[])
        self.manager.is_process_running = mock.Mock(
            side_effect=lambda name: name.lower() == "game.exe"
        )

        self.assertEqual(
            self.manager.get_running_monitored_processes(), ["game.exe"]
        )

    def test_forced_process_scan_bypasses_recent_cache(self):
        self.manager._cache = {"oldgame.exe": {"pid": 1}}
        self.manager._cache_time = time.time()
        current_game = type(
            "Process", (), {"info": {"name": "game.exe"}, "pid": 2}
        )()
        with mock.patch(
            "process_manager.psutil.process_iter",
            return_value=[current_game],
        ):
            self.assertEqual(
                self.manager.get_active_processes(force_refresh=True),
                ["game.exe"],
            )

    def test_close_request_targets_visible_monitored_game_windows(self):
        fake_user32 = mock.Mock()
        fake_user32.IsWindowVisible.return_value = True
        fake_user32.PostMessageW.return_value = True

        def enumerate_windows(callback, _lparam):
            callback(123, 0)
            return True

        fake_user32.EnumWindows.side_effect = enumerate_windows

        def get_window_process(_hwnd, process_id):
            process_id._obj.value = 456
            return 1

        fake_user32.GetWindowThreadProcessId.side_effect = get_window_process
        with (
            mock.patch("process_manager.os.name", "nt"),
            mock.patch("process_manager.ctypes.WinDLL", return_value=fake_user32),
            mock.patch(
                "process_manager.psutil.Process"
            ) as process,
        ):
            process.return_value.name.return_value = "game.exe"
            self.assertEqual(
                self.manager.close_monitored_game_windows(), 1
            )

        fake_user32.PostMessageW.assert_called_once_with(123, 0x0010, 0, 0)

    def test_parallel_processes_count_once_toward_daily_total(self):
        self.manager.record_active_processes(
            ["game.exe", "launcher.exe"], duration=7
        )
        self.manager.record_active_processes(
            ["game.exe", "launcher.exe"], duration=7
        )

        self.assertEqual(self.manager.get_daily_usage(date.today()), 14)
        self.assertEqual(self.manager.get_weekly_usage(date.today()), 14)
        self.assertEqual(
            self.manager.get_usage_by_process(date.today()),
            {"game.exe": 14, "launcher.exe": 14},
        )
        self.manager.flush_pending_usage()
        self.assertEqual(self.manager.get_daily_usage(date.today()), 14)

    def test_reset_discards_buffered_and_persisted_usage(self):
        self.manager.record_active_processes(["game.exe"], duration=8)
        self.manager.flush_pending_usage()
        self.manager.record_active_processes(["game.exe"], duration=5)

        self.manager.reset_usage_data()

        self.assertEqual(self.manager.get_daily_usage(date.today()), 0)
        self.assertEqual(self.manager.get_usage_by_process(date.today()), {})

    def test_legacy_database_is_migrated_without_losing_usage(self):
        with sqlite3.connect(self.db_path) as connection:
            connection.execute("DROP TABLE usage_stats")
            connection.execute("""
                CREATE TABLE usage_stats (
                    timestamp TEXT,
                    process_name TEXT,
                    duration INTEGER,
                    PRIMARY KEY (timestamp, process_name)
                )
            """)
            connection.execute(
                "INSERT INTO usage_stats VALUES (?, ?, ?)",
                (f"{date.today().isoformat()} 12:00:00", "game.exe", 13),
            )
        connection.close()

        manager = ProcessManager(self.settings)

        self.assertEqual(manager.get_daily_usage(date.today()), 13)
        connection = sqlite3.connect(self.db_path)
        try:
            columns = {row[1] for row in connection.execute(
                "PRAGMA table_info(usage_stats)"
            )}
        finally:
            connection.close()
        self.assertIn("id", columns)


class AchievementManagerTests(unittest.TestCase):
    def test_new_manager_does_not_reuse_another_users_in_memory_progress(self):
        first = AchievementManager(DictSettings({}))
        first.update_achievement("first_timer")
        second = AchievementManager(DictSettings({}))

        self.assertFalse(second.achievements["first_timer"].completed)
        self.assertEqual(second.achievements["first_timer"].progress, 0)


class TimerManagerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt6 import QtCore
        cls.application = QtCore.QCoreApplication.instance() or QtCore.QCoreApplication([])

    def setUp(self):
        from PyQt6 import QtCore

        class UI:
            class Display:
                def setText(self, text):
                    self.text = text

            class Button:
                def setEnabled(self, enabled):
                    self.enabled = enabled

                def setText(self, text):
                    self.text = text

            time_display = Display()
            start_button = Button()
            pause_button = Button()
            reset_button = Button()

        class Blocker:
            def update_timer_state(self, expired):
                self.expired = expired

        self.ui = UI()
        self.blocker = Blocker()
        self.manager = TimerManager(
            QtCore.QObject(), self.blocker, self.ui, DictSettings({})
        )

    def tearDown(self):
        self.manager.reset_timer()

    def test_zero_countdown_is_rejected(self):
        self.assertFalse(self.manager.start_timer(0, "countdown"))
        self.assertFalse(self.manager.is_running())

    def test_countdown_expiration_is_handled_at_zero(self):
        import time

        self.assertTrue(self.manager.start_timer(2, "countdown"))
        self.manager._countdown_deadline = time.monotonic() - 0.1
        self.manager.update_timer()

        self.assertTrue(self.manager.is_expired())
        self.assertEqual(self.manager.remaining_time, 0)
        self.assertEqual(self.ui.time_display.text, "00:00:00")
        self.assertTrue(self.blocker.expired)

    def test_reset_updates_display_to_zero(self):
        self.manager.start_timer(90, "countdown")
        self.manager.reset_timer()

        self.assertEqual(self.ui.time_display.text, "00:00:00")


class AutoCountupMonitorTests(unittest.TestCase):
    def run_monitor(self, manual_start):
        class ProcessManager:
            def is_any_monitored_process_running(self, force_refresh=False):
                return False

        class TimerManager:
            paused = False

            def is_running(self):
                return True

            def get_mode(self):
                return "countup"

            def is_expired(self):
                return False

            def pause_timer(self):
                self.paused = True

        app = type("AppState", (), {})()
        app.process_manager = ProcessManager()
        app.timer_manager = TimerManager()
        app.manual_start = manual_start
        app._expire_grace_used = False
        app._block_dismissed_until_game_exit = False
        app.logger = mock.Mock()
        app.game_blocker = mock.Mock()
        app.game_blocker.unblock.return_value = False
        app._hide_countdown_overlay = mock.Mock()
        app._cancel_game_warning = lambda: GameTimerApp._cancel_game_warning(app)
        app._start_grace_period = mock.Mock()

        GameTimerApp._autocountup_monitor(app)
        return app.timer_manager.paused

    def test_manual_countup_is_not_paused_without_a_detected_game(self):
        self.assertFalse(self.run_monitor(manual_start=True))

    def test_auto_countup_pauses_when_game_closes(self):
        self.assertTrue(self.run_monitor(manual_start=False))


class PlaySessionLimitTests(unittest.TestCase):
    def make_app(self, settings_values=None, play_seconds=0, in_rest=False):
        app = type("AppState", (), {})()
        app.settings = DictSettings({
            "enforce_play_session_limit": True,
            "play_session_limit_hours": 2,
            "enforced_rest_minutes": 60,
            **(settings_values or {}),
        })
        app._play_since_rest_seconds = play_seconds
        app._session_progress_dirty = False
        app._last_session_progress_save_ts = time.monotonic()
        app.is_in_rest = lambda: in_rest
        app.logger = mock.Mock()
        app._parent_extension_seconds_today = lambda field="daily_seconds": 0
        app._persist_play_since_rest = lambda: GameTimerApp._persist_play_since_rest(app)
        def start_rest(minutes):
            app.rest_minutes_started = minutes
            GameTimerApp._reset_play_since_rest(app)
        app.start_rest = start_rest
        return app

    def test_counts_running_gameplay_and_saves_progress(self):
        app = self.make_app(play_seconds=120)
        GameTimerApp._account_play_session(app, {"game.exe"}, 30)

        self.assertEqual(app._play_since_rest_seconds, 150)
        self.assertTrue(app._session_progress_dirty)
        GameTimerApp._persist_play_since_rest(app)
        self.assertEqual(
            app.settings.get("play_since_rest_seconds"), 150
        )
        self.assertFalse(app._session_progress_dirty)

    def test_two_hour_limit_starts_sixty_minute_rest_and_resets_counter(self):
        app = self.make_app(play_seconds=7190)
        GameTimerApp._account_play_session(app, {"game.exe"}, 10)

        self.assertEqual(app.rest_minutes_started, 60)
        self.assertEqual(app._play_since_rest_seconds, 0)
        self.assertEqual(app.settings.get("play_since_rest_seconds"), 0)

    def test_does_not_accumulate_during_rest_or_without_a_running_game(self):
        during_rest = self.make_app(play_seconds=120, in_rest=True)
        GameTimerApp._account_play_session(during_rest, {"game.exe"}, 30)
        without_game = self.make_app(play_seconds=120)
        GameTimerApp._account_play_session(without_game, set(), 30)

        self.assertEqual(during_rest._play_since_rest_seconds, 120)
        self.assertEqual(without_game._play_since_rest_seconds, 120)

    def test_session_limit_can_be_disabled(self):
        app = self.make_app(
            {"enforce_play_session_limit": False},
            play_seconds=7190,
        )
        GameTimerApp._account_play_session(app, {"game.exe"}, 30)

        self.assertEqual(app._play_since_rest_seconds, 7190)
        self.assertFalse(hasattr(app, "rest_minutes_started"))

    def test_daily_limit_can_be_configured_per_weekday(self):
        app = type("AppState", (), {})()
        app.settings = DictSettings({
            "daily_limits_by_weekday": {"0": 2.5, "5": 6},
            "daily_limit_hours": 4,
        })
        app.logger = mock.Mock()

        self.assertEqual(GameTimerApp._daily_limit_hours_for_weekday(app, 0), 2.5)
        self.assertEqual(GameTimerApp._daily_limit_hours_for_weekday(app, 5), 6)
        self.assertEqual(GameTimerApp._daily_limit_hours_for_weekday(app, 2), 4)

    def test_zero_daily_limit_is_preserved(self):
        app = type("AppState", (), {})()
        app.settings = DictSettings({
            "daily_limits_by_weekday": {"1": 0},
            "daily_limit_hours": 6,
        })
        app.logger = mock.Mock()

        self.assertEqual(GameTimerApp._daily_limit_hours_for_weekday(app, 1), 0)

    def test_play_session_progress_shows_elapsed_and_rest_state(self):
        app = type("AppState", (), {})()
        app.settings = DictSettings({
            "enforce_play_session_limit": True,
            "play_session_limit_hours": 2,
        })
        app._play_since_rest_seconds = 4800
        app.is_in_rest = lambda: False
        app._format_duration = GameTimerApp._format_duration
        app.gui_manager = mock.Mock()
        app.gui_manager.play_session_progress_label = mock.Mock()
        app.gui_manager.play_session_progress_bar = mock.Mock()

        GameTimerApp.update_play_session_progress(app)

        app.gui_manager.play_session_progress_label.setText.assert_called_once_with(
            "До перерыва: 1 ч 20 мин из 2 ч 00 мин"
        )
        app.gui_manager.play_session_progress_bar.setValue.assert_called_once_with(
            666
        )

    def test_zero_limit_adjustment_stays_zero(self):
        app = type("AppState", (), {})()
        app.settings = DictSettings({
            "daily_limits_by_weekday": {str(day): 0 for day in range(7)}
        })
        app.logger = mock.Mock()
        app._daily_limit_hours_for_weekday = (
            lambda weekday: GameTimerApp._daily_limit_hours_for_weekday(app, weekday)
        )
        app._daily_limit_seconds_for_today = lambda: 0
        app.gui_manager = mock.Mock()
        app.update_stats = mock.Mock()

        GameTimerApp._adjust_today_daily_limit(app, -600)

        self.assertEqual(
            app.settings.get("daily_limits_by_weekday")[
                str(datetime.now().weekday())
            ],
            0,
        )

    def test_limit_warning_is_sent_once_and_requests_saving_game(self):
        app = type("AppState", (), {})()
        app.settings = DictSettings({
            "limit_warning_seconds": 300,
            "enforce_play_session_limit": True,
            "play_session_limit_hours": 1,
        })
        app._play_since_rest_seconds = 3500
        app._session_limit_warning_shown = False
        app._daily_limit_warning_date = None
        app._active_limit_warning_text = None
        app.daily_limit_seconds = 36000
        app.tray_manager = mock.Mock()
        app.logger = mock.Mock()
        app._parent_extension_seconds_today = lambda field: 0

        GameTimerApp._check_limit_warnings(app, today_used=0)
        GameTimerApp._check_limit_warnings(app, today_used=0)

        app.tray_manager.show_message.assert_called_once()
        self.assertIn("Сохрани игру", app._active_limit_warning_text)

    def test_daily_limit_warning_is_sent_once(self):
        app = type("AppState", (), {})()
        app.settings = DictSettings({
            "limit_warning_seconds": 300,
            "enforce_play_session_limit": False,
            "block_until_next_day_on_limit": True,
        })
        app._daily_limit_warning_date = None
        app._active_limit_warning_text = None
        app.daily_limit_seconds = 3600
        app.tray_manager = mock.Mock()
        app.logger = mock.Mock()
        app._parent_extension_seconds_today = lambda field="daily_seconds": 0

        GameTimerApp._check_limit_warnings(app, today_used=3500)
        GameTimerApp._check_limit_warnings(app, today_used=3500)

        app.tray_manager.show_message.assert_called_once()
        self.assertIn("Сохрани игру", app._active_limit_warning_text)

    def test_parent_extension_adds_time_and_clears_active_rest(self):
        app = type("AppState", (), {})()
        app.settings = DictSettings({
            "daily_limits_by_weekday": {
                str(day): 2 for day in range(7)
            },
            "parent_extension": {"date": "", "daily_seconds": 0, "session_seconds": 0},
        })
        app._parent_extension_seconds_today = lambda field="daily_seconds": (
            GameTimerApp._parent_extension_seconds_today(app, field)
        )
        app._daily_limit_hours_for_weekday = lambda weekday: 2
        app._daily_limit_seconds_for_today = lambda: (
            7200 + GameTimerApp._parent_extension_seconds_today(app)
        )
        app.rest_until = datetime.now() + timedelta(minutes=30)
        app.rest_reason = "cooldown"
        app.is_in_rest = lambda: app.rest_until is not None
        app.settings.set("rest_until", app.rest_until.isoformat())
        app.game_blocker = mock.Mock()
        app._block_dismissed_until_game_exit = True
        app._session_limit_warning_shown = True
        app._active_limit_warning_text = "warning"
        app.daily_limit_seconds = 7200
        app.timer_manager = mock.Mock()
        app.timer_manager.is_expired.return_value = False
        app.update_stats = mock.Mock()
        app.tray_manager = mock.Mock()
        app.logger = mock.Mock()

        self.assertTrue(GameTimerApp.grant_parent_extension(app, 30))

        extension = app.settings.get("parent_extension")
        self.assertEqual(extension["daily_seconds"], 1800)
        self.assertEqual(extension["session_seconds"], 1800)
        self.assertIsNone(app.rest_until)
        self.assertEqual(app.settings.get("rest_until"), "")
        self.assertFalse(app._block_dismissed_until_game_exit)
        self.assertFalse(app._session_limit_warning_shown)
        self.assertIsNone(app._active_limit_warning_text)
        app.game_blocker.unblock.assert_called_once_with()
        app.update_stats.assert_called_once_with()

    def test_session_extension_is_cleared_after_next_rest(self):
        app = self.make_app({
            "parent_extension": {
                "date": date.today().isoformat(),
                "daily_seconds": 1800,
                "session_seconds": 1800,
            }
        })

        GameTimerApp._reset_play_since_rest(app)

        self.assertEqual(
            app.settings.get("parent_extension")["daily_seconds"], 1800
        )
        self.assertEqual(
            app.settings.get("parent_extension")["session_seconds"], 0
        )

    def test_usage_is_counted_only_for_foreground_monitored_game(self):
        app = type("AppState", (), {})()
        app.settings = DictSettings({"periodic_tasks_interval_ms": 1000})
        app._last_usage_account_ts = time.monotonic() - 1.2
        app.process_manager = mock.Mock()
        app.process_manager.get_active_processes.return_value = [
            "game.exe", "browser.exe"
        ]
        app.process_manager.get_monitored_processes.return_value = ["game.exe"]
        app.process_manager.get_foreground_process_name.return_value = "game.exe"
        app.logger = mock.Mock()
        app._account_play_session = mock.Mock()

        GameTimerApp._account_active_usage(app)

        app.process_manager.record_active_processes.assert_called_once_with(
            {"game.exe"}, 1
        )
        app._account_play_session.assert_called_once_with({"game.exe"}, 1)

    def test_background_game_is_not_counted(self):
        app = type("AppState", (), {})()
        app.settings = DictSettings({"periodic_tasks_interval_ms": 1000})
        app._last_usage_account_ts = time.monotonic() - 1.2
        app.process_manager = mock.Mock()
        app.process_manager.get_active_processes.return_value = ["game.exe"]
        app.process_manager.get_monitored_processes.return_value = ["game.exe"]
        app.process_manager.get_foreground_process_name.return_value = "desktop.exe"
        app.logger = mock.Mock()

        GameTimerApp._account_active_usage(app)

        app.process_manager.record_active_processes.assert_not_called()


class BlockingRecoveryTests(unittest.TestCase):
    def test_parent_hotkey_dismissal_is_latched_until_game_exit(self):
        app = type("AppState", (), {})()
        app.game_blocker = mock.Mock()
        app.game_blocker.unblock.return_value = True
        app._block_dismissed_until_game_exit = False

        GameTimerApp._unblock_and_suppress_until_game_exit(app)

        app.game_blocker.unblock.assert_called_once_with()
        self.assertTrue(app._block_dismissed_until_game_exit)

    def test_closing_game_stops_grace_countdown_and_unblocks(self):
        app = type("AppState", (), {})()
        app.process_manager = mock.Mock(
            is_any_monitored_process_running=mock.Mock(return_value=False)
        )
        app.timer_manager = mock.Mock(
            is_running=mock.Mock(return_value=False),
            get_mode=mock.Mock(return_value="countdown"),
        )
        app.manual_start = False
        app._expire_grace_used = True
        app._block_dismissed_until_game_exit = True
        app.logger = mock.Mock()
        app.game_blocker = mock.Mock()
        app.game_blocker.unblock.return_value = True
        app._hide_countdown_overlay = mock.Mock()
        app._cancel_game_warning = lambda: GameTimerApp._cancel_game_warning(app)
        app.post_notification_timer = mock.Mock()
        app.post_notification_timer.isActive.return_value = True
        app.notification_window = mock.Mock()
        app.notification_window.isVisible.return_value = True
        app.notification_shown = True

        GameTimerApp._autocountup_monitor(app)

        app.post_notification_timer.stop.assert_called_once_with()
        app.notification_window.accept.assert_called_once_with()
        app._hide_countdown_overlay.assert_called_once_with()
        app.game_blocker.unblock.assert_called_once_with()
        self.assertFalse(hasattr(app, "notification_shown"))
        self.assertFalse(app._expire_grace_used)
        self.assertFalse(app._block_dismissed_until_game_exit)

    def test_hotkey_dismissal_does_not_reopen_block_for_same_game(self):
        app = type("AppState", (), {})()
        app.process_manager = mock.Mock(
            is_any_monitored_process_running=mock.Mock(return_value=True)
        )
        app.timer_manager = mock.Mock(
            is_running=mock.Mock(return_value=False),
            get_mode=mock.Mock(return_value="countdown"),
            is_expired=mock.Mock(return_value=True),
        )
        app._block_dismissed_until_game_exit = True
        app._expire_grace_used = True
        app.game_blocker = mock.Mock()
        app.logger = mock.Mock()

        GameTimerApp._autocountup_monitor(app)

        app.game_blocker.start_blocking_sequence.assert_not_called()

    def test_block_screen_uses_main_event_loop_not_nested_exec(self):
        from game_blocker import GameBlocker

        screen = mock.Mock()
        screen.isVisible.return_value = False
        with (
            mock.patch("game_blocker.Logger"),
            mock.patch("game_blocker.BlockScreen", return_value=screen),
        ):
            blocker = GameBlocker(DictSettings({"block_delay": 3}))
            blocker.start_blocking_sequence()

        screen.show.assert_called_once_with()
        screen.exec.assert_not_called()
        screen.raise_.assert_called_once_with()
        screen.activateWindow.assert_called_once_with()

    def test_block_screen_receives_graceful_game_close_callback(self):
        from game_blocker import GameBlocker

        screen = mock.Mock()
        screen.isVisible.return_value = False
        close_game_callback = mock.Mock(return_value=1)
        with (
            mock.patch("game_blocker.Logger"),
            mock.patch("game_blocker.BlockScreen", return_value=screen) as block_screen,
        ):
            blocker = GameBlocker(
                DictSettings({"block_delay": 3}), close_game_callback
            )
            blocker.start_blocking_sequence()

        self.assertIs(
            block_screen.call_args.kwargs["close_game_callback"],
            close_game_callback,
        )


class ExpirationFlowTests(unittest.TestCase):
    def test_expired_timer_notifies_and_starts_grace_period(self):
        app = type("AppState", (), {})()
        app.process_manager = mock.Mock(
            is_any_monitored_process_running=mock.Mock(return_value=True)
        )
        app.timer_manager = mock.Mock(
            is_running=mock.Mock(return_value=False),
            get_mode=mock.Mock(return_value="countdown"),
            is_expired=mock.Mock(return_value=True),
        )
        app._expire_grace_used = False
        app._block_dismissed_until_game_exit = False
        app._hide_countdown_overlay = mock.Mock()
        app._start_grace_period = mock.Mock()
        app._on_notification_closed = mock.Mock()
        app.achievement_manager = mock.Mock()
        app.logger = mock.Mock()

        with mock.patch.object(game_timer, "NotificationWindow") as notification:
            GameTimerApp._autocountup_monitor(app)

        notification.return_value.show.assert_called_once_with(duration=0)
        app.achievement_manager.on_notification_shown.assert_called_once_with()
        app._start_grace_period.assert_called_once_with()
        self.assertTrue(app.notification_shown)

    def test_game_still_running_after_grace_starts_blocking_sequence(self):
        app = type("AppState", (), {})()
        app.process_manager = mock.Mock(
            is_any_monitored_process_running=mock.Mock(return_value=True)
        )
        app.settings = DictSettings({
            "enforce_cooldown_between_sessions": True,
            "enforced_rest_minutes": 60,
        })
        app.game_blocker = mock.Mock()
        app.achievement_manager = mock.Mock()
        app.logger = mock.Mock()
        app._hide_countdown_overlay = mock.Mock()
        app.start_rest = mock.Mock()
        app.notification_shown = True

        GameTimerApp._check_game_after_notification(app)

        app.game_blocker.update_timer_state.assert_called_once_with(True)
        app.game_blocker.start_blocking_sequence.assert_called_once_with()
        app.achievement_manager.on_forced_block.assert_called_once_with()
        app.start_rest.assert_called_once_with(60)
        self.assertTrue(app._expire_grace_used)
        self.assertFalse(hasattr(app, "notification_shown"))


if __name__ == "__main__":
    unittest.main()
