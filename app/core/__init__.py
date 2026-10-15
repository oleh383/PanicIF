# -*- coding: utf-8 -*-
"""Діагностичне ядро PanicIF, придатне для повторного використання без GUI.

Пакет НЕ містить копії правил діагностики. Єдине джерело логіки —
``app/iphone_panic_diagnostics.py``. Модуль :mod:`app.core.diagnostics`
завантажує його без залежності від PyQt6 і реекспортує потрібні символи.
"""

from __future__ import annotations

from app.core.diagnostics import (  # noqa: F401
    APP_NAME,
    APP_VERSION,
    OCR_NO_KEYWORDS_MSG,
    OCR_NO_TEXT_MSG,
    SUPPORTED_IMAGE_EXTENSIONS,
    SUPPORTED_LOG_EXTENSIONS,
    DiagnosticReport,
    Finding,
    analyze_ocr_text,
    analyze_panic_text,
    build_text_report,
    classify_log_source,
    extract_panic_string_block,
    looks_like_image,
    ocr_image_to_text,
    parse_panic_log,
    read_text_with_auto_encoding,
)

__all__ = [
    "APP_NAME",
    "APP_VERSION",
    "OCR_NO_KEYWORDS_MSG",
    "OCR_NO_TEXT_MSG",
    "SUPPORTED_IMAGE_EXTENSIONS",
    "SUPPORTED_LOG_EXTENSIONS",
    "DiagnosticReport",
    "Finding",
    "analyze_ocr_text",
    "analyze_panic_text",
    "build_text_report",
    "classify_log_source",
    "extract_panic_string_block",
    "looks_like_image",
    "ocr_image_to_text",
    "parse_panic_log",
    "read_text_with_auto_encoding",
]
