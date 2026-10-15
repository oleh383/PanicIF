# -*- coding: utf-8 -*-
"""Сервіс аналізу panic-логів для Telegram-бота.

Це тонкий адаптер до наявного діагностичного ядра PanicIF
(:mod:`app.core.diagnostics`). Жодних нових правил діагностики тут немає:
усі висновки формуються ядром Windows-застосунку.

Безпека:
    * розмір завантаження обмежено (:data:`MAX_UPLOAD_BYTES`);
    * тип файлу перевіряється за вмістом, а не лише за розширенням;
    * вміст зберігається у тимчасовому файлі, який гарантовано видаляється;
    * вміст ніколи не виконується як код.
"""

from __future__ import annotations

import contextlib
import os
import tempfile
from dataclasses import dataclass

from app.core.diagnostics import (
    SUPPORTED_IMAGE_EXTENSIONS,
    SUPPORTED_LOG_EXTENSIONS,
    DiagnosticReport,
    analyze_ocr_text,
    analyze_panic_text,
    build_text_report,
    classify_log_source,
    extract_panic_string_block,
    looks_like_image,
    ocr_image_to_text,
    read_text_with_auto_encoding,
)

# Обмеження розміру завантаження текстових логів (5 МБ).
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
# Зображення зазвичай більші за текст — окремий, дещо вищий ліміт (10 МБ).
MAX_IMAGE_UPLOAD_BYTES = 10 * 1024 * 1024

# Обмеження Telegram на довжину повідомлення / підпису (caption).
MAX_MESSAGE_LENGTH = 4096
MAX_CAPTION_LENGTH = 1024

SUPPORTED_EXTENSIONS = SUPPORTED_LOG_EXTENSIONS
REPORT_FILENAME = "panelif_report.txt"

# Зображення, які приймає бот (документом або як фото).
IMAGE_EXTENSIONS = SUPPORTED_IMAGE_EXTENSIONS

NON_PANIC_MESSAGE = (
    "Цей файл не схожий на panic-лог iPhone, який підтримує PanicIF. "
    "Надішли panic-full лог (.ips, .panic, .txt, .log), який містить блок "
    "panicString або рядок panic(cpu ...)."
)
UNSUPPORTED_EXTENSION_MESSAGE = (
    "Непідтримуване розширення файлу. Надішли panic-лог у форматі "
    ".ips, .panic, .txt або .log."
)
UNSUPPORTED_IMAGE_MESSAGE = (
    "Непідтримуване зображення. Надішли фото або документ у форматі "
    "JPG/JPEG або PNG."
)
TOO_LARGE_MESSAGE = (
    "Файл завеликий для аналізу (ліміт 5 МБ). Надішли менший panic-лог."
)
TOO_LARGE_IMAGE_MESSAGE = (
    "Зображення завелике для аналізу (ліміт 10 МБ). Спробуйте зменшити "
    "розмір або надіслати інше фото."
)
READ_ERROR_MESSAGE = (
    "Не вдалося прочитати файл. Спробуй надіслати його ще раз."
)
ANALYSIS_ERROR_MESSAGE = (
    "Під час аналізу файлу сталася помилка. Спробуй інший лог або фото."
)
OCR_ERROR_MESSAGE = (
    "Не вдалося розпізнати текст із фото. Спробуйте надіслати чіткіше "
    "зображення."
)
OCR_NO_TEXT_MESSAGE = (
    "Не вдалося розпізнати текст із фото. Спробуйте надіслати чіткіше "
    "зображення."
)
NO_DIAGNOSTIC_DATA_MESSAGE = (
    "Текст із фото розпізнано, але він не містить підтримуваних "
    "діагностичних даних panic-логу iPhone."
)
NO_FINDINGS_MESSAGE = "Проблем не виявлено."

# Повідомлення рівня бота (обмеження навантаження / загальні збої).
RATE_LIMIT_MESSAGE = (
    "Забагато запитів. Зачекай трохи й спробуй надіслати файл ще раз."
)
BUSY_MESSAGE = (
    "Зараз бот обробляє багато запитів. Спробуй, будь ласка, за мить."
)
TIMEOUT_MESSAGE = (
    "Аналіз триває занадто довго й перевищив ліміт часу. "
    "Спробуй ще раз із меншим файлом або чіткішим фото."
)
GENERIC_ERROR_MESSAGE = (
    "Сталася непередбачена помилка під час обробки. Спробуй надіслати файл "
    "ще раз пізніше."
)


class AnalyzerError(Exception):
    """Помилка під час аналізу (файл завеликий, нечитабельний тощо)."""


class UnsupportedImageError(AnalyzerError):
    """Файл не є підтримуваним зображенням."""


class OcrUnavailableError(AnalyzerError):
    """OCR-рушій PanicIF недоступний (не встановлено залежності)."""


@dataclass
class PhotoAnalysis:
    """Результат OCR-аналізу зображення.

    ``text`` — розпізнаний текст (порожній, якщо нічого не розпізнано).
    ``report`` — звіт наявного аналізатора PanicIF (``None``, якщо текст
    не розпізнано).
    """

    text: str
    report: "DiagnosticReport | None"


def file_extension(name: str) -> str:
    """Повернути розширення файлу (нижній регістр), напр. ``.ips``."""
    return os.path.splitext(name or "")[1].lower()


def is_supported_extension(name: str) -> bool:
    """Чи має файл підтримуване розширення (.ips/.panic/.txt/.log)."""
    return file_extension(name) in SUPPORTED_EXTENSIONS


def is_supported_image_extension(name: str) -> bool:
    """Чи має файл підтримуване розширення зображення (.jpg/.jpeg/.png)."""
    return file_extension(name) in IMAGE_EXTENSIONS


def is_panic_log_text(raw_text: str, file_name: str = "") -> bool:
    """Чи є текст підтримуваним panic-логом (за вмістом, не за розширенням).

    Довільний текст із «panic» у назві, але без реального panic-блоку,
    підтримуваним panic-логом НЕ вважається.
    """
    source = classify_log_source(raw_text, file_name)
    if source == "panic-full":
        return True
    if source == "panic":
        return bool(extract_panic_string_block(raw_text))
    return False


def analyze_text(raw_text: str, file_name: str = ""):
    """Запустити наявний аналізатор PanicIF на тексті логу."""
    return analyze_panic_text(raw_text, source_file=file_name)


@contextlib.contextmanager
def _temp_log_file(data: bytes, file_name: str):
    """Записати дані у тимчасовий файл і ГАРАНТОВАНО видалити його."""
    suffix = file_extension(file_name) or ".log"
    fd, path = tempfile.mkstemp(prefix="panelif_", suffix=suffix)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        yield path
    finally:
        with contextlib.suppress(OSError):
            os.remove(path)


def analyze_log_bytes(data: bytes, file_name: str):
    """Проаналізувати завантажені байти panic-логу.

    Повертає :class:`app.core.diagnostics.DiagnosticReport`, якщо файл є
    підтримуваним panic-логом, або ``None``, якщо це не panic-лог
    (порожній / довільний / бінарний файл).

    Піднімає :class:`AnalyzerError` при перевищенні ліміту чи помилці читання.
    """
    if not data:
        return None
    if len(data) > MAX_UPLOAD_BYTES:
        raise AnalyzerError(TOO_LARGE_MESSAGE)

    try:
        with _temp_log_file(data, file_name) as path:
            raw_text = read_text_with_auto_encoding(path)
    except OSError as exc:
        raise AnalyzerError(READ_ERROR_MESSAGE) from exc

    if not is_panic_log_text(raw_text, file_name):
        return None

    return analyze_text(raw_text, file_name)


def recognize_image_file(path: str) -> str:
    """Розпізнати текст із зображення наявним OCR-рушієм PanicIF.

    Піднімає :class:`OcrUnavailableError`, якщо OCR-залежності не встановлено.
    """
    try:
        return ocr_image_to_text(path)
    except RuntimeError as exc:  # OCR-движок відсутній
        raise OcrUnavailableError(OCR_ERROR_MESSAGE) from exc


def analyze_photo_text(raw_text: str, file_name: str = "") -> DiagnosticReport:
    """Проаналізувати розпізнаний з фото текст наявною логікою PanicIF."""
    return analyze_ocr_text(raw_text, source_file=file_name)


def analyze_image_bytes(data: bytes, file_name: str = "") -> PhotoAnalysis:
    """Розпізнати текст на зображенні та проаналізувати його.

    Повертає :class:`PhotoAnalysis`. Якщо текст не розпізнано — ``text``
    порожній, а ``report`` дорівнює ``None``. Якщо вміст не є зображенням
    (перевірка за сигнатурою), піднімає :class:`UnsupportedImageError`.

    Тимчасовий файл гарантовано видаляється.
    """
    if not data:
        return PhotoAnalysis("", None)
    if len(data) > MAX_IMAGE_UPLOAD_BYTES:
        raise AnalyzerError(TOO_LARGE_IMAGE_MESSAGE)

    try:
        with _temp_log_file(data, file_name) as path:
            if not looks_like_image(path):
                raise UnsupportedImageError(UNSUPPORTED_IMAGE_MESSAGE)
            text = recognize_image_file(path)
    except OSError as exc:
        raise AnalyzerError(READ_ERROR_MESSAGE) from exc

    if not text.strip():
        return PhotoAnalysis("", None)

    return PhotoAnalysis(text, analyze_photo_text(text, file_name))


def summarize(report) -> str:
    """Короткий підсумок повідомлення (без вигадування діагнозів)."""
    if report is None or not report.findings:
        return NO_FINDINGS_MESSAGE
    return report.verdict


def summarize_photo(analysis: PhotoAnalysis) -> str:
    """Підсумок для фото (використовує висновок наявної логіки PanicIF)."""
    if analysis is None or not analysis.text or analysis.report is None:
        return OCR_NO_TEXT_MESSAGE
    return analysis.report.verdict


def build_report_text(report) -> str:
    """Повний текстовий звіт наявного аналізатора PanicIF."""
    return build_text_report(report)


__all__ = [
    "AnalyzerError",
    "UnsupportedImageError",
    "OcrUnavailableError",
    "PhotoAnalysis",
    "MAX_UPLOAD_BYTES",
    "MAX_IMAGE_UPLOAD_BYTES",
    "MAX_MESSAGE_LENGTH",
    "MAX_CAPTION_LENGTH",
    "SUPPORTED_EXTENSIONS",
    "IMAGE_EXTENSIONS",
    "REPORT_FILENAME",
    "NON_PANIC_MESSAGE",
    "UNSUPPORTED_EXTENSION_MESSAGE",
    "UNSUPPORTED_IMAGE_MESSAGE",
    "TOO_LARGE_MESSAGE",
    "TOO_LARGE_IMAGE_MESSAGE",
    "READ_ERROR_MESSAGE",
    "ANALYSIS_ERROR_MESSAGE",
    "OCR_ERROR_MESSAGE",
    "OCR_NO_TEXT_MESSAGE",
    "NO_DIAGNOSTIC_DATA_MESSAGE",
    "NO_FINDINGS_MESSAGE",
    "RATE_LIMIT_MESSAGE",
    "BUSY_MESSAGE",
    "TIMEOUT_MESSAGE",
    "GENERIC_ERROR_MESSAGE",
    "file_extension",
    "is_supported_extension",
    "is_supported_image_extension",
    "is_panic_log_text",
    "analyze_text",
    "analyze_log_bytes",
    "recognize_image_file",
    "analyze_photo_text",
    "analyze_image_bytes",
    "summarize",
    "summarize_photo",
    "build_report_text",
]
