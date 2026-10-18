# -*- coding: utf-8 -*-
"""Тонкий завантажувач діагностичного ядра PanicIF без PyQt6.

Призначення
-----------
Windows-застосунок (``app/iphone_panic_diagnostics.py``) поєднує діагностичну
логіку та GUI в одному файлі й імпортує PyQt6 на верхньому рівні. Щоб
використовувати ту саму логіку в Telegram-боті (без GUI), цей модуль:

1. підставляє легкий stub замість ``PyQt6`` (лише якщо справжній PyQt6 ще не
   імпортовано), тому бот НІКОЛИ не імпортує реальний Qt;
2. завантажує наявний ``app/iphone_panic_diagnostics.py`` як єдине джерело
   правил діагностики;
3. реекспортує лише чисті (не-GUI) функції та моделі.

Копіювання чи переписування бази знань тут НЕ відбувається.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import types

_CORE_FILENAME = "iphone_panic_diagnostics"
_CORE_MODULE_NAME = "iphone_panic_diagnostics"
_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CORE_PATH = os.path.join(_APP_DIR, _CORE_FILENAME + ".py")


# ---------------------------------------------------------------------------
# Stub PyQt6: потрібен лише для того, щоб модуль ядра імпортувався без GUI.
# Він не імітує поведінку Qt — жоден GUI-метод ботом не викликається.
# ---------------------------------------------------------------------------
_STUB_MODULE_NAMES = (
    "PyQt6",
    "PyQt6.QtCore",
    "PyQt6.QtGui",
    "PyQt6.QtWidgets",
)


class _QtStubMeta(type):
    """Мета-клас, що дозволяє викликати stub-клас з будь-якими аргументами."""

    def __call__(cls, *args, **kwargs):  # noqa: D102
        return super().__call__()


class _QtStub(metaclass=_QtStubMeta):
    """Універсальний плейсхолдер замість будь-якого класу/сигналу Qt."""

    def __getattr__(self, name):  # noqa: D102
        return _QtStub


def _make_stub_module(name: str) -> types.ModuleType:
    module = types.ModuleType(name)
    module._PANICIF_QT_STUB = True  # маркер: це заглушка, а не справжній Qt
    module.__getattr__ = lambda _attr: _QtStub
    return module


def _install_qt_stubs() -> list:
    """Тимчасово підставити stub PyQt6. Повертає список встановлених імен.

    Якщо справжній ``PyQt6`` уже імпортовано, нічого не робимо (повертаємо []).
    """
    if "PyQt6" in sys.modules:
        return []
    installed = []
    for name in _STUB_MODULE_NAMES:
        sys.modules[name] = _make_stub_module(name)
        installed.append(name)
    return installed


def _load_core_module() -> types.ModuleType:
    existing = sys.modules.get(_CORE_MODULE_NAME)
    if existing is not None and hasattr(existing, "parse_panic_log"):
        return existing

    if _APP_DIR not in sys.path:
        sys.path.insert(0, _APP_DIR)

    spec = importlib.util.spec_from_file_location(_CORE_MODULE_NAME, _CORE_PATH)
    if spec is None or spec.loader is None:  # pragma: no cover - захист від дивного середовища
        raise ImportError(f"Не вдалося завантажити ядро PanicIF: {_CORE_PATH}")

    if "PyQt6" in sys.modules:
        module = importlib.util.module_from_spec(spec)
        sys.modules[_CORE_MODULE_NAME] = module
        spec.loader.exec_module(module)
        return module

    for name in _STUB_MODULE_NAMES:
        sys.modules[name] = _make_stub_module(name)
    try:
        module = importlib.util.module_from_spec(spec)
        sys.modules[_CORE_MODULE_NAME] = module
        spec.loader.exec_module(module)
    finally:
        _remove_qt_stub_modules()
    return module


def _remove_qt_stub_modules() -> None:
    """Прибрати встановлені stub-модулі, щоб не забруднювати ``sys.modules``.

    Завантажене ядро вже тримає прямі посилання на stub-класи, тож його робота
    не залежить від присутності заглушок у ``sys.modules``. Це важливо, щоб не
    ламати інші частини застосунку (напр., тести, що потребують справжнього Qt).
    """
    for name in _STUB_MODULE_NAMES:
        module = sys.modules.get(name)
        if module is not None and getattr(module, "_PANICIF_QT_STUB", False):
            del sys.modules[name]


CORE = _load_core_module()

# --- Реекспорт чистого (не-GUI) API ядра --------------------------------
APP_NAME = CORE.APP_NAME
APP_VERSION = CORE.APP_VERSION
SUPPORTED_LOG_EXTENSIONS = CORE.SUPPORTED_LOG_EXTENSIONS
SUPPORTED_IMAGE_EXTENSIONS = CORE.SUPPORTED_IMAGE_EXTENSIONS
OCR_NO_TEXT_MSG = CORE.OCR_NO_TEXT_MSG
OCR_NO_KEYWORDS_MSG = CORE.OCR_NO_KEYWORDS_MSG
Finding = CORE.Finding
DiagnosticReport = CORE.DiagnosticReport
read_text_with_auto_encoding = CORE.read_text_with_auto_encoding
extract_panic_string_block = CORE.extract_panic_string_block
classify_log_source = CORE.classify_log_source
parse_panic_log = CORE.parse_panic_log
build_text_report = CORE.build_text_report
build_telegram_report = CORE.build_telegram_report
# OCR (наявний рушій PanicIF; залежності завантажуються ліниво всередині)
ocr_image_to_text = CORE.ocr_image_to_text
analyze_ocr_text = CORE.analyze_ocr_text
looks_like_image = CORE._looks_like_image


def analyze_panic_text(raw_text: str, source_file: str = "") -> DiagnosticReport:
    """Проаналізувати текст panic-логу наявною логікою PanicIF.

    Обгортка над :func:`parse_panic_log` (щоб бот не залежав від деталей
    сигнатури ядра).
    """
    return parse_panic_log(raw_text, source_file=source_file)


__all__ = [
    "CORE",
    "APP_NAME",
    "APP_VERSION",
    "SUPPORTED_LOG_EXTENSIONS",
    "SUPPORTED_IMAGE_EXTENSIONS",
    "OCR_NO_TEXT_MSG",
    "OCR_NO_KEYWORDS_MSG",
    "Finding",
    "DiagnosticReport",
    "read_text_with_auto_encoding",
    "extract_panic_string_block",
    "classify_log_source",
    "parse_panic_log",
    "build_text_report",
    "build_telegram_report",
    "analyze_panic_text",
    "ocr_image_to_text",
    "analyze_ocr_text",
    "looks_like_image",
]
