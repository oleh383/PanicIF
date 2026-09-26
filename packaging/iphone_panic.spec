# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec для iPhone Panic Log Diagnostics — оптимізована версія.
# Збірка:  python -m PyInstaller --noconfirm --clean packaging/iphone_panic.spec
#
# Оптимізації (порівняно з попередньою версією):
#  1) ЗАМІСТЬ collect_all("pymobiledevice3") (тягнув весь CLI+REMOTE+WebDAV:
#     IPython/jedi/uvicorn/fastapi/starlette/pmd_pytcp/pydantic/PIL тощо)
#     — використовуємо точкові hiddenimports лише тих підмодулів, що реально
#     потрібні для: lockdown/usbmux, device info, Panic Logs (crash_reports).
#  2) exclude список бракує свідомо непотрібні пакети (CLI/REPL/webdav/tunnel).
#  3) Відсікаємо непотрібні Qt-бінарники (opengl32sw.dll), Qt-модулі
#     (Qt6Pdf/Qt6Svg/Qt6Network) та зайві Qt-переклади (qtbase_*.qm).
#  4) Ціль pymobiledevice3 підвантажується «ледаче» (в середині методів
#     робітників), тому тримаємо повний релевантний набір модулів явно.

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
)
import os

# SPECPATH — папка, де лежить spec-файл (packaging/). Корінь проєкту — рівнем вище.
PROJECT_ROOT = os.path.dirname(SPECPATH)
if not PROJECT_ROOT:
    PROJECT_ROOT = os.getcwd()

datas = []
binaries = []
hiddenimports = []

# ---------------------------------------------------------------------------
# pymobiledevice3 — точковий збір потрібних підмодулів та їхніх ресурсів.
# Список модулів зібрано за результатами runtime-трасування реальних викликів:
#   - lockdown create_using_usbmux (підключення, device info)
#   - services.crash_reports CrashReportsManager (Panic Logs)
# Всі суб-імпорти цих модулів PyInstaller проаналізує сам, але явний список
# робимо для надійності (модулі імпортуються ледаче всередині функцій).
# ---------------------------------------------------------------------------
pymod_hidden = [
    "pymobiledevice3",
    "pymobiledevice3.bonjour",
    "pymobiledevice3.ca",
    "pymobiledevice3.common",
    "pymobiledevice3.construct_compat",
    "pymobiledevice3.exceptions",
    "pymobiledevice3.irecv_devices",
    "pymobiledevice3.lockdown",
    "pymobiledevice3.lockdown_service_provider",
    "pymobiledevice3.osu",
    "pymobiledevice3.osu.os_utils",
    "pymobiledevice3.osu.win_util",
    "pymobiledevice3.pair_records",
    "pymobiledevice3.plist_types",
    "pymobiledevice3.remote",
    "pymobiledevice3.remote.remote_service",
    "pymobiledevice3.remote.remote_service_discovery",
    "pymobiledevice3.remote.remotexpc",
    "pymobiledevice3.remote.xpc_message",
    "pymobiledevice3.service_connection",
    "pymobiledevice3.services",
    "pymobiledevice3.services.afc",
    "pymobiledevice3.services.crash_reports",
    "pymobiledevice3.services.lockdown_service",
    "pymobiledevice3.services.notification_proxy",
    "pymobiledevice3.services.os_trace",
    "pymobiledevice3.usbmux",
    "pymobiledevice3.utils",
]
hiddenimports += pymod_hidden

# Дані та нативні бібліотеки pymobiledevice3 (сертифікати, ресурси, .pyd).
datas += collect_data_files("pymobiledevice3")
binaries += collect_dynamic_libs("pymobiledevice3")

# Звіт PDF будується через reportlab; явно підтягуємо модулі шрифтів,
# які імпортуються всередині функції.
hiddenimports += [
    "reportlab.pdfbase.pdfmetrics",
    "reportlab.pdfbase.ttfonts",
    "reportlab.pdfbase",
]

# Додаткові підмодулі для надійності alter у випадку динамічних імпортів у
# залежностях (construct/charset/requests можуть підвантажуватись неявно).
hiddenimports += collect_submodules("construct")
hiddenimports += collect_submodules("construct_typed")
hiddenimports += collect_submodules("pycrashreport")

# ---------------------------------------------------------------------------
# OCR-движок (RapidOCR на ONNX Runtime) для аналізу фотографій/скріншотів
# логів. Моделі (models/*.onnx) та конфіги (config.yaml) зберігаються як дані
# пакета; onnxruntime потребує нативні бібліотеки поруч із .pyd; увесь стек
# (numpy, opencv/cv2, shapely, pyclipper) підхоплюється стандартними hook-ами.
# ---------------------------------------------------------------------------
hiddenimports += collect_submodules("rapidocr_onnxruntime")
datas += collect_data_files("rapidocr_onnxruntime")
binaries += collect_dynamic_libs("onnxruntime")

# ---------------------------------------------------------------------------
# Свідомо виключені пакети (перевірено runtime-трасуванням: вони НЕ імпортуються
# в ланцюжку lockdown/usbmux + crash_reports/Panic Logs):
#   * CLI / REPL (IPython, jedi) та CLI-фреймворк серверів
#   * Remote Core Device (pmd_pytcp / pmd_net_proto / pmd_net_addr / pytun_pmd3)
#   * WebDAV/HTTP сервіси (uvicorn/fastapi/starlette/asgi_webdav/aiofiles/aiohttp)
#   * WebInspector/websockets, BLE (bleak), pcap (pcapng), DVT тощо.
# ВАЖЛИВО: xonsh, typer, click, questionary, rich, pygments, prompt_toolkit,
# traitlets, PIL ЗАЛИШАЄМО — їх імпортують pymobiledevice3.crash_reports,
# pycrashreport, pymobiledevice3.utils та reportlab (PDF-експорт; він
# тягне reportlab.lib.utils -> PIL обов'язково).
# ---------------------------------------------------------------------------
excludes = [
    "IPython",
    "jedi",
    "uvicorn",
    "fastapi",
    "starlette",
    "anyio",
    "asgi_webdav",
    "aiofiles",
    "aiohttp",
    "websockets",
    "wsproto",
    "bleak",
    "pcapng",
    "scapy",
    "pmd_pytcp",
    "pmd_net_proto",
    "pmd_net_addr",
    "pytun_pmd3",
    "qh3",
    "dataclass_wizard",
    "pydantic",
]

a = Analysis(
    [os.path.join(PROJECT_ROOT, "app", "iphone_panic_diagnostics.py")],
    pathex=[os.path.join(PROJECT_ROOT, "app")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=1,
)

# ---------------------------------------------------------------------------
# Фільтрація Qt-бінарників: лишаємо лише те, що потрібно для widgets-GUI.
# Викидаємо:
#   - opengl32sw.dll (20 МБ software-renderer; для QWidgets не потрібен)
#   - Qt6Pdf.dll / Qt6Svg.dll / Qt6Network.dll (модулі не використовуються)
#   - Qt плагіни зображень jpeg/webp/tiff (у GUI немає >= 2-х строк зображень)
# ---------------------------------------------------------------------------
_qt_drop = {
    "opengl32sw.dll",
    "qt6pdf.dll",
    "qt6svg.dll",
    "qt6network.dll",
    "qjpeg.dll",
    "qwebp.dll",
    "qtiff.dll",
    "qicns.dll",
    "qgif.dll",
    "qtga.dll",
    "qwbmp.dll",
    "qpdf.dll",
    "qtuiotouchplugin.dll",
}

_q_drop = tuple(_qt_drop)
_filtered_binaries = []
for _dest, _src, _typecode in a.binaries:
    _name = os.path.basename(_dest).lower()
    if _name in _qt_drop or _name.lower() in _qt_drop:
        continue
    _filtered_binaries.append((_dest, _src, _typecode))
a.binaries = _filtered_binaries

# Очищуємо Qt-переклади: лишаємо лише українську та англійську (qtbase_uk/en).
def _keep_translation(dest):
    d = dest.lower()
    if not d.endswith(".qm"):
        return True
    return "qtbase_uk.qm" in d or "qtbase_en.qm" in d

a.datas = [(_d, _s, _t) for (_d, _s, _t) in a.datas if _keep_translation(_d)]

pyz = PYZ(a.pure)

# ---------------------------------------------------------------------------
# onedir-режим: pyzm/bootloader в EXE, решта (DLL, .pyd, datas) — папка
# iPhonePanicDiagnostics/ поруч. Швидший і стабільніший старт (без розпаковки
# в %TEMP%), антивируси менше скаржаться. Встановлений розмір більший
# (~94 МБ vs ~45 МБ), але старт миттєвий — це обраний компроміс.
# ---------------------------------------------------------------------------
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="iPhonePanicDiagnostics",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(SPECPATH, "icon.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="iPhonePanicDiagnostics",
)