"""
Файл: process_manager.py

Модуль для мониторинга и учёта времени, проведённого в отслеживаемых процессах (играх) в приложении Game Timer.
"""

import psutil
import logging
import ctypes
from ctypes import wintypes
from datetime import datetime, timedelta
import sqlite3
import time
from contextlib import contextmanager
import os
from app_paths import get_data_path

class ProcessManager:
    def __init__(self, settings):
        self.settings = settings
        self.logger = logging.getLogger('ProcessManager')
        self._cache = {}
        self._cache_time = 0
        # Время жизни кэша берём из настроек проверки процессов (в секундах)
        self._cache_lifetime = max(1, int(self.settings.get('process_check_interval_ms', 5000) / 1000))
        self._usage_db = (
            settings.get("usage_db_path") or get_data_path("usage_stats.db")
        )
        self._last_cleanup = time.time()
        self._cleanup_interval = 3600
        self._write_buffer = []
        self._buffer_size = 100
        self._last_flush = time.time()
        self._flush_interval = 300
        self._monitored_set = None  # кэш множества целевых процессов (lowercase)
        self._init_db()

    def _init_db(self):
        """Инициализация базы данных для статистики"""
        try:
            with self._connection() as conn:
                columns = conn.execute(
                    "PRAGMA table_info(usage_stats)"
                ).fetchall()
                if columns and not any(column[1] == "id" for column in columns):
                    conn.execute("DROP INDEX IF EXISTS idx_process_time")
                    conn.execute("ALTER TABLE usage_stats RENAME TO usage_stats_legacy")
                    columns = []
                if not columns:
                    conn.execute('''
                        CREATE TABLE IF NOT EXISTS usage_stats (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            timestamp TEXT NOT NULL,
                            process_name TEXT NOT NULL,
                            duration INTEGER NOT NULL
                        )
                    ''')
                    legacy = conn.execute(
                        "SELECT name FROM sqlite_master "
                        "WHERE type = 'table' AND name = 'usage_stats_legacy'"
                    ).fetchone()
                    if legacy:
                        conn.execute('''
                            INSERT INTO usage_stats (timestamp, process_name, duration)
                            SELECT timestamp, process_name, duration FROM usage_stats_legacy
                        ''')
                        conn.execute("DROP TABLE usage_stats_legacy")
                conn.execute('''
                    CREATE INDEX IF NOT EXISTS idx_process_time 
                    ON usage_stats(process_name, timestamp)
                ''')
            self.logger.info("Database initialized successfully")
        except sqlite3.Error as e:
            self.logger.error(f"Database initialization error: {e}")
            raise

    @contextmanager
    def _connection(self):
        connection = sqlite3.connect(self._usage_db)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def get_monitored_processes(self):
        """Возвращает список отслеживаемых процессов из настроек"""
        return self.settings.get("processes", [])

    def get_running_monitored_processes(self):
        """Returns configured process names that currently match a running process."""
        active = set(self.get_active_processes())
        running = []
        seen = set()
        for configured_name in self.get_monitored_processes() or []:
            if not isinstance(configured_name, str) or not configured_name.strip():
                continue
            name = configured_name.strip()
            executable = os.path.basename(name).lower()
            if executable in seen:
                continue
            if executable in active or self.is_process_running(name):
                running.append(name)
                seen.add(executable)
        return running

    def _get_monitored_set(self):
        """Возвращает множество имён процессов в lowercase для быстрого сравнения."""
        procs = self.settings.get("processes", []) or []
        try:
            return set(p.strip().lower() for p in procs if p and isinstance(p, str))
        except Exception:
            return set()

    def get_active_processes(self, force_refresh=False):
        """Получение списка активных процессов с кэшированием"""
        current_time = time.time()
        if (
            not force_refresh
            and current_time - self._cache_time <= self._cache_lifetime
        ):
            return list(self._cache.keys())
        try:
            new_cache = {}
            for proc in psutil.process_iter(['name']):
                try:
                    proc_name = proc.info['name']
                    if proc_name:
                        new_cache[proc_name.lower()] = {
                            'pid': proc.pid,
                            'last_update': current_time
                        }
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    continue
            self._cache = new_cache
            self._cache_time = current_time
            if current_time - self._last_cleanup >= self._cleanup_interval:
                self.cleanup_old_data()
                self._last_cleanup = current_time
            return list(self._cache.keys())
        except Exception as e:
            self.logger.error(f"Error getting active processes: {e}")
            return list(self._cache.keys()) if self._cache else []

    def get_foreground_process_name(self):
        """Returns the executable name for the process owning the foreground window."""
        if os.name != "nt":
            return None
        try:
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            user32.GetForegroundWindow.restype = wintypes.HWND
            user32.GetWindowThreadProcessId.argtypes = (
                wintypes.HWND,
                ctypes.POINTER(wintypes.DWORD),
            )
            user32.GetWindowThreadProcessId.restype = wintypes.DWORD
            hwnd = user32.GetForegroundWindow()
            if not hwnd:
                return None
            process_id = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
            if not process_id.value:
                return None
            return psutil.Process(process_id.value).name().lower()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            return None
        except Exception as e:
            self.logger.error(f"Error getting foreground process: {e}")
            return None

    def close_monitored_game_windows(self):
        """Sends WM_CLOSE to visible top-level windows of monitored game processes."""
        if os.name != "nt":
            return 0

        monitored = {
            os.path.basename(name.strip()).casefold()
            for name in (self.get_monitored_processes() or [])
            if isinstance(name, str) and name.strip()
        }
        if not monitored:
            return 0

        try:
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            window_proc_type = ctypes.WINFUNCTYPE(
                wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
            )
            user32.EnumWindows.argtypes = (
                window_proc_type, wintypes.LPARAM
            )
            user32.EnumWindows.restype = wintypes.BOOL
            user32.IsWindowVisible.argtypes = (wintypes.HWND,)
            user32.IsWindowVisible.restype = wintypes.BOOL
            user32.GetWindowThreadProcessId.argtypes = (
                wintypes.HWND,
                ctypes.POINTER(wintypes.DWORD),
            )
            user32.GetWindowThreadProcessId.restype = wintypes.DWORD
            user32.PostMessageW.argtypes = (
                wintypes.HWND,
                wintypes.UINT,
                wintypes.WPARAM,
                wintypes.LPARAM,
            )
            user32.PostMessageW.restype = wintypes.BOOL

            closed_requests = 0

            def close_matching_window(hwnd, _lparam):
                nonlocal closed_requests
                if not user32.IsWindowVisible(hwnd):
                    return True

                process_id = wintypes.DWORD()
                user32.GetWindowThreadProcessId(
                    hwnd, ctypes.byref(process_id)
                )
                if not process_id.value:
                    return True
                try:
                    process_name = psutil.Process(
                        process_id.value
                    ).name().casefold()
                except (
                    psutil.NoSuchProcess,
                    psutil.AccessDenied,
                    psutil.ZombieProcess,
                ):
                    return True
                if process_name in monitored and user32.PostMessageW(
                    hwnd, 0x0010, 0, 0
                ):
                    closed_requests += 1
                return True

            callback = window_proc_type(close_matching_window)
            user32.EnumWindows(callback, 0)
            return closed_requests
        except Exception as e:
            self.logger.error(f"Error requesting monitored games to close: {e}")
            return None

    def add_process_to_monitor(self, process_name):
        """Adds a process name to monitoring settings, ignoring duplicates."""
        name = (process_name or "").strip()
        processes = list(self.get_monitored_processes() or [])
        if not name or any(
            item.lower() == name.lower()
            for item in processes
            if isinstance(item, str)
        ):
            return False
        processes.append(name)
        self.settings.set("processes", processes)
        self._cache_time = 0
        return True

    def remove_process_from_monitor(self, process_name):
        """Removes a monitored process by case-insensitive name."""
        name = (process_name or "").strip().lower()
        processes = list(self.get_monitored_processes() or [])
        remaining = [
            item for item in processes
            if not isinstance(item, str) or item.strip().lower() != name
        ]
        if len(remaining) == len(processes):
            return False
        self.settings.set("processes", remaining)
        self._cache_time = 0
        return True

    def log_usage(self, process_name, duration):
        """Логирование использования процесса с буферизацией"""
        duration = int(duration)
        if not process_name or duration <= 0:
            return
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        self._write_buffer.append((timestamp, process_name, duration))
        self._flush_buffer()

    def record_active_processes(self, process_names, duration):
        """Records per-process usage and total play time once per sample."""
        names = {
            name.strip().lower()
            for name in process_names
            if isinstance(name, str) and name.strip()
        }
        if not names or int(duration) <= 0:
            return
        for name in sorted(names):
            self.log_usage(name, duration)
        self.log_usage("__total__", duration)

    def get_daily_usage(self, date=None):
        """Возвращает суммарное время использования всех отслеживаемых процессов за день (секунды)"""
        if date is None:
            date = datetime.now().date()
        else:
            date = datetime.strptime(date, '%Y-%m-%d').date() if isinstance(date, str) else date
        total = 0
        try:
            with self._connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT timestamp, process_name, duration
                    FROM usage_stats WHERE date(timestamp) = ?
                    ORDER BY timestamp
                ''', (date.strftime('%Y-%m-%d'),))
                rows = cursor.fetchall()
            rows.extend(
                (ts, name, duration)
                for ts, name, duration in self._write_buffer
                if ts[:10] == date.strftime('%Y-%m-%d')
            )
            first_total = min(
                (ts for ts, name, _ in rows if name == "__total__"),
                default=None
            )
            total = sum(
                duration for ts, name, duration in rows
                if name == "__total__"
                or (first_total is None or ts < first_total)
                and name != "__total__"
            )
        except Exception as e:
            self.logger.error(f"Error getting daily usage: {e}")
        return total

    def get_weekly_usage(self, start_date=None):
        """Возвращает суммарное время использования всех отслеживаемых процессов за неделю (секунды)"""
        if start_date is None:
            today = datetime.now().date()
            start_date = today - timedelta(days=today.weekday())
        else:
            start_date = datetime.strptime(start_date, '%Y-%m-%d').date() if isinstance(start_date, str) else start_date
        end_date = start_date + timedelta(days=7)
        total = 0
        try:
            with self._connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT timestamp, process_name, duration
                    FROM usage_stats
                    WHERE date(timestamp) >= ? AND date(timestamp) < ?
                    ORDER BY timestamp
                ''', (start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d')))
                rows = cursor.fetchall()
            rows.extend(
                (ts, name, duration)
                for ts, name, duration in self._write_buffer
                if start_date <= datetime.strptime(ts, '%Y-%m-%d %H:%M:%S').date() < end_date
            )
            totals_by_date = {}
            for ts, name, duration in rows:
                totals_by_date.setdefault(ts[:10], []).append((ts, name, duration))
            for day_rows in totals_by_date.values():
                first_total = min(
                    (ts for ts, name, _ in day_rows if name == "__total__"),
                    default=None
                )
                total += sum(
                    duration for ts, name, duration in day_rows
                    if name == "__total__"
                    or (first_total is None or ts < first_total)
                    and name != "__total__"
                )
        except Exception as e:
            self.logger.error(f"Error getting weekly usage: {e}")
        return total

    def _flush_buffer(self, force=False):
        """Записывает буферизированные данные в БД"""
        current_time = time.time()
        if not force and len(self._write_buffer) < self._buffer_size and \
           current_time - self._last_flush < self._flush_interval:
            return
        if not self._write_buffer:
            return
        try:
            with self._connection() as conn:
                cursor = conn.cursor()
                cursor.executemany(
                    'INSERT OR REPLACE INTO usage_stats (timestamp, process_name, duration) VALUES (?, ?, ?)',
                    self._write_buffer
                )
                conn.commit()
            self.logger.debug(f"Flushed {len(self._write_buffer)} records to database")
            self._write_buffer.clear()
            self._last_flush = current_time
        except sqlite3.Error as e:
            self.logger.error(f"Error flushing buffer to database: {e}")

    # --- Aggregations for per-game details ---
    def get_usage_by_process(self, date=None):
        """Возвращает словарь {process_name: seconds} за указанный день (по умолчанию сегодня)."""
        if date is None:
            date = datetime.now().date()
        else:
            date = datetime.strptime(date, '%Y-%m-%d').date() if isinstance(date, str) else date
        result = {}
        try:
            with self._connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT process_name, SUM(duration) as total
                    FROM usage_stats
                    WHERE date(timestamp) = ? AND process_name != '__total__'
                    GROUP BY process_name
                ''', (date.strftime('%Y-%m-%d'),))
                for name, total in cursor.fetchall():
                    result[name] = int(total or 0)
            target_date = date.strftime('%Y-%m-%d')
            for timestamp, name, duration in self._write_buffer:
                if timestamp[:10] == target_date and name != "__total__":
                    result[name] = result.get(name, 0) + duration
        except Exception as e:
            self.logger.error(f"Error getting usage by process: {e}")
        return result

    def get_usage_by_process_range(self, start_date, end_date=None):
        """Возвращает словарь {process_name: seconds} за период [start_date, end_date).
        Если end_date не указан, берется start_date + 7 дней.
        Принимает даты как date или 'YYYY-MM-DD'.
        """
        if isinstance(start_date, str):
            start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
        if end_date is None:
            end_date = start_date + timedelta(days=7)
        elif isinstance(end_date, str):
            end_date = datetime.strptime(end_date, '%Y-%m-%d').date()
        result = {}
        try:
            with self._connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT process_name, SUM(duration) as total
                    FROM usage_stats
                    WHERE date(timestamp) >= ? AND date(timestamp) < ?
                      AND process_name != '__total__'
                    GROUP BY process_name
                ''', (start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d')))
                for name, total in cursor.fetchall():
                    result[name] = int(total or 0)
            for timestamp, name, duration in self._write_buffer:
                record_date = datetime.strptime(
                    timestamp, '%Y-%m-%d %H:%M:%S'
                ).date()
                if start_date <= record_date < end_date and name != "__total__":
                    result[name] = result.get(name, 0) + duration
        except Exception as e:
            self.logger.error(f"Error getting usage by process range: {e}")
        return result

    def get_last_seen_and_sessions(self, start_date=None, end_date=None, gap_minutes=15):
        """Эвристически вычисляет последнее появление и число сессий по процессам за период.
        Сессия считается прерванной, если между соседними записями > gap_minutes.
        Возвращает словарь: {proc: {last_seen: 'YYYY-MM-DD HH:MM:SS', sessions: int}}
        """
        if start_date is None:
            start_date = datetime.now().date()
        if isinstance(start_date, str):
            start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
        if end_date is None:
            end_date = start_date + timedelta(days=1)
        if isinstance(end_date, str):
            end_date = datetime.strptime(end_date, '%Y-%m-%d').date()
        info = {}
        try:
            with self._connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT process_name, timestamp
                    FROM usage_stats
                    WHERE date(timestamp) >= ? AND date(timestamp) < ?
                      AND process_name != '__total__'
                    ORDER BY process_name, timestamp
                ''', (start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d')))
                rows = cursor.fetchall()
            rows.extend(
                (name, timestamp)
                for timestamp, name, _ in self._write_buffer
                if start_date.strftime('%Y-%m-%d')
                <= timestamp[:10]
                < end_date.strftime('%Y-%m-%d')
                and name != "__total__"
            )
            from collections import defaultdict
            grouped = defaultdict(list)
            for name, ts in rows:
                grouped[name].append(datetime.strptime(ts, '%Y-%m-%d %H:%M:%S'))
            for name, times in grouped.items():
                sessions = 0
                prev = None
                for t in times:
                    if prev is None or (t - prev).total_seconds() > gap_minutes * 60:
                        sessions += 1
                    prev = t
                info[name] = {
                    'last_seen': times[-1].strftime('%Y-%m-%d %H:%M:%S') if times else None,
                    'sessions': sessions
                }
        except Exception as e:
            self.logger.error(f"Error computing last_seen/sessions: {e}")
        return info

    def cleanup_old_data(self):
        """Очистка старых данных из БД"""
        try:
            cutoff_date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
            with self._connection() as conn:
                cursor = conn.cursor()
                cursor.execute('DELETE FROM usage_stats WHERE date(timestamp) < ?', (cutoff_date,))
                conn.commit()
            self.logger.info("Old data cleaned up")
        except sqlite3.Error as e:
            self.logger.error(f"Error cleaning up old data: {e}")

    def flush_pending_usage(self):
        """Writes any buffered usage records before application shutdown."""
        self._flush_buffer(force=True)

    def reset_usage_data(self):
        """Discards buffered records and recreates the usage database."""
        self._write_buffer.clear()
        if os.path.exists(self._usage_db):
            os.remove(self._usage_db)
        self._cache_time = 0
        self._init_db()

    def is_any_monitored_process_running(self, force_refresh=False):
        """Проверяет, запущен ли хотя бы один из отслеживаемых процессов (быстро через пересечение множеств)."""
        monitored = self._get_monitored_set()
        if not monitored:
            return False
        active = set(self.get_active_processes(force_refresh=force_refresh))
        if active & monitored:
            return True
        # Если прямого совпадения по имени нет, делаем более дорогую проверку по путям (редкий случай)
        for name in monitored:
            if self.is_process_running(name):
                return True
        return False


    def is_process_running(self, process_name):
        """Проверяет, запущен ли указанный процесс. Сначала по кэшу имён, затем (если нужно) по путям."""
        process_lower = os.path.basename((process_name or "").strip()).lower()
        if not process_lower:
            return False
        # Быстрая проверка по кэшу имён
        if process_lower in self._cache:
            return True
        # Медленная проверка по путям
        for proc in psutil.process_iter(['name', 'exe']):
            try:
                proc_info = proc.info
                if not proc_info:
                    continue
                name = (proc_info.get('name') or '').lower()
                exe = (proc_info.get('exe') or '').lower()
                if process_lower == name or (
                    exe and process_lower == os.path.basename(exe).lower()
                ):
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
        return False
