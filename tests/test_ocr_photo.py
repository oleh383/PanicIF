# -*- coding: utf-8 -*-
"""Тести OCR-аналізу фотографій/скріншотів логів.

Вимоги (з технічного завдання):
  1) Чітке фото з відомим ключем бази знань -> знаходиться несправність.
  2) Скріншот panic-логу -> кілька ключів -> кілька знахідок.
  3) Довгий текст фото -> TXT/PDF звіт, текст переноситься і зберігається.
  4) Фото без тексту -> повідомлення «Не вдалося розпізнати текст...».
  5) Текст є, але ключів немає -> «Текст розпізнано, але ... ключів не знайдено».
  6) Аналіз фото НЕ впливає на аналіз panic-full (джерела незалежні).
  7) Drag & Drop фото направляє файл на OCR-шлях.
  8) Непідтримувані файли не ламають програму.
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

from PyQt6.QtWidgets import QApplication, QMessageBox  # noqa: E402

PANIC_LOG = (
    '{"bug_type":"210","timestamp":"2026-09-11 13:29:26.00 +0300",'
    '"os_version":"iPhone OS 18.7.7 (22H340)"}\n'
    '{ "product" : "iPhone14,5", "build" : "iPhone OS 18.7.7 (22H340)",'
    '"panicString" : "panic(cpu 0 caller 0xfffffff049bb6db8): '
    '\\"_enableHalogen:4104 Unknown sample rate on DAC\\" '
    '@AppleCS42L77Audio.cpp:4104\\\\nDebugger message: panic\\\\n",'
    '"panicFlags" : "0x802" }\n'
)


def _make_image(path, lines, width=1400, font_size=56, bg="white", fg="black"):
    """Генерує тестове зображення з текстом (без OCR у процесі)."""
    from PIL import Image, ImageDraw, ImageFont
    font = None
    for name in ("arial.ttf", "calibri.ttf", "verdana.ttf"):
        try:
            font = ImageFont.truetype(name, font_size)
            break
        except OSError:
            continue
    if font is None:
        font = ImageFont.load_default()
    step = int(font_size * 2.0)
    h = step * len(lines) + 80
    img = Image.new("RGB", (width, h), bg)
    d = ImageDraw.Draw(img)
    y = 40
    for ln in lines:
        d.text((40, y), ln, fill=fg, font=font)
        y += step
    img.save(path)


class TestOcrPhoto(unittest.TestCase):
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
        self._t = self._tmp.name
        self.panic_path = os.path.join(self._t, "panic-full-test.ips")
        with open(self.panic_path, "w", encoding="utf-8") as f:
            f.write(PANIC_LOG)
        # Мінімальне справжнє PNG (для D&D-тестів потрібна сигнатура).
        self.photo_path = os.path.join(self._t, "snapshot.png")
        _make_image(self.photo_path, ["AppleSocHot AGXG10P"], width=1000)

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

    # ---- 1) Чітке фото з відомим ключем -----------------------------------
    def test_clear_photo_with_keyword_gives_diagnosis(self):
        img = os.path.join(self._t, "clear.png")
        _make_image(img, [
            "panic(cpu 0 caller 0xfffffff0075b5f8c)",
            "AppleSocHot AGXG10P 0x12345678, userspace watchdog",
            "Prs0 Pressure Controller Eiger.cpp:356",
        ], width=1400, font_size=40)
        text = MODULE.ocr_image_to_text(img)
        self.assertTrue(text, "OCR не розпізнав текст на чіткому фото")
        report = MODULE.analyze_ocr_text(text, source_file=img)
        self.assertEqual(report.source_type, "photo")
        self.assertTrue(report.findings, "ключ AppleSocHot не знайдено")
        self.assertTrue(
            any("SocHot" in f.keyword for f in report.findings),
            f"очікувався AppleSocHot, отримано: "
            f"{[f.keyword for f in report.findings]}",
        )
        self.assertTrue(report.verdict.startswith("Ймовірна несправність"))

    # ---- 2) Скріншот panic-логу -------------------------------------------
    def test_panic_screenshot_finds_multiple_keywords(self):
        img = os.path.join(self._t, "shot.png")
        _make_image(img, [
            "panic(cpu 1 caller 0xfffffff0072a3e1c)",
            "AppleCS42L77Audio _enableHalogen unknown sample rate",
            "Prs0 Pressure Controller Eiger.cpp:356",
        ], width=1400, font_size=40)
        text = MODULE.ocr_image_to_text(img)
        self.assertTrue(text)
        report = MODULE.analyze_ocr_text(text, source_file=img)
        self.assertGreaterEqual(len(report.findings), 2,
                                f"замало знахідок: {report.findings}")
        self.assertEqual(len(report.matched_keywords), len(report.findings))

    # ---- 3) Довгий текст фото + TXT/PDF звіт -------------------------------
    def test_long_text_photo_txt_and_pdf(self):
        lines = [f"Line {i}: kernel message value {i * 7 % 100}" for i in range(28)]
        lines[10] = "AppleSocHot critical temperature reached"
        img = os.path.join(self._t, "long.png")
        _make_image(img, lines, width=1500, font_size=40)
        text = MODULE.ocr_image_to_text(img)
        self.assertTrue(text)
        report = MODULE.analyze_ocr_text(text, source_file=img)
        self.assertTrue(report.findings, "AppleSocHot має бути знайдено")
        # TXT-звіт: показуються знахідки, але НЕ повний розпізнаний текст.
        txt = MODULE.build_text_report(report)
        self.assertIn("Фото / OCR", txt)
        self.assertIn("AppleSocHot", txt)
        self.assertNotIn("РОЗПІЗНАНИЙ ТЕКСТ (OCR):", txt)
        self.assertNotIn("kernel message value", txt)
        # PDF-звіт відкривається, містить ключове слово, але без OCR-тексту.
        from pypdf import PdfReader
        pdf = os.path.join(self._t, "out.pdf")
        MODULE.export_pdf(report, pdf)
        self.assertTrue(os.path.exists(pdf))
        reader = PdfReader(pdf)
        self.assertGreaterEqual(len(reader.pages), 1)
        joined = "".join(p.extract_text() or "" for p in reader.pages)
        self.assertIn("AppleSocHot", joined)
        self.assertNotIn("Розпізнаний текст (OCR)", joined)
        self.assertNotIn("kernel message value", joined)

    # ---- 4) Фото без тексту -------------------------------------------------
    def test_photo_without_text_returns_empty_and_warns(self):
        blank = os.path.join(self._t, "blank.png")
        _make_image(blank, ["   "], width=800, font_size=20)
        text = MODULE.ocr_image_to_text(blank)
        self.assertEqual(text, "")
        # GUI-шлях: OCR порожньо -> попередження з точним текстом вимоги.
        self.window._on_ocr_ready(blank, "")
        QMessageBox.warning.assert_called_once()
        msg = QMessageBox.warning.call_args[0]
        self.assertEqual(msg[2], MODULE.OCR_NO_TEXT_MSG)
        self.assertIsNone(self.window.current_report)

    # ---- 5) Текст є, ключів немає -------------------------------------------
    def test_photo_text_without_keywords(self):
        img = os.path.join(self._t, "notes.png")
        _make_image(img, ["Hello world, this is an ordinary note 12345"],
                    width=1200, font_size=60)
        text = MODULE.ocr_image_to_text(img)
        self.assertTrue(text, "текст має розпізнатись")
        report = MODULE.analyze_ocr_text(text, source_file=img)
        self.assertEqual(report.findings, [])
        self.assertEqual(report.verdict, MODULE.OCR_NO_KEYWORDS_MSG)
        # GUI інформує користувача тим самим повідомленням.
        self.window._on_ocr_ready(img, "Hello world note without keywords")
        QMessageBox.information.assert_called_once()
        msg = QMessageBox.information.call_args[0]
        self.assertEqual(msg[2], MODULE.OCR_NO_KEYWORDS_MSG)
        self.assertEqual(self.window.current_report.source_type, "photo")

    # ---- 6) Незалежність фото і panic-full ----------------------------------
    def test_photo_analysis_independent_from_panic_full(self):
        self.window._import_log_file(self.panic_path)
        self.assertTrue(self.window.current_report.is_panic_source)
        self.assertEqual(self.window.current_report.source_type, "panic-full")

        # Тепер завантажуємо фото з ключем — має стати ТІЛЬКИ photo-аналізом.
        self.window._on_ocr_ready(self.photo_path,
                                  "panic cpu 0 AppleSocHot temperature")
        self.assertEqual(self.window.current_report.source_type, "photo")
        self.assertEqual(len(self.window.loaded_logs), 2)
        self.assertEqual(self.window.loaded_logs[0]["name"], "snapshot.png")
        self.assertEqual(self.window.loaded_logs[1]["name"],
                         "panic-full-test.ips")
        # Повторний вибір panic-логу показує саме panic-full (а не photo).
        panic_item = self.window.logs_list.item(1)
        self.window._on_log_selected(panic_item)
        self.assertTrue(self.window.current_report.is_panic_source)
        self.assertEqual(self.window.current_report.source_type, "panic-full")

    # ---- 7) Drag & Drop фото -> OCR-шлях ------------------------------------
    def test_drop_photo_routes_to_ocr_path(self):
        with mock.patch.object(MODULE.MainWindow, "_start_ocr_import",
                               autospec=True) as ocr:
            self.window._on_files_dropped([self.photo_path])
            ocr.assert_called_once_with(self.window, self.photo_path)
        self.assertEqual(self.window.loaded_logs, [])

    def test_button_photo_chooses_image_and_runs_ocr(self):
        from PyQt6.QtWidgets import QFileDialog
        with mock.patch.object(QFileDialog, "getOpenFileName",
                               return_value=(self.photo_path, "")):
            with mock.patch.object(MODULE.MainWindow, "_start_ocr_import",
                                   autospec=True) as ocr:
                self.window._on_load_photo_clicked()
                ocr.assert_called_once_with(self.window, self.photo_path)

    # ---- 8) Непідтримувані файли не ламають програму ------------------------
    def test_drop_unsupported_file_does_not_crash(self):
        bad = os.path.join(self._t, "notes.docx")
        with open(bad, "w", encoding="utf-8") as f:
            f.write("some docx-ish content")
        self.window._on_files_dropped([bad])
        self.assertEqual(self.window.loaded_logs, [])
        self.assertIsNone(self.window.current_report)
        QMessageBox.warning.assert_called_once()

    def test_drop_log_and_photo_mixed(self):
        with mock.patch.object(MODULE.MainWindow, "_start_ocr_import",
                               autospec=True) as ocr:
            self.window._on_files_dropped([self.panic_path, self.photo_path])
            ocr.assert_called_once_with(self.window, self.photo_path)
        self.assertEqual(len(self.window.loaded_logs), 1)
        self.assertEqual(self.window.loaded_logs[0]["name"],
                         "panic-full-test.ips")


# ---- 9) Код 0x4000 -> акумулятор (iPhone 13 серії) ----------------------
    def test_sensor_code_0x4000_recognized_as_battery(self):
        # Реальне OCR по фотографії рядка SMC Sensor Array.
        img = os.path.join(self._t, "array.png")
        _make_image(img, [
            "SMC PANIC - Sensor Array",
            "S.sensor array 0 - 6 is 0x0, 0x4000, 0x0, 0x0, 0x0, 0x0, 0x0",
        ], width=1500, font_size=40)
        text = MODULE.ocr_image_to_text(img)
        self.assertIn("0x4000", text, f"OCR не прочитав код: {text!r}")
        report = MODULE.analyze_ocr_text(text, source_file=img, model_hint="13")
        self.assertTrue(
            any("0x4000" in f.keyword for f in report.findings),
            f"0x4000 не знайдено: {[f.keyword for f in report.findings]}",
        )
        bat = [f for f in report.findings if "0x4000" in f.keyword][0]
        self.assertIn("Акумулятор", bat.component)
        self.assertIn("батаре", bat.recommendation.lower())
        self.assertEqual(bat.matched_snippet, "")  # OCR-текст не видаємо
        self.assertIn("Код: 0x4000", report.verdict)

    def test_hex_code_variants_normalized(self):
        # Різні написания коду (регістр, пробіли, символи) -> те саме значення.
        for variant in ("0x4000", "0X4000", "(0x4000)", "0x4000,", "  0x4000  "):
            res = MODULE.decode_sensor_codes_from_photo(variant, model_hint="13")
            self.assertEqual(len(res), 1, f"вариант {variant!r}: {res}")
            self.assertIn("0x4000", res[0].keyword)

    def test_0x4000_detected_despite_ocr_noise(self):
        # OCR-спотворення слова-підказки/ряду «... is ...» не заважають.
        noisy = "S.sensor arrav 0 - 6 iis 0x0, 0x4000, 0x0, 0x0, 0x0"
        res = MODULE.decode_sensor_codes_from_photo(noisy, model_hint="13")
        self.assertEqual(len(res), 1, f"очікувався 0x4000: {res}")
        self.assertIn("Акумулятор", res[0].component)

    def test_0x4000_auto_model_from_product_id(self):
        # Режим «АВТО»: модель визначається з product-id у тексті.
        raw = '{"product" : "iPhone14,5"}  S.sensor array 0 - 6 is 0x0, 0X4000, 0x0'
        res = MODULE.decode_sensor_codes_from_photo(raw, model_hint="")
        self.assertEqual(len(res), 1, f"очікувався 0x4000: {res}")
        self.assertIn("Акумулятор", res[0].component)

    def test_panic_flags_not_mistaken_for_sensor_code(self):
        # Прапорець panicFlags «0x802» — НЕ SMC-код, помилкового діагнозу немає.
        res = MODULE.decode_sensor_codes_from_photo(
            '"panicFlags" : "0x802"', model_hint="13")
        self.assertEqual(res, [])

    def test_photo_report_does_not_expose_ocr_text_gui(self):
        from PyQt6.QtWidgets import QToolButton
        self.window.show()
        try:
            with mock.patch.object(MODULE.MainWindow, "_show_raw_view",
                                   autospec=True) as show_raw:
                self.window._on_ocr_ready(
                    self.photo_path,
                    "S.sensor array 0 - 6 is 0x0, 0x4000, 0x0",
                )
                # Повний розпізнаний текст не показується і не відкривається.
                show_raw.assert_not_called()
                self.assertIsInstance(
                    self.window.view_mode_btn, QToolButton)
                self.assertFalse(self.window.view_mode_btn.isChecked())
                self.assertFalse(self.window.view_mode_btn.isVisible())
                self.assertFalse(getattr(self.window, "_raw_view_active", False))
                # Повернення до логу знову показує кнопку Raw Panic.
                self.window._import_log_file(self.panic_path)
                self.assertTrue(self.window.view_mode_btn.isVisible())
                self.assertEqual(
                    self.window.view_mode_btn.text(),
                    "👁 Переглянути сирий лог (Raw Panic)",
                )
        finally:
            self.window.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)