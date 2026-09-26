# -*- coding: utf-8 -*-
"""Тести Drag & Drop імпорту логів.

Вимога: зона Drag & Drop повинна використовувати ТОЙ САМИЙ механізм
імпорту, що й кнопка «Завантажити файл вручну»; непідтримувані файли та
папки не мають ламати програму; перетягнутий файл має бути доступний для
аналізу без зміни типу аналізу.
"""
import importlib.util
import os
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

APP_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "app", "iphone_panic_diagnostics.py",
)

_spec = importlib.util.spec_from_file_location("iphone_panic_diagnostics", APP_PATH)
MODULE = importlib.util.module_from_spec(_spec)
sys.modules["iphone_panic_diagnostics"] = MODULE
_spec.loader.exec_module(MODULE)

from PyQt6.QtWidgets import QApplication, QFileDialog, QMessageBox  # noqa: E402

# Мінімальний справжній panic-full зразок (обробляється як panic-full).
PANIC_LOG = (
    '{"bug_type":"210","timestamp":"2026-09-11 13:29:26.00 +0300",'
    '"os_version":"iPhone OS 18.7.7 (22H340)"}\n'
    '{ "product" : "iPhone14,5", "build" : "iPhone OS 18.7.7 (22H340)",'
    '"panicString" : "panic(cpu 0 caller 0xfffffff049bb6db8): '
    '\\"_enableHalogen:4104 Unknown sample rate on DAC\\" '
    '@AppleCS42L77Audio.cpp:4104\\\\nDebugger message: panic\\\\n",'
    '"panicFlags" : "0x802" }\n'
)


class TestDragDropImport(unittest.TestCase):
    """Кнопка та Drag & Drop — один спільний механізм імпорту."""

    @classmethod
    def setUpClass(cls):
        cls._app_owned = False
        cls._app = QApplication.instance()
        if cls._app is None:
            cls._app = QApplication([])
            cls._app_owned = True

    @classmethod
    def tearDownClass(cls):
        if cls._app_owned:
            cls._app.quit()

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.panic_path = os.path.join(self._tmp.name, "panic-full-test.ips")
        with open(self.panic_path, "w", encoding="utf-8") as f:
            f.write(PANIC_LOG)

        # Не запускаємо фонових потоків і не показуємо реальних діалогів.
        patchers = [
            mock.patch.object(MODULE.MainWindow, "_start_worker",
                              lambda self, mode, silent=False: None),
            mock.patch.object(QMessageBox, "information", return_value=None),
            mock.patch.object(QMessageBox, "warning", return_value=None),
            mock.patch.object(QMessageBox, "critical", return_value=None),
        ]
        for p in patchers:
            p.start()
            self.addCleanup(p.stop)
        self.window = MODULE.MainWindow()

    def tearDown(self):
        self.window.close()
        self._tmp.cleanup()

    def test_button_import_adds_log_and_analyzes(self):
        with mock.patch.object(QFileDialog, "getOpenFileName",
                               return_value=(self.panic_path, "")):
            self.window._on_load_file_clicked()
        self.assertEqual(len(self.window.loaded_logs), 1)
        self.assertEqual(self.window.loaded_logs[0]["name"], "panic-full-test.ips")
        self.assertEqual(self.window.logs_list.count(), 1)
        self.assertIsNotNone(self.window.current_report)
        self.assertTrue(self.window.current_report.is_panic_source)
        self.assertEqual(self.window.current_report.source_type, "panic-full")

    def test_drop_and_button_use_same_import_method(self):
        """Обидва шляхи викликають рівно один спільний _import_log_file."""
        with mock.patch.object(MODULE.MainWindow, "_import_log_file",
                               autospec=True) as imp:
            with mock.patch.object(QFileDialog, "getOpenFileName",
                                   return_value=(self.panic_path, "")):
                self.window._on_load_file_clicked()
            self.window._on_files_dropped([self.panic_path])
            self.assertEqual(imp.call_count, 2)
            for call in imp.call_args_list:
                # autospec: виклик приходить з (self, path)
                self.assertEqual(call.args[1], self.panic_path)

    def test_dropped_file_available_for_analysis(self):
        self.window._on_files_dropped([self.panic_path])
        self.assertEqual(len(self.window.loaded_logs), 1)
        self.assertEqual(self.window.logs_list.count(), 1)
        self.assertEqual(self.window.loaded_logs[0]["name"], "panic-full-test.ips")
        # Той самий аналіз, що й для кнопки: panic-full.
        self.assertIsNotNone(self.window.current_report)
        self.assertTrue(self.window.current_report.is_panic_source)
        self.assertEqual(self.window.current_report.source_type, "panic-full")

    def test_drop_unsupported_file_does_not_crash(self):
        bad = os.path.join(self._tmp.name, "photo.exe")
        with open(bad, "wb") as f:
            f.write(b"MZ\x90\x00")
        self.window._on_files_dropped([bad])  # не повинно кидати виключення
        self.assertEqual(self.window.loaded_logs, [])
        self.assertEqual(self.window.logs_list.count(), 0)
        self.assertIsNone(self.window.current_report)
        QMessageBox.warning.assert_called_once()

    def test_drop_folder_does_not_crash(self):
        folder = os.path.join(self._tmp.name, "some_folder")
        os.makedirs(folder)
        self.window._on_files_dropped([folder])
        self.assertEqual(self.window.loaded_logs, [])
        self.assertEqual(self.window.logs_list.count(), 0)
        QMessageBox.warning.assert_called_once()

    def test_drop_multiple_files_valid_invalid_dir(self):
        bad = os.path.join(self._tmp.name, "notes.docx")
        folder = os.path.join(self._tmp.name, "logs_dir")
        os.makedirs(folder)
        with open(bad, "w", encoding="utf-8") as f:
            f.write("docx-ish content")
        self.window._on_files_dropped([self.panic_path, bad, folder])
        # Коректний файл імпортовано, проблемні проігноровані.
        self.assertEqual(len(self.window.loaded_logs), 1)
        self.assertEqual(self.window.loaded_logs[0]["name"], "panic-full-test.ips")
        QMessageBox.warning.assert_called_once()


if __name__ == "__main__":
    unittest.main(verbosity=2)