#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=====================================================================================
 iPhone Panic Log Diagnostics (PanicIF) — десктопна програма для діагностики iPhone
 за логами Panic Full (PyQt6 + pymobiledevice3)
=====================================================================================

Призначення:
    Утиліта для майстрів з ремонту та технічних користувачів, яка:
      1. Виявляє підключений по USB iPhone (через pymobiledevice3 / usbmuxd).
      2. Зчитує CrashLogs / Panic Full логи з пристрою.
      3. Дозволяє також завантажити .panic/.ips/.txt файл вручну.
      4. Парсить лог за розширеною базою регулярних виразів і визначає
         ймовірний несправний компонент (шлейф, сенсор, АКБ, NAND, CPU тощо).
      5. Показує "вердикт" та детальний список знахідок з рекомендаціями з ремонту.
      6. Дозволяє зберегти звіт у TXT або PDF.
      7. Додатково вміє аналізувати ФОТО/СКРІНШОТ логу: локальний OCR
         (RapidOCR/ONNX, повністю офлайн) розпізнає текст, який далі
         аналізується ТІЄЮ САМОЮ базою знань, що й panic-full.

Автор: згенеровано за технічним завданням користувача.
Ліцензія: використання на власний розсуд, без гарантій.

=====================================================================================
 ІНСТРУКЦІЯ З ЗАПУСКУ
=====================================================================================

1) Встановити Python 3.10+ (https://www.python.org/downloads/windows/)
   Під час встановлення обов'язково відмітити "Add python.exe to PATH".

2) Встановити залежності (у командному рядку / PowerShell):

    pip install PyQt6 pymobiledevice3 reportlab pyinstaller

   Якщо pymobiledevice3 не встановлюється або лається на залежності,
   спробуйте оновити pip:  python -m pip install --upgrade pip
   а потім повторити встановлення.

3) На Windows для роботи з iPhone по USB потрібен iTunes АБО окремо
   встановлені драйвери Apple Mobile Device Support (входять до складу
   iTunes з офіційного сайту Apple, НЕ з Microsoft Store — там урізана
   версія без потрібних служб). Служба "Apple Mobile Device Service"
   повинна бути запущена (Win+R -> services.msc -> Apple Mobile Device
   Service -> Running).

4) Запустити програму:

    python iphone_panic_diagnostics.py

5) Підключити iPhone кабелем, розблокувати його та натиснути
   "Довіряти цьому компʼютеру" на екрані пристрою, якщо з'явиться запит.

=====================================================================================
 ЗБІРКА В .EXE (PyInstaller)
=====================================================================================

У теці зі скриптом виконати:

    pyinstaller --noconsole --onefile --name "PanicIF" ^
        --collect-all pymobiledevice3 ^
        --collect-all pygments ^
        iphone_panic_diagnostics.py

Пояснення ключів:
    --noconsole   — не показувати чорне консольне вікно (GUI-режим).
    --onefile     — зібрати все в один .exe файл.
    --collect-all pymobiledevice3 — pymobiledevice3 має ресурсні файли
                    (наприклад, lockdown-сертифікати/плагіни), які треба
                    примусово включити в збірку, інакше .exe працюватиме
                    з помилками "module not found" при спробі підключення.
    --collect-all pygments — pymobiledevice3 внутрішньо використовує
                    pygments для підсвітки виводу; часто губиться при збірці.

Готовий файл з'явиться у теці dist/PanicIF.exe

Якщо після збірки .exe не бачить пристрій — запустіть перевірку прямо
з .py файлу (через python) щоб виключити проблему саме збірки, і
переконайтесь, що на компʼютері встановлено iTunes / Apple Mobile
Device Support.

=====================================================================================
"""

from __future__ import annotations  # noqa: E402 — дозволяє посилатись на Finding до його оголошення

import sys
import os
import re
import json
import traceback
import datetime
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSize, QUrl
from PyQt6.QtGui import QFont, QColor, QIcon, QAction, QDesktopServices
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QListWidget, QListWidgetItem, QTextEdit, QPlainTextEdit,
    QTableWidget, QTableWidgetItem, QHeaderView, QFrame, QSplitter,
    QFileDialog, QMessageBox, QProgressBar, QToolButton, QStackedWidget,
    QSizePolicy, QGroupBox, QGridLayout, QScrollArea, QComboBox
)


# =====================================================================================
# Назва та версія продукту — ЄДИНЕ ДЖЕРЕЛО правди.
# Spec PyInstaller (packaging/iphone_panic.spec) та інсталятор Inno Setup
# (packaging/Setup.iss) читають їх звідси для генерації назви .exe та
# version-resource. Змінюйте версію ТІЛЬКИ тут перед новим GitHub Release.
# =====================================================================================
APP_NAME = "PanicIF"
APP_VERSION = "1.2.0"


# =====================================================================================
# Модуль перевірки оновлень (app/updater.py). Додаємо теку модуля на шлях пошуку,
# щоб 'import updater' працював і з вихідного коду, і у збірці PyInstaller.
# =====================================================================================
_APP_DIR = os.path.dirname(os.path.abspath(__file__))
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)

from updater import (  # noqa: E402
    UpdaterError,
    UpdaterDataError,
    UpdaterIntegrityError,
    UpdaterNetworkError,
    UpdaterServerError,
    is_update_available,
    fetch_latest_release,
    get_latest_tag,
    get_installer_asset,
    get_digest_asset,
    download_asset,
    fetch_digest,
    digest_matches,
    launch_installer,
)


# =====================================================================================
# 1. БАЗА ЗНАНЬ: RegEx-мапінг "ключове слово в лозі" -> "несправний компонент"
# =====================================================================================
# Кожен запис: {
#   "pattern": скомпільований regex (case-insensitive),
#   "keyword": людяне представлення ключового слова для звіту,
#   "component": назва вузла/компонента,
#   "recommendation": порада майстру щодо ремонту,
#   "severity": "critical" | "warning" | "info"  (впливає на колір картки)
# }

RAW_KNOWLEDGE_BASE: List[Dict[str, str]] = [
    # --- А. Живлення, датчики, шлейфи ---
    {
        "pattern": r"Prs0|Pressure Controller|Eiger\.cpp",
        "keyword": "Prs0 / Pressure Controller / Eiger.cpp",
        "component": "Нижній шлейф (зарядки)",
        "recommendation": (
            "Датчик барометра (Prs0) не відповідає. Замініть нижній шлейф "
            "зарядки. Для iPhone SE2 додатково перевірте ревізію мікрофона "
            "на шлейфі (GWM1/GWM2) — несумісна ревізія теж дає цю помилку."
        ),
        "severity": "critical",
    },
    {
        "pattern": r"TG0B|TG0V|TG0P|TG0D|SD:\s*0\s*Missing sensor\(s\):\s*TG0",
        "keyword": "TG0B / TG0V / TG0P / TG0D (Tigris)",
        "component": "Акумулятор / Контролер Tigris",
        "recommendation": (
            "Відсутній контакт BSI, критичний знос АКБ або несправний "
            "контролер Tigris. Перевірте контакт коннектора АКБ, за потреби "
            "замініть акумулятор; якщо не допомагає — перевірте/перепрошийте "
            "контролер Tigris."
        ),
        "severity": "critical",
    },
    {
        "pattern": r"\bmic1\b",
        "keyword": "mic1",
        "component": "Нижній шлейф",
        "recommendation": (
            "Помилка нижнього лівого мікрофона. Замініть нижній шлейф "
            "(шлейф зарядки/мікрофону) або перевірте доріжки під SIM-лотком "
            "на предмет корозії/обриву."
        ),
        "severity": "warning",
    },
    {
        "pattern": r"\bmic2\b|mic-temp-sens2",
        "keyword": "mic2 / mic-temp-sens2",
        "component": "Верхній шлейф спалаху",
        "recommendation": "Мікрофон біля камери/спалаху. Замініть шлейф спалаху.",
        "severity": "warning",
    },
    {
        "pattern": r"\bmic3\b",
        "keyword": "mic3",
        "component": "Верхній шлейф датчиків",
        "recommendation": "Мікрофон біля фронтальної камери. Замініть верхній шлейф датчиків.",
        "severity": "warning",
    },
    {
        "pattern": r"\bmic4\b",
        "keyword": "mic4",
        "component": "Нижній шлейф",
        "recommendation": "Помилка нижнього правого мікрофона. Замініть нижній шлейф.",
        "severity": "warning",
    },
    {
        "pattern": r"\bprox\b|SCMto:0-prox|SCMto:1-prox",
        "keyword": "prox / SCMto:0-prox / SCMto:1-prox",
        "component": "Верхній шлейф",
        "recommendation": "Несправність датчика наближення (Proximity). Замініть верхній шлейф.",
        "severity": "warning",
    },
    {
        "pattern": r"\bpearl\b|SCMto:2-pearl",
        "keyword": "pearl / SCMto:2-pearl",
        "component": "Верхній шлейф / Face ID",
        "recommendation": (
            "Питання модуля датчика наближення або системи Face ID. "
            "Перевірте верхній шлейф та шлейф Face ID/TrueDepth."
        ),
        "severity": "warning",
    },
    {
        "pattern": r"power\(2\)|power\(1\)",
        "keyword": "power(1) / power(2)",
        "component": "Верхній шлейф / PMU",
        "recommendation": (
            "Проблема кнопки увімкнення живлення або контролера живлення (PMU). "
            "Перевірте кнопку power / верхній шлейф, за потреби — PMU."
        ),
        "severity": "warning",
    },
    {
        "pattern": r"main\(5\)",
        "keyword": "main(5)",
        "component": "Шлейф кнопок гучності",
        "recommendation": "Замініть шлейф кнопок гучності (Volume Flex).",
        "severity": "warning",
    },
    {
        "pattern": r"NO pulse on",
        "keyword": "NO pulse on",
        "component": "Taptic Engine / Нижній шлейф",
        "recommendation": (
            "Немає імпульсу від вібромотору. Перевірте/замініть Taptic Engine "
            "або нижній шлейф, що з ним зʼєднаний."
        ),
        "severity": "warning",
    },
    {
        "pattern": r"Systick Watchdog",
        "keyword": "Systick Watchdog",
        "component": "Кнопка Home",
        "recommendation": "Перевірте шлейф/модуль кнопки Home.",
        "severity": "warning",
    },

    # --- Б. Дисплей, аудіо, периферія ---
    {
        "pattern": r"i2c2.*audio-speaker-top",
        "keyword": "i2c2 ... audio-speaker-top",
        "component": "Верхній шлейф / Підсилювач",
        "recommendation": (
            "Несправність верхнього динаміка або верхнього аудіопідсилювача. "
            "Перевірте верхній динамік і шлейф, за потреби — підсилювач на платі."
        ),
        "severity": "warning",
    },
    {
        "pattern": r"i2c3.*Roswell|display-eeprom|Lm3539|SCL display PMU|DCP PANIC|MIPIDSI",
        "keyword": "Roswell / display-eeprom / Lm3539 / DCP PANIC / MIPIDSI",
        "component": "Дисплейний модуль",
        "recommendation": (
            "Несправний дисплей, шлейф тачскріна або драйвер підсвітки/дисплея. "
            "Спробуйте замінити дисплейний модуль на завідомо робочий для перевірки."
        ),
        "severity": "critical",
    },
    {
        "pattern": r"Dart-disp SMMU error",
        "keyword": "Dart-disp SMMU error",
        "component": "Основна камера",
        "recommendation": "Помилка основної (задньої) камери. Замініть модуль основної камери.",
        "severity": "warning",
    },
    {
        "pattern": r"AppleCS42L77Audio|AppleCS42L75Audio|(?<!AOP)ad5860|H3K5 Tglon",
        "keyword": "AppleCS42L77/75Audio / ad5860 / H3K5 Tglon",
        "component": "Аудіокодек",
        "recommendation": (
            "Помилка аудіосистеми на рівні кодека. Перекатайте (реболл) або "
            "замініть мікросхему Audio Codec на материнській платі."
        ),
        "severity": "critical",
    },
    {
        "pattern": r"AppleBCMWLAN|apcie\(wlan\)|apcie\(bt\)",
        "keyword": "AppleBCMWLAN / apcie(wlan) / apcie(bt)",
        "component": "Wi-Fi / Bluetooth",
        "recommendation": (
            "Несправність модуля Wi-Fi/Bluetooth або його обвʼязки на платі. "
            "Перевірте антенні шлейфи, за потреби — модуль/мікросхему WiFi-BT."
        ),
        "severity": "warning",
    },
    {
        "pattern": r"@AppleMultiFunction Manager",
        "keyword": "@AppleMultiFunction Manager",
        "component": "Модем (Baseband)",
        "recommendation": (
            "Помилка модемного (baseband) процесора. Можливе міжплатне "
            "розшарування шлейфів або відвал/несправність модему."
        ),
        "severity": "critical",
    },
    {
        "pattern": r"Apple tristar2|Dart-USB",
        "keyword": "Apple tristar2 / Dart-USB",
        "component": "Контролер Tristar / Hydra / Kraken",
        "recommendation": (
            "Проблема з контролером зарядки/USB (Tristar/Hydra/Kraken) або "
            "нижнім шлейфом. Перевірте роз'єм Lightning/USB-C і нижній шлейф, "
            "за потреби — контролер на платі."
        ),
        "severity": "warning",
    },

    # --- В. Пам'ять, процесор, системні помилки ---
    {
        "pattern": r"\bANS\b|\bANS2\b|\bnvme\b|apcie\(0\)|Ememory",
        "keyword": "ANS / ANS2 / nvme / apcie(0) / Ememory",
        "component": "Пам'ять NAND",
        "recommendation": (
            "Несправність флеш-пам'яті NAND. Спробуйте повне відновлення "
            "через DFU-режим; якщо це не допомагає — потрібен реболл або "
            "заміна мікросхеми NAND (з переносом даних за потреби)."
        ),
        "severity": "critical",
    },
    {
        "pattern": r"Kernel data abort|Kernel instruction fetch|GFX GPU|@zalloc|@kalloc",
        "keyword": "Kernel data abort / GFX GPU / @zalloc / @kalloc",
        "component": "Процесор (CPU)",
        "recommendation": (
            "Ознаки відвалу або деградації процесора/графічного ядра "
            "(CPU/GPU). Потрібен реболл (BGA reflow) процесора, у важких "
            "випадках — заміна корпусу процесора."
        ),
        "severity": "critical",
    },
    {
        "pattern": r"AppleSocHot",
        "keyword": "AppleSocHot",
        "component": "Перегрів CPU / PMU",
        "recommendation": (
            "Спрацював тепловий захист SoC. Ймовірне коротке замикання на "
            "платі або несправність контролера живлення (PMU). Перевірте "
            "плату на КЗ, виміряйте струм споживання."
        ),
        "severity": "critical",
    },
    {
        "pattern": r"AGXG10P BONMI",
        "keyword": "AGXG10P BONMI",
        "component": "Материнська плата (Sandwich)",
        "recommendation": (
            "Обрив шарів міжплатної зборки ('сендвіча'), типово після падіння. "
            "Потрібно перекатати або переклеїти шари материнської плати."
        ),
        "severity": "critical",
    },
    {
        "pattern": r"Firmware fatal|vfs_cluster|SIGNAL, code 9",
        "keyword": "Firmware fatal / vfs_cluster / SIGNAL code 9",
        "component": "ПЗ / Файлова система",
        "recommendation": (
            "Схоже на програмний збій (не апаратний). Відновіть пристрій "
            "через офіційний iTunes або 3uTools (з резервною копією "
            "даних, якщо можливо)."
        ),
        "severity": "info",
    },
]


def _compile_knowledge_base(raw_kb: List[Dict[str, str]]):
    compiled = []
    for entry in raw_kb:
        try:
            rx = re.compile(entry["pattern"], re.IGNORECASE)
        except re.error:
            continue
        compiled.append({**entry, "regex": rx})
    return compiled


KNOWLEDGE_BASE = _compile_knowledge_base(RAW_KNOWLEDGE_BASE)


# =====================================================================================
# 1б. БАЗА ЗНАНЬ: розшифровка SMC PANIC - Sensor Array (iPhone 13 ... 17)
# =====================================================================================
# У сучасних iPhone (13+) панік-лог містить рядок виду
#   S.sensor array 0 - 6 is 0x0, 0x4000, 0x0, ...
# Значення — бітові маски, де кожен біт відповідає датчику/шлейфу.
# Мапи складені за довідником сервісних інженерів (стаття Pikabu
# "Ваш iPhone перезагружается на яблоке? ... Panic-full"):
#   https://pikabu.ru/story/...11901460
# Значення можуть бути у 16-ковій (0x...) або 10-ковій формі (iOS 26+).
#
# Формат кожної групи:
#   "bits"  — атомарні маски (окремий датчик/шлейф), використовуються і для
#             розкладання сумарних кодів,
#   "exact" — точні значення, які НЕ дорівнюють простій сумі бітів
#             (або мають особливе трактування).
#
# Кожен опис: (component, recommendation, severity)

SENSOR_ARRAY_KB: Dict[str, Dict[str, Any]] = {
    # ---- iPhone 13 / 13 mini / 13 Pro / 13 Pro Max (iPhone14,x) ----
    "13": {
        "label": "iPhone 13 / 13 mini / 13 Pro / 13 Pro Max",
        "bits": {
            0x4000: (
                "Акумулятор (батарея)",
                "Проблема з акумулятором (батареєю) — лінія передачі даних. "
                "Перевірте конектор АКБ, шлейф і контролер Tigris на платі.",
                "critical",
            ),
            0x800: (
                "Нижній шлейф зарядки",
                "Замініть/перевірте нижній шлейф зарядки.",
                "critical",
            ),
            0x1000: (
                "Шлейф безпровідної зарядки",
                "Перевірте/замініть шлейф безпровідної зарядки (MagSafe).",
                "warning",
            ),
            0x400: (
                "Нижня плата (тільки iPhone 13 mini)",
                "Код 0x400 на 13 mini означає проблему з нижньою платою. "
                "Потрібна компонентна діагностика материнської плати.",
                "critical",
            ),
        },
        "exact": {
            0x1800: (
                "Нижній шлейф зарядки + шлейф датчиків дисплея",
                "Суміщена ознака: нижній шлейф зарядки і шлейф датчиків "
                "дисплея. Перевірте обидва шлейфи.",
                "critical",
            ),
        },
    },

    # ---- iPhone 14 / 14 Plus (iPhone14,7/14,8) ----
    "14": {
        "label": "iPhone 14 / 14 Plus",
        "bits": {
            0x400000: (
                "Шлейф безпровідної зарядки",
                "Перевірте/замініть шлейф безпровідної зарядки (MagSafe).",
                "warning",
            ),
            0x100000: (
                "Нижній шлейф зарядки",
                "Замініть/перевірте нижній шлейф зарядки.",
                "critical",
            ),
            0x200000: (
                "Шлейф датчиків дисплея",
                "Перевірте/замініть шлейф датчиків на дисплеї.",
                "warning",
            ),
        },
        "exact": {
            0x500000: (
                "Taptic Engine / нижній шлейф (або зв'язок з АКБ)",
                "За довідником — перевірити Taptic Engine та нижній шлейф "
                "зарядки; також може вказувати на проблему зв'язку з "
                "акумулятором.",
                "warning",
            ),
            0x600000: (
                "Шлейф безпровідної зарядки + шлейф датчиків дисплея",
                "Суміщена помилка безпровідної зарядки та шлейфа датчиків "
                "дисплея.",
                "warning",
            ),
        },
    },

    # ---- iPhone 14 Pro / 14 Pro Max (iPhone15,2/15,3) ----
    "14pro": {
        "label": "iPhone 14 Pro / 14 Pro Max",
        "bits": {
            0x80000: (
                "Шлейф датчиків дисплея",
                "Перевірте/замініть шлейф датчиків на дисплеї.",
                "warning",
            ),
            0x40000: (
                "Нижній шлейф зарядки",
                "Замініть/перевірте нижній шлейф зарядки.",
                "critical",
            ),
            0x100000: (
                "Шлейф кнопки живлення",
                "Перевірте/замініть шлейф кнопки живлення (power).",
                "warning",
            ),
            0x20000: (
                "Половинки плат (Sandwich)",
                "Проблема з половинками плат (розшарування сендвіча). "
                "Потрібна компонентна діагностика плати.",
                "critical",
            ),
        },
        "exact": {},
    },

    # ---- iPhone 15 / 15 Plus (iPhone15,4/15,5) ----
    "15": {
        "label": "iPhone 15 / 15 Plus",
        "bits": {
            0x200000: (
                "Шлейф безпровідної зарядки",
                "Перевірте/замініть шлейф безпровідної зарядки (MagSafe).",
                "warning",
            ),
            0x80000: (
                "Нижній шлейф зарядки",
                "Замініть/перевірте нижній шлейф зарядки.",
                "critical",
            ),
            0x100000: (
                "Шлейф датчиків дисплея",
                "Перевірте/замініть шлейф датчиків на дисплеї.",
                "warning",
            ),
        },
        "exact": {},
    },

    # ---- iPhone 15 Pro / 15 Pro Max (iPhone16,1/16,2) ----
    "15pro": {
        "label": "iPhone 15 Pro / 15 Pro Max",
        "bits": {
            0x200000: (
                "Шлейф датчиків дисплея (тільки 15 Pro, не Pro Max)",
                "Перевірте/замініть шлейф датчиків на дисплеї. "
                "Код актуальний саме для iPhone 15 Pro.",
                "warning",
            ),
            0x300000: (
                "Нижній шлейф зарядки",
                "Замініть/перевірте нижній шлейф зарядки.",
                "critical",
            ),
            0x400000: (
                "Шлейф безпровідної зарядки",
                "Перевірте/замініть шлейф безпровідної зарядки (MagSafe).",
                "warning",
            ),
            0xA1: (
                "Зв'язок з акумулятором",
                "Проблема зв'язку з акумулятором. Перевірте конектор/АКБ.",
                "critical",
            ),
        },
        "exact": {},
    },

    # ---- iPhone 16 / 16 Plus (iPhone17,3/17,4) ----
    "16": {
        "label": "iPhone 16 / 16 Plus",
        "bits": {
            169: (
                "Дані акумулятора",
                "Проблеми з визначенням даних акумулятора.",
                "critical",
            ),
            524288: (
                "Датчик барометра (нижній шлейф)",
                "Немає відповіді від датчика барометра.",
                "warning",
            ),
            1048576: (
                "Датчик компаса",
                "Немає відповіді від датчика компаса.",
                "warning",
            ),
            2097152: (
                "Шлейф безпровідної зарядки",
                "Пошкоджено шлейф безпровідної зарядки.",
                "warning",
            ),
        },
        "exact": {
            1572864: (
                "Нижній шлейф (барометр і компас)",
                "Немає відповіді від барометра і компаса — типово "
                "відключений або пошкоджений нижній шлейф.",
                "critical",
            ),
        },
    },

    # ---- iPhone 16 Pro / 16 Pro Max (iPhone17,1/17,2) ----
    "16pro": {
        "label": "iPhone 16 Pro / 16 Pro Max",
        "bits": {
            169: (
                "Дані акумулятора",
                "Проблеми з визначенням даних акумулятора.",
                "critical",
            ),
            524288: (
                "Датчик гіроскопа",
                "Немає відповіді від датчика гіроскопа.",
                "warning",
            ),
            1048576: (
                "Датчик барометра",
                "Немає відповіді від датчика барометра.",
                "warning",
            ),
            2097152: (
                "Датчик компаса",
                "Немає відповіді від датчика компаса.",
                "warning",
            ),
            4194304: (
                "Мікросхема безпровідної зарядки (під SIM)",
                "Несправність мікросхеми безпровідної зарядки (розташована "
                "біля слоту SIM).",
                "warning",
            ),
        },
        "exact": {
            3145728: (
                "Нижній шлейф (барометр і компас)",
                "Немає відповіді від барометра і компаса — відключений або "
                "пошкоджений нижній шлейф.",
                "critical",
            ),
        },
    },

    # ---- iPhone 17 Pro / 17 Pro Max (iPhone18,1/18,2) ----
    "17pro": {
        "label": "iPhone 17 Pro / 17 Pro Max",
        "bits": {
            8388608: (
                "Безпровідна зарядка",
                "Перевірте/замініть шлейф безпровідної зарядки.",
                "warning",
            ),
            6291456: (
                "Шлейф зарядки",
                "Замініть/перевірте шлейф зарядки.",
                "critical",
            ),
            2097152: (
                "Верхній шлейф",
                "Перевірте/замініть верхній шлейф.",
                "warning",
            ),
            4194304: (
                "Вібромотор",
                "Перевірте/замініть вібромотор (Taptic Engine).",
                "warning",
            ),
        },
        "exact": {
            14680064: (
                "Нижній шлейф і безпровідна зарядка",
                "Пошкоджено нижній шлейф і шлейф безпровідної зарядки.",
                "critical",
            ),
            10485760: (
                "Шлейф зарядки і вібромотор",
                "Пошкоджено шлейф зарядки та вібромотор.",
                "warning",
            ),
        },
    },
}


# Відображення product-id ("iPhone14,5") -> назва моделі
PRODUCT_NAMES: Dict[str, str] = {
    "iPhone8,1": "iPhone 6s", "iPhone8,2": "iPhone 6s Plus", "iPhone8,4": "iPhone SE (1st gen)",
    "iPhone9,1": "iPhone 7", "iPhone9,2": "iPhone 7 Plus",
    "iPhone9,3": "iPhone 7", "iPhone9,4": "iPhone 7 Plus",
    "iPhone10,1": "iPhone 8", "iPhone10,2": "iPhone 8 Plus",
    "iPhone10,3": "iPhone X", "iPhone10,4": "iPhone 8",
    "iPhone10,5": "iPhone 8 Plus", "iPhone10,6": "iPhone X",
    "iPhone11,2": "iPhone XS", "iPhone11,4": "iPhone XS Max",
    "iPhone11,6": "iPhone XS Max", "iPhone11,8": "iPhone XR",
    "iPhone12,1": "iPhone 11", "iPhone12,3": "iPhone 11 Pro",
    "iPhone12,5": "iPhone 11 Pro Max", "iPhone12,8": "iPhone SE (2nd gen)",
    "iPhone13,1": "iPhone 12 mini", "iPhone13,2": "iPhone 12",
    "iPhone13,3": "iPhone 12 Pro", "iPhone13,4": "iPhone 12 Pro Max",
    "iPhone14,2": "iPhone 13 Pro", "iPhone14,3": "iPhone 13 Pro Max",
    "iPhone14,4": "iPhone 13 mini", "iPhone14,5": "iPhone 13",
    "iPhone14,6": "iPhone SE (3rd gen)", "iPhone14,7": "iPhone 14",
    "iPhone14,8": "iPhone 14 Plus",
    "iPhone15,2": "iPhone 14 Pro", "iPhone15,3": "iPhone 14 Pro Max",
    "iPhone15,4": "iPhone 15", "iPhone15,5": "iPhone 15 Plus",
    "iPhone16,1": "iPhone 15 Pro", "iPhone16,2": "iPhone 15 Pro Max",
    "iPhone17,1": "iPhone 16 Pro", "iPhone17,2": "iPhone 16 Pro Max",
    "iPhone17,3": "iPhone 16", "iPhone17,4": "iPhone 16 Plus",
    "iPhone17,5": "iPhone 16e",
    "iPhone18,1": "iPhone 17 Pro", "iPhone18,2": "iPhone 17 Pro Max",
    "iPhone18,3": "iPhone 17", "iPhone18,4": "iPhone Air",
    "iPhone18,5": "iPhone 17e",
}

# product-id -> група розшифровки Sensor Array
PRODUCT_TO_SENSOR_FAMILY: Dict[str, str] = {
    "iPhone14,2": "13", "iPhone14,3": "13", "iPhone14,4": "13", "iPhone14,5": "13",
    "iPhone14,7": "14", "iPhone14,8": "14",
    "iPhone15,2": "14pro", "iPhone15,3": "14pro",
    "iPhone15,4": "15", "iPhone15,5": "15",
    "iPhone16,1": "15pro", "iPhone16,2": "15pro",
    "iPhone17,1": "16pro", "iPhone17,2": "16pro",
    "iPhone17,3": "16", "iPhone17,4": "16",
    "iPhone18,1": "17pro", "iPhone18,2": "17pro",
}


def _resolve_sensor_family(raw_text: str = "", model_hint: str = "",
                           product: str = "") -> str:
    """Повертає ключ SENSOR_ARRAY_KB за підказкою користувача, а якщо
    автоматично — за product-id, переданим з релевантних метаданих логу."""
    if model_hint in SENSOR_ARRAY_KB:
        return model_hint
    if product:
        fam = PRODUCT_TO_SENSOR_FAMILY.get(product.strip())
        if fam:
            return fam
    if raw_text:
        m = re.search(r'"product"\s*:\s*"([^"]+)"', raw_text)
        if m:
            fam = PRODUCT_TO_SENSOR_FAMILY.get(m.group(1).strip())
            if fam:
                return fam
    return ""


def _value_to_finding(kb: Dict[str, Any], value: int) -> Optional[Finding]:
    """Розшифровує одне число Sensor Array у Finding (або None)."""
    bits = kb.get("bits", {})
    exact = kb.get("exact", {})

    # Точне значення має перевагу: воно може перекриватись із бітовою
    # декомпозицією (напр. 15 Pro 0x300000 = нижній шлейф, не «дисплей + ...»)
    if value in exact:
        comp, rec, sev = exact[value]
        return Finding(component=comp, keyword=f"0x{value:X} / {value}",
                       recommendation=rec, severity=sev)

    if value in bits:
        comp, rec, sev = bits[value]
        return Finding(component=comp, keyword=f"0x{value:X} / {value}",
                       recommendation=rec, severity=sev)

    matched = []
    for mask, info in sorted(bits.items()):
        if value & mask == mask:
            matched.append((mask, info))

    if not matched:
        return None

    names = " + ".join(m[1][0] for m in matched)
    recs = " ".join(m[1][1] for m in matched)
    sev = max((m[1][2] for m in matched),
              key=lambda s: SEVERITY_ORDER.get(s, 9))
    return Finding(
        component=names,
        keyword=f"0x{value:X} / {value} (сумарний код)",
        recommendation=(
            f"Код {hex(value)} містить кілька ознак: {names}. {recs}"
        ),
        severity=sev,
    )


def decode_sensor_array(raw_text: str, model_hint: str = "", product: str = "") -> List[Finding]:
    """Шукає в лозі рядки 'S.sensor array ... is ...' і розшифровує знайдені
    бітові маски для відповідної моделі. Аналізується тільки переданий
    релевантний блок (зазвичай panicString), а не весь журнал."""
    if not raw_text or "sensor array" not in raw_text.lower():
        return []

    family = _resolve_sensor_family(raw_text, model_hint, product=product)
    if family not in SENSOR_ARRAY_KB:
        return []

    kb = SENSOR_ARRAY_KB[family]
    array_rx = re.compile(
        r"(?:[A-Za-z]\.)?\s*sensor\s*array[\s\S]{0,40}?\bis\s+([0-9A-Fa-fxX_,\s]+)",
        re.IGNORECASE,
    )
    token_rx = re.compile(r"0[xX][0-9A-Fa-f]+|\b\d+\b")

    findings: List[Finding] = []
    seen_vals: set = set()
    for m in array_rx.finditer(raw_text):
        snippet = m.group(0)[:160].replace("\n", " ")
        for tok in token_rx.finditer(m.group(1)):
            t = tok.group(0)
            value = int(t, 16) if t.lower().startswith("0x") else int(t)
            if value == 0 or value in seen_vals:
                continue
            seen_vals.add(value)
            f = _value_to_finding(kb, value)
            if f:
                f.matched_snippet = snippet
                findings.append(f)
    return findings


def extract_hex_codes(text: str) -> List[int]:
    """Витягує 16-кові коди виду 0x…/0X… із тексту.

    Стійко до OCR-шуму: незалежно від регістру префікса (0x/0X) і наявності
    пробілів/зайвих символів навколо коду. Значення 0 і повтори — відкидаються.
    """
    if not text:
        return []
    codes, seen = [], set()
    for value, _ in _iter_hex_codes(text):
        if value in seen:
            continue
        seen.add(value)
        codes.append(value)
    return codes


def _iter_hex_codes(text: str):
    """(value, match) для кожного hex-коду 0x…/0X… у тексті."""
    for m in re.finditer(r"0[xX]\s*[0-9A-Fa-f]+", text):
        value = int(m.group(0)[2:].replace(" ", ""), 16)
        if value:
            yield value, m


def _in_sensor_context_lines(text: str, m: re.Match) -> bool:
    """Правда, якщо рядок із hex-кодом схожий на контекст SMC Sensor Array
    (а не на випадкову адресу/прапорець логу типу panicFlags '0x802')."""
    line_start = text.rfind("\n", 0, m.start()) + 1
    line_end = text.find("\n", m.end())
    if line_end == -1:
        line_end = len(text)
    line = text[line_start:line_end]
    low = line.lower()
    if "sensor" in low or "array" in low or "smc" in low:
        return True
    # Одинокий рядок-код: лише код і розділові символи навколо нього.
    rest = re.sub(r"0[xX]\s*[0-9A-Fa-f]+", " ", line)
    rest = re.sub(r"[0-9A-Fa-fxX,\s:;=\-–—()\[\]\"'`.]", " ", rest)
    return not rest.strip()


def decode_sensor_codes_from_photo(raw_text: str,
                                   model_hint: str = "") -> List[Finding]:
    """Розшифровує числові SMC-коди (напр. 0x4000) із розпізнаного фото.

    Не вимагає ідеально розпізнаного рядка «S.sensor array ... is ...»:
    спочатку пробуємо класичний рядок (включно з десятковим форматом iOS 26+),
    потім стійко витягуємо hex-коди з будь-якого sensor-рядка. Модель береться
    з вибраної групи, інакше з product-id у тексті, інакше зі стандартної
    групи «13» (щоб 0x4000 -> акумулятор навіть без підказки моделі)."""
    if not raw_text:
        return []

    family = _resolve_sensor_family(raw_text, model_hint)
    kb = SENSOR_ARRAY_KB.get(family)
    default_kb = SENSOR_ARRAY_KB["13"]

    findings: List[Finding] = []
    seen_keys: set = set()

    # 1) класичний рядок «(S.)sensor array ... is ...»
    for f in decode_sensor_array(raw_text, model_hint=model_hint):
        if f.keyword in seen_keys:
            continue
        seen_keys.add(f.keyword)
        f.matched_snippet = ""  # OCR-текст користувачу не показуємо
        findings.append(f)

    # 2) стійкий hex-розбір (OCR-шум: 0X4000, зайві пробіли/символи)
    for value, m in _iter_hex_codes(raw_text):
        target = (_value_to_finding(kb, value) if kb is not None
                  else _value_to_finding(default_kb, value))
        if target is None or target.keyword in seen_keys:
            continue
        if not _in_sensor_context_lines(raw_text, m):
            continue
        seen_keys.add(target.keyword)
        target.matched_snippet = ""
        findings.append(target)

    return findings


SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2}
SEVERITY_COLOR = {
    "critical": "#ff5c5c",
    "warning": "#ffb84d",
    "info": "#5cc8ff",
}
SEVERITY_LABEL = {
    "critical": "Критично",
    "warning": "Увага",
    "info": "Інформація",
}

# Розширення файлів логів, які приймає програма (кнопка та Drag & Drop).
SUPPORTED_LOG_EXTENSIONS = {".panic", ".ips", ".txt", ".log"}
SUPPORTED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}

# Повідомлення користувачу для OCR (точний текст за вимогами).
OCR_NO_TEXT_MSG = ("Не вдалося розпізнати текст на зображенні. "
                   "Спробуйте завантажити більш чітке фото.")
OCR_NO_KEYWORDS_MSG = "Текст розпізнано, але відомих діагностичних ключів не знайдено."


# =====================================================================================
# 2. МОДЕЛІ ДАНИХ
# =====================================================================================

@dataclass
class Finding:
    component: str
    keyword: str
    recommendation: str
    severity: str
    matched_snippet: str = ""


@dataclass
class DiagnosticReport:
    source_file: str = ""
    device_model: str = ""
    ios_version: str = ""
    serial: str = ""
    udid: str = ""
    log_timestamp: str = ""
    raw_text: str = ""
    findings: List[Finding] = field(default_factory=list)
    source_type: str = "unknown"       # "panic-full" | "panic" | "analytics" | "other" | "photo"
    panic_cause: str = ""              # перший рядок panicString («чому» впало)
    analyzed_part: str = ""            # розмір/опиc проаналізованого блоку (для прозорості)
    ocr_text: str = ""                 # текст, розпізнаний з фото/скріншоту (джерело "photo")
    matched_keywords: List[str] = field(default_factory=list)  # знайдені ключі (джерело "photo")

    @property
    def is_panic_source(self) -> bool:
        return self.source_type in ("panic-full", "panic")

    @property
    def is_photo_source(self) -> bool:
        return self.source_type == "photo"

    @property
    def verdict(self) -> str:
        if self.source_type == "photo":
            if not self.findings:
                return OCR_NO_KEYWORDS_MSG
            top = sorted(self.findings, key=lambda f: SEVERITY_ORDER.get(f.severity, 9))[0]
            return f"Ймовірна несправність: {top.component} (Код: {top.keyword})"
        if not self.is_panic_source:
            return "Проблем не виявлено. Panic Full логів не знайдено."
        if not self.findings:
            return "Явних апаратних несправностей за базою ознак не виявлено."
        top = sorted(self.findings, key=lambda f: SEVERITY_ORDER.get(f.severity, 9))[0]
        return f"Ймовірна несправність: {top.component} ({top.keyword})"


# =====================================================================================
# 3. ПАРСЕР PANIC-ЛОГІВ
# =====================================================================================

def read_text_with_auto_encoding(path: str) -> str:
    """Читає текстовий файл, автоматично визначаючи кодування.

    Спершу пробує UTF-8 (найпоширеніше для панік-логів), потім UTF-16
    (Windows-«Юнікод» з Блокнота), далі Windows-1251 та суміжні CP-кодування.
    Використовується для ручного завантаження .panic/.txt/.log файлів.
    """
    import codecs

    # 1) BOM-детекція — найнадійніше для UTF-16/UTF-8-BOM
    with open(path, "rb") as f:
        raw = f.read()

    for bom, enc in [
        (codecs.BOM_UTF8, "utf-8-sig"),
        (codecs.BOM_UTF16_LE, "utf-16"),
        (codecs.BOM_UTF16_BE, "utf-16"),
        (codecs.BOM_UTF32_LE, "utf-32"),
        (codecs.BOM_UTF32_BE, "utf-32"),
    ]:
        if raw.startswith(bom):
            try:
                return raw.decode(enc, errors="replace")
            except Exception:  # noqa: BLE001
                pass

    # 2) Строгий UTF-8 (null-байти означають, що це не текст або UTF-16 без BOM)
    try:
        text = raw.decode("utf-8")
        return text
    except UnicodeDecodeError:
        pass

    # 3) UTF-16 без BOM: велика кількість нульових байтів свідчить про UTF-16
    if len(raw) >= 4:
        zero_count = raw.count(b"\x00")
        if zero_count > len(raw) // 6:
            try:
                text = raw.decode("utf-16-le", errors="replace")
                return text.lstrip("\ufeff")
            except Exception:  # noqa: BLE001
                pass

    # 4) Windows-1251 / CP866 / latin-1 (остання ніколи не падає)
    for enc in ("cp1251", "cp866", "latin-1"):
        try:
            text = raw.decode(enc, errors="replace")
            # latin-1 завжди «успішний» — віддаємо його лише якщо інші не спрацювали
            if enc == "latin-1" and not any(ord(ch) > 0x7F for ch in text[:4096]):
                text = raw.decode("latin-1")
            return text
        except Exception:  # noqa: BLE001
            continue

    return raw.decode("latin-1", errors="replace")


def _unescape_json_block(s: str) -> str:
    """Прибрати JSON-екранування (\\n, \\/, \\" і т.п.) із блоку panicString."""
    try:
        return s.encode("utf-8").decode("unicode_escape", errors="ignore")
    except Exception:  # noqa: BLE001
        return s


def extract_panic_string_block(raw_text: str) -> str:
    """Виділити блок panicString із JSON-подібного або текстового логу.

    Формати, що підтримуються:
      * .ips / CrashLog (*.txt): JSON із ключем "panicString". Apple зберігає
        значення не строго — усередині можуть бути НЕекрановані лапки
        (panicString: "panic(...): "Msg" @File"). Тому пробуємо два різновиди
        і беремо довший блок;
      * класичний текстовий Panic Full: перший рядок "panic(cpu ...)" і тіло.
    """
    # Варіант A: суворий JSON ("\"..." всередині значення екрановане).
    candidates = []
    m = re.search(r'"panicString"\s*:\s*"((?:[^"\\]|\\.)*)"', raw_text, re.DOTALL)
    if m:
        candidates.append(_unescape_json_block(m.group(1)))

    # Варіант B: "loose" JSON Apple — значення закінчується перед ключем
    # "panicFlags", а всередині можуть бути НЕекрановані лапки (AppleTriStar
    # "Msg" @File). Витягуємо позиційно між двома ключами.
    idx = raw_text.find('"panicString"')
    if idx >= 0:
        end_mark = re.search(r'",\s*\n\s*"panicFlags"', raw_text[idx:])
        if end_mark:
            seg = raw_text[idx:idx + end_mark.start() + 1]
            colon = seg.find(":")
            open_q = seg.find('"', colon)
            if open_q >= 0 and seg[open_q + 1:open_q + 2] != "":
                block = seg[open_q + 1:-1]
                if block.strip():
                    candidates.append(_unescape_json_block(block))

    if candidates:
        # Беремо найдовший успішно витягнутий блок (релевантніші дані).
        return max(candidates, key=len)

    # Варіант 2: класичний текстовий Panic Full лог з рядком "panic(cpu ...)"
    m2 = re.search(r"panic\(cpu[^\n]*\n(.{0,4000})", raw_text, re.DOTALL)
    if m2:
        return m2.group(0)

    return ""


def clean_text_for_match(text: str) -> str:
    """Повертає текст без завідомо «шумових» фрагментів для пошуку за базою знань:
    списку завантажених драйверів (kext) і JSON-поля 'name' (список процесів
    jetsam). Без цього назви драйверів (AppleAOPAD5860, IONVMeFamily,
    AppleCS42L77Audio, ...) дають хибні спрацювання."""
    if not text:
        return text
    out_lines = []
    for ln in text.splitlines():
        s = ln.strip()
        if re.match(r"^com\.apple\.\S+\t", s) or re.match(r"^com\.apple\.[\w.]+\s+\d", s):
            continue
        out_lines.append(ln)
    res = "\n".join(out_lines)
    # JSON-описаний список драйверів у межах одного рядка (екрановані \\t / \\n):
    # com.apple.driver.AppleCS42L77Audio\t840.26  →  прибрати
    res = re.sub(r"com\.apple\.[A-Za-z0-9._+-]+\\t[0-9.;\d]+", "", res)
    res = re.sub(r'"name"\s*:\s*"[^"]*"', '"name":"?"', res)
    return res


def classify_log_source(raw_text: str, source_file: str = "") -> str:
    """Визначає тип логу за вмістом та іменем файлу.

    Повертає одне з: "panic-full" | "panic" | "analytics" | "other".
    Пріоритетний джерело для діагностики причини перезавантаження —
    саме "panic-full" (або будь-який лог, що містить panicString).
    """
    name = (source_file or "").lower()

    # panicString — головна ознака панік-блоку (і панель "pan' різдва" в .ips)
    has_panic_string = '"panicstring"' in raw_text.lower() or \
        re.search(r'panic\s*\(cpu\s*\d+', raw_text[:8000], re.IGNORECASE)

    if has_panic_string:
        return "panic-full"

    # Файл, який користувач/пристрій називає panic-логом
    if "panic" in name:
        return "panic"

    # Analytics-логи та агрегати — не джерело діагнозу
    if ("analytics" in raw_text[:4000].lower()
            or "aggregated" in raw_text[:4000].lower()
            or bool(re.search(r'"bug_type"\s*:\s*"(?!210\b)', raw_text[:2000]))):
        return "analytics"

    return "other"


def extract_relevant_fields(raw_text: str, source_file: str = "") -> Dict[str, Any]:
    """Виокремити з panic-full лише діагностично значущі поля.

    Повертає структурований словник із *релевантними* даними (panicString,
    panicFlags, kernel, build, incident_id, ...) — саме ці поля використовуються
    для аналізу, а не весь текст журналу. Для некорових типів логу (analytics,
    other) повертається порожній словник із позначкою типу.
    """
    source = classify_log_source(raw_text, source_file)

    fields: Dict[str, Any] = {
        "source_type": source,
        "has_panic_string": False,
        "panic_string": "",
        "panic_flags": "",
        "incident_id": "",
        "kernel": "",
        "build": "",
        "product": "",
        "bug_type": "",
        "timestamp": "",
    }

    if source not in ("panic-full", "panic"):
        return fields

    # Головний текст — блок panicString (тільки він нас цікавить)
    panic_string = extract_panic_string_block(raw_text)
    if panic_string:
        fields["panic_string"] = panic_string
        fields["has_panic_string"] = True
        first = panic_string.splitlines()[0] if panic_string.splitlines() else ""
        fields["panic_cause"] = first

    # Метадані з JSON-обгортки (header або body .ips)
    for pattern, key in [
        (r'"panicFlags"\s*:\s*"([^"]+)"', "panic_flags"),
        (r'"incident_id"\s*:\s*"([^"]+)"', "incident_id"),
        (r'"timestamp"\s*:\s*"([^"]+)"', "timestamp"),
        (r'"bug_type"\s*:\s*"?(\d+)"?', "bug_type"),
        (r'"build"\s*:\s*"([^"]+)"', "build"),
        (r'"product"\s*:\s*"([^"]+)"', "product"),
        (r'"kernel"\s*:\s*"([^"]+)"', "kernel"),
    ]:
        m = re.search(pattern, raw_text)
        if m:
            fields[key] = m.group(1)

    return fields


def parse_panic_log(raw_text: str, source_file: str = "",
                    model_hint: str = "") -> DiagnosticReport:
    """Головна функція аналізу panic-full логу.

    Послідовність роботи (згідно з технічним завданням):

        panic-full → parser → relevant fields/keywords → diagnosis

    1) Класифікує джерело: лише panic-full/panic вважається придатним для
       визначення причини. Analytics та інші файли НЕ аналізуються.
    2) Витягує з логу тільки діагностично значущі поля (насамперед panicString).
    3) Знаходиться за базою знань ТІЛЬКИ в цих релевантних даних.
    4) Окремо розшифровує SMC PANIC - Sensor Array (числові коди iPhone 13+),
       які містяться всередині panicString.
    """
    report = DiagnosticReport(source_file=source_file, raw_text=raw_text)

    fields = extract_relevant_fields(raw_text, source_file)
    report.source_type = fields["source_type"]

    if not report.is_panic_source:
        # Не діагностуємо причину за analytics / сторонніми логами.
        report.findings = []
        report.panic_cause = ""
        return report

    # ---- Релевантні дані для аналізу: ТІЛЬКИ panicString (не весь журнал). ----
    panic_string = fields.get("panic_string", "")
    report.panic_cause = fields.get("panic_cause", "")

    search_targets: List[str] = []
    if panic_string:
        search_targets.append(clean_text_for_match(panic_string))

    report.analyzed_part = "panicString"

    seen_components = set()
    findings: List[Finding] = []

    for target in search_targets:
        if not target:
            continue
        for entry in KNOWLEDGE_BASE:
            key = (entry["component"], entry["keyword"])
            if key in seen_components:
                continue
            match = entry["regex"].search(target)
            if match:
                snippet = target[max(0, match.start() - 40): match.end() + 40].strip()
                findings.append(Finding(
                    component=entry["component"],
                    keyword=entry["keyword"],
                    recommendation=entry["recommendation"],
                    severity=entry["severity"],
                    matched_snippet=snippet.replace("\n", " "),
                ))
                seen_components.add(key)

    # Розшифровка SMC PANIC - Sensor Array (числові коди моделей 13+)
    if panic_string and "sensor array" in panic_string.lower():
        sensor_findings = decode_sensor_array(panic_string, model_hint=model_hint,
                                              product=fields.get("product", ""))
        for f in sensor_findings:
            if (f.component, f.keyword) in seen_components:
                continue
            seen_components.add((f.component, f.keyword))
            findings.append(f)

    findings.sort(key=lambda f: SEVERITY_ORDER.get(f.severity, 9))
    report.findings = findings

    # Метадані пристрою з виокремлених релевантних полів (не весь лог)
    if fields.get("product"):
        raw_prod = fields["product"].strip()
        report.device_model = PRODUCT_NAMES.get(raw_prod, raw_prod)
    if fields.get("build"):
        report.ios_version = fields["build"]
    if fields.get("timestamp"):
        report.log_timestamp = fields["timestamp"]

    return report


# =====================================================================================
# 3.5. OCR: АНАЛІЗ ФОТОГРАФІЙ / СКРІНШОТІВ ЛОГІВ
# =====================================================================================
# Локальний розпізнавач тексту (RapidOCR на ONNX Runtime), який працює
# повністю офлайн і не передає зображення на жодні зовнішні сервіси.
# Використовується ТА САМА база знань (KNOWLEDGE_BASE), що й для panic-full.


def _looks_like_image(path: str) -> bool:
    """Визначити за сигнатурою (magic bytes), чи файл є зображенням.

    Працює навіть якщо розширення не співпадає (наприклад, PNG із назвою
    *.txt). Точніше, ніж перевірка розширення — тому використовується для
    авто-визначення «лог це чи фото».
    """
    try:
        with open(path, "rb") as f:
            head = f.read(16)
    except OSError:
        return False
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return True
    if head.startswith(b"\xff\xd8\xff"):
        return True
    return bool((len(head) >= 12 and head[:4] == b"RIFF"
                 and head[8:12] == b"WEBP"))


def _join_ocr_lines(result) -> str:
    """Перевести результат OCR у текст, упорядкований «зверху вниз».

    RapidOCR повертає список `[box, text, score]`. Групуємо рядки за
    вертикальною координатою, об'єднуючи фрагменти однієї лінії.
    """
    if not result:
        return ""
    boxes = []
    for item in result:
        if len(item) < 3:
            continue
        box, text, _score = item[0], item[1], item[2]
        try:
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            boxes.append((min(ys), min(xs), str(text or "").strip()))
        except Exception:  # noqa: BLE001
            continue
    if not boxes:
        return ""
    boxes.sort(key=lambda b: (b[0], b[1]))  # зверху донизу, зліва направо
    lines, cur, last_y = [], [], None
    for y0, _x0, text in boxes:
        if last_y is not None and y0 - last_y > 14:
            lines.append(" ".join(cur))
            cur = []
        cur.append(text)
        last_y = y0
    if cur:
        lines.append(" ".join(cur))
    return "\n".join(lines)


def _has_meaningful_text(text: str) -> bool:
    txt = (text or "").strip()
    return len(txt) >= 8 and bool(txt)


def ocr_image_to_text(path: str) -> str:
    """Локальний OCR (RapidOCR/ONNX) для фото або скріншоту логу.

    Повертає розпізнаний текст; якщо на зображенні тексту немає — порожній
    рядок. Оригінальне зображення НЕ змінюється (препроцесинг виконується
    лише для OCR-проходів). Залежності завантажуються ліниво, щоб програма
    запускалась навіть без встановленого движка OCR.
    """
    try:
        import numpy as np  # noqa: F401
        import cv2
        from rapidocr_onnxruntime import RapidOCR
    except ImportError as exc:
        raise RuntimeError(
            "OCR-движок не встановлений. Встановіть: "
            "pip install rapidocr_onnxruntime"
        ) from exc

    img = cv2.imread(path)
    if img is None:
        # cv2 не зміг прочитати (напр. екзотичний WEBP) — пробуємо через PIL.
        try:
            from PIL import Image
            pil = Image.open(path)
            img = cv2.cvtColor(np.array(pil.convert("RGB")), cv2.COLOR_RGB2BGR)
        except Exception:  # noqa: BLE001
            return ""
    if img is None:
        return ""

    engine = RapidOCR()

    def _run(variant) -> str:
        try:
            res, _ = engine(variant)
        except Exception:  # noqa: BLE001
            return ""
        return _join_ocr_lines(res)

    # Варіант 1: оригінал без змін — не погіршуємо якість джерела.
    text = _run(img)
    if _has_meaningful_text(text):
        return text

    # Варіант 2: збільшення дрібного тексту (не шкодить крупному).
    h, w = img.shape[:2]
    if h < 1000 or w < 1000:
        scale = max(2.0, 1400.0 / max(h, w))
        up = cv2.resize(img, None, fx=scale, fy=scale,
                        interpolation=cv2.INTER_CUBIC)
        text = _run(up)
        if _has_meaningful_text(text):
            return text

    # Варіант 3: градації сірого + контраст (CLAHE) для блідих фото.
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)
    text = _run(enhanced)
    if _has_meaningful_text(text):
        return text

    # Варіант 4: інверсія + поріг Оцу для темного фону (білий текст).
    inv = cv2.bitwise_not(gray)
    _, thr = cv2.threshold(inv, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    text = _run(thr)
    if text.strip():
        return text

    return ""


def analyze_ocr_text(raw_text: str, source_file: str = "",
                     model_hint: str = "") -> DiagnosticReport:
    """Аналіз тексту, розпізнаного з фото/скріншоту (OCR).

    Використовує ТУ Ж саму базу знань (KNOWLEDGE_BASE), що й panic-full.
    Джерело позначається як "photo". Пошук ключів — точний (regex-збіг по
    базі), fuzzy-пошук НЕ застосовується за замовчуванням. SMC Sensor Array
    розшифровується, якщо присутній у розпізнаному тексті.
    """
    report = DiagnosticReport(source_file=source_file, raw_text=raw_text)
    report.source_type = "photo"
    report.analyzed_part = "OCR-текст (розпізнаний з фото)"
    report.ocr_text = raw_text

    target = clean_text_for_match(raw_text or "")
    if not target.strip():
        return report

    findings: List[Finding] = []
    seen_components = set()
    for entry in KNOWLEDGE_BASE:
        key = (entry["component"], entry["keyword"])
        if key in seen_components:
            continue
        match = entry["regex"].search(target)
        if match:
            findings.append(Finding(
                component=entry["component"],
                keyword=entry["keyword"],
                recommendation=entry["recommendation"],
                severity=entry["severity"],
                matched_snippet="",  # OCR-контекст користувачу не показуємо
            ))
            seen_components.add(key)

    # SMC-коди з фото (напр. 0x4000 -> акумулятор). Стійкий розбір: не
    # вимагає ідеально розпізнаного рядка 'sensor array ... is ...'.
    sensor_findings = decode_sensor_codes_from_photo(raw_text, model_hint=model_hint)
    for f in sensor_findings:
        if (f.component, f.keyword) in seen_components:
            continue
        seen_components.add((f.component, f.keyword))
        findings.append(f)

    findings.sort(key=lambda f: SEVERITY_ORDER.get(f.severity, 9))
    report.findings = findings
    report.matched_keywords = [f.keyword for f in findings]
    return report


# =====================================================================================
# 4. ФОНОВИЙ ПОТІК ДЛЯ РОБОТИ З ПРИСТРОЄМ (pymobiledevice3)
# =====================================================================================
# Примітка: API pymobiledevice3 періодично змінюється між версіями.
# Нижче використано найбільш стабільний і широко сумісний шлях доступу —
# через CrashReportsManager (сервіс com.apple.crashreportcopymobile),
# який на iOS зберігає копії панік-логів у теці CrashReports/.
# Якщо у встановленій версії бібліотеки назви класів відрізняються,
# скоригуйте імпорти нижче відповідно до `pip show pymobiledevice3`
# та документації https://github.com/doronz88/pymobiledevice3

class DeviceWorker(QThread):
    """Фоновий потік: підключення до пристрою, отримання інформації та
    зчитування Panic-логів. Виконується окремо від GUI-потоку, щоб
    інтерфейс не "зависав" під час операцій з USB."""

    device_connected = pyqtSignal(dict)          # інформація про пристрій
    device_disconnected = pyqtSignal()
    logs_found = pyqtSignal(list)                # список знайдених panic-логів (dict)
    error_occurred = pyqtSignal(str)
    progress = pyqtSignal(str)

    def __init__(self, mode: str = "detect", parent=None):
        super().__init__(parent)
        self.mode = mode  # "detect" -> лише інформація, "fetch_logs" -> ще й логи

    def run(self):
        try:
            import asyncio
            asyncio.run(self._run_impl())
        except Exception as exc:  # noqa: BLE001 — навмисно широкий catch для GUI-стабільності
            tb = traceback.format_exc()
            self.error_occurred.emit(
                f"Помилка звʼязку з пристроєм: {exc}\n\n"
                f"Перевірте, що iPhone розблокований, ви натиснули "
                f"«Довіряти цьому компʼютеру», встановлено iTunes / Apple "
                f"Mobile Device Support і служба Apple Mobile Device Service "
                f"запущена.\n\nТехнічні деталі:\n{tb}"
            )

    async def _run_impl(self):
        self.progress.emit("Пошук підключеного iPhone...")
        try:
            from pymobiledevice3.lockdown import create_using_usbmux
            from pymobiledevice3.exceptions import (
                NoDeviceConnectedError, PasswordRequiredError, ConnectionFailedToUsbmuxdError,
            )
        except ImportError:
            self.error_occurred.emit(
                "Бібліотека pymobiledevice3 не встановлена.\n"
                "Встановіть її командою: pip install pymobiledevice3\n\n"
                "Ви можете скористатися кнопкою «Завантажити файл вручну», "
                "поки бібліотека не встановлена."
            )
            return

        lockdown = None
        try:
            lockdown = await create_using_usbmux()
        except ConnectionFailedToUsbmuxdError:
            self.error_occurred.emit(
                "Не вдалося звʼязатися зі службою usbmuxd / Apple Mobile "
                "Device Service. Встановіть iTunes з офіційного сайту Apple "
                "(не з Microsoft Store) і переконайтесь, що служба "
                "'Apple Mobile Device Service' запущена (services.msc)."
            )
            return
        except NoDeviceConnectedError:
            self.error_occurred.emit(
                "iPhone не знайдено. Підключіть пристрій USB-кабелем, "
                "розблокуйте екран і натисніть «Довіряти», якщо з'явиться "
                "запит. Або скористайтесь кнопкою «Завантажити файл вручну»."
            )
            return
        except PasswordRequiredError:
            self.error_occurred.emit(
                "Пристрій заблокований або потребує підтвердження довіри. "
                "Розблокуйте iPhone та натисніть «Довіряти цьому компʼютеру»."
            )
            return

        try:
            product_type = lockdown.product_type if hasattr(lockdown, "product_type") else "Невідомо"
            product_version = lockdown.product_version if hasattr(lockdown, "product_version") else "Невідомо"
            serial = ""
            udid = ""
            try:
                serial = await lockdown.get_value(key="SerialNumber")
            except Exception:  # noqa: BLE001
                try:
                    serial = lockdown.serial_number
                except Exception:  # noqa: BLE001
                    serial = "Невідомо"
            udid = getattr(lockdown, "udid", "") or ""
        except Exception:  # noqa: BLE001
            product_type = "Невідомо"
            product_version = "Невідомо"
            serial = "Невідомо"
            udid = ""

        info = {
            "model": product_type,
            "ios_version": product_version,
            "serial": serial,
            "udid": udid,
        }
        self.device_connected.emit(info)

        if self.mode != "fetch_logs":
            return

        self.progress.emit("Зчитування Panic-логів з пристрою...")
        found_logs = []
        try:
            from pymobiledevice3.services.crash_reports import CrashReportsManager

            async with CrashReportsManager(lockdown=lockdown) as crash_manager:
                # Повне рекурсивне перелічення: panic-full-*.ips на сучасних
                # iOS знаходяться глибше ніж розкриває ls(/, depth=2), напр. у
                # /DiagnosticLogs/PanicLogs/. Обираємо ЛИШЕ звичайні файли
                # (S_IFREG), ігноруючи каталоги (напр. сам /DiagnosticLogs/
                # або .../PanicLogs/, які "panic" лише в назві).
                entries = await crash_manager.ls("/", depth=-1)
                candidates = []
                for entry in entries:
                    name = entry if isinstance(entry, str) else str(entry)
                    low = name.lower()
                    if "panic" not in low:
                        continue
                    try:
                        st = await crash_manager.afc.stat(name)
                        if st.get("st_ifmt") != "S_IFREG":
                            continue
                    except Exception:  # noqa: BLE001
                        continue
                    candidates.append(name)

                # Пріоритет: спочатку panic-full (за назвою файлу швидше),
                # новіші — раніше (дата зазвичай є у назві panic-full-*-*.ips).
                def _panic_key(n):
                    return (0 if "panic-full" in n.lower() else 1, n.lower())

                candidates.sort(key=_panic_key)

                if not candidates:
                    self.progress.emit(
                        "Проблем не виявлено. Panic Full логів не знайдено."
                    )
                    self.logs_found.emit([])
                    return

                # Читаємо максимум кілька найрелевантніших панік-логів,
                # щоб не вивантажувати/не аналізувати зайві файли.
                for name in candidates[:6]:
                    try:
                        data = await crash_manager.afc.get_file_contents(name)
                    except Exception:  # noqa: BLE001
                        data = None
                    content = data.decode("utf-8", errors="ignore") if isinstance(data, (bytes, bytearray)) else (data or "")
                    found_logs.append({
                        "name": name,
                        "content": content,
                        "date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
                    })
        except ImportError:
            self.error_occurred.emit(
                "У цій версії pymobiledevice3 не знайдено модуль "
                "crash_reports. Оновіть бібліотеку: "
                "pip install --upgrade pymobiledevice3, або скористайтесь "
                "кнопкою «Завантажити файл вручну» разом із утилітою "
                "3uTools / Xcode Devices для попереднього вивантаження логів."
            )
            return
        except Exception as exc:  # noqa: BLE001
            self.error_occurred.emit(
                f"Не вдалося прочитати панік-логи з пристрою: {exc}\n"
                f"Скористайтесь кнопкою «Завантажити файл вручну», якщо у "
                f"вас вже є експортований .panic/.ips файл (наприклад, "
                f"через Xcode -> Window -> Devices and Simulators -> "
                f"View Device Logs, або через 3uTools)."
            )
            return

        if lockdown is not None and hasattr(lockdown, "aclose"):
            try:
                await lockdown.aclose()
            except Exception:  # noqa: BLE001
                pass

        if not found_logs:
            self.progress.emit(
                "Проблем не виявлено. Panic Full логів не знайдено."
            )
        self.logs_found.emit(found_logs)


class InstallWorker(QThread):
    """Фоновий потік встановлення pymobiledevice3 через pip."""

    log = pyqtSignal(str)
    finished_ok = pyqtSignal()
    failed = pyqtSignal(str)

    def run(self):
        try:
            self._run_impl()
            self.finished_ok.emit()
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))

    def _run_impl(self):
        import subprocess

        def run(cmd):
            proc = subprocess.run(
                cmd,
                shell=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            if proc.stdout:
                self.log.emit(proc.stdout.strip())
            if proc.stderr:
                self.log.emit(proc.stderr.strip())
            return proc.returncode, proc.stdout + proc.stderr

        self.log.emit("Перевірка Python/pip...")
        code, out = run([sys.executable, "-m", "pip", "--version"])
        if code != 0:
            # Спроба через "pip"
            code, out = run(["pip", "--version"])
            if code != 0:
                raise RuntimeError(
                    "Не знайдено pip. Встановіть Python з опцією "
                    "'Add python.exe to PATH'."
                )

        self.log.emit("Оновлення pip...")
        run([sys.executable, "-m", "pip", "install", "--upgrade", "pip"])

        # Крок 1: встановлюємо pymobiledevice3 без залежностей.
        # Це робиться для того, щоб уникнути спроби зібрати C-модуль
        # 'lzfse', який вимагає Microsoft C++ Build Tools (компілятор).
        # lzfse потрібен лише для роботи з IPSW/прошивками, а для
        # зчитування панік-логів він НЕ потрібен.
        self.log.emit("Встановлення pymobiledevice3 (без C-залежностей)...")
        code, out = run([sys.executable, "-m", "pip", "install", "--no-deps", "pymobiledevice3"])
        if code != 0:
            raise RuntimeError(
                "Не вдалося встановити pymobiledevice3: " + (out or "невідома помилка")
            )

        # Крок 2: встановлюємо необхідні Python-залежності (усі вони
        # чисто Python і НЕ потребують компілятора C).
        self.log.emit("Встановлення Python-залежностей...")
        deps = (
            "construct construct-typing asn1 coloredlogs pygments hexdump "
            "tqdm requests packaging typing_extensions cryptography "
            "pycrashreport pyusb ifaddr hyperframe srptools psutil "
            "prompt_toolkit plumbum bpylist2 parameter_decorators pygnuutils "
            "defusedxml backports.zstd python-dateutil pywin32 typer-injector "
            "uvicorn wsproto xonsh daemonize gpxpy pykdebugparser questionary "
            "opack2 pmd-pytcp python-pcapng IPython matplotlib-inline "
            "pytun-pmd3 'qh3<2' pyiosbackup"
        )
        code, out = run(
            [sys.executable, "-m", "pip", "install", *deps.split()]
        )
        if code != 0:
            raise RuntimeError(
                "Не вдалося встановити залежності: " + (out or "невідома помилка")
            )

        # Крок 3: перевірка, що критичні модулі для роботи з пристроєм
        # імпортуються (без lzfse).
        self.log.emit("Перевірка результату...")
        try:
            from pymobiledevice3.lockdown import create_using_usbmux  # noqa: F401
            from pymobiledevice3.services.crash_reports import CrashReportsManager  # noqa: F401
        except ImportError as exc:
            raise RuntimeError(
                "Бібліотека встановлена, але не імпортується: " + str(exc)
            ) from exc


class OcrWorker(QThread):
    """Фоновий потік: локальне розпізнавання тексту з фото/скріншоту.

    OCR виконується поза GUI-потоком (розпізнавання займає кілька секунд),
    щоб вікно не «зависало». Результат передається сигналом `done(str)`,
    помилка — `failed(str)`.
    """

    done = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, path: str, parent=None):
        super().__init__(parent)
        self.path = path

    def run(self):
        try:
            text = ocr_image_to_text(self.path)
            self.done.emit(text or "")
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


class UpdateCheckWorker(QThread):
    """Фоновий потік: перевірка latest release PanicIF на GitHub.

    Мережевий запит виконується поза GUI-потоком (із таймаутом), щоб вікно
    не зависало. Результат: `result(dict)` або `failed(kind)`.
    """

    result = pyqtSignal(dict)
    failed = pyqtSignal(str, str)  # (kind, detail)

    def __init__(self, current_version: str, parent=None):
        super().__init__(parent)
        self.current_version = current_version

    def run(self):
        try:
            release = fetch_latest_release()
            latest = get_latest_tag(release)
            available = is_update_available(self.current_version, latest)
            self.result.emit(
                {
                    "available": available,
                    "latest": latest,
                    "release": release,
                }
            )
        except UpdaterError as exc:
            self._emit_error(exc)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit("unknown", str(exc))

    def _emit_error(self, exc):
        if isinstance(exc, UpdaterNetworkError):
            kind = "network"
        elif isinstance(exc, UpdaterServerError):
            kind = "server"
        elif isinstance(exc, UpdaterIntegrityError):
            kind = "integrity"
        else:
            kind = "data"
        self.failed.emit(kind, str(exc))


class UpdateDownloadWorker(QThread):
    """Фоновий потік: завантаження PanicIF-Setup.exe та перевірка цілісності."""

    progress = pyqtSignal(int, int)  # (bytes, total або -1)
    downloaded = pyqtSignal(str)
    failed = pyqtSignal(str, str)  # (kind, detail)

    def __init__(self, url: str, digest_url: str = "", parent=None):
        super().__init__(parent)
        self.url = url
        self.digest_url = digest_url

    def run(self):
        try:
            path = download_asset(self.url, progress_callback=self._report_progress)
            if self.digest_url:
                expected = fetch_digest(self.digest_url)
                if expected and not digest_matches(path, expected):
                    self.failed.emit("integrity", "SHA-256 не збігається.")
                    return
            self.downloaded.emit(path)
        except (UpdaterDataError, UpdaterNetworkError) as exc:
            self.failed.emit("download", str(exc))
        except UpdaterIntegrityError:
            self.failed.emit("integrity", "SHA-256 не збігається.")
        except Exception as exc:  # noqa: BLE001
            self.failed.emit("unknown", str(exc))

    def _report_progress(self, got: int, total):
        self.progress.emit(got, total if total else -1)


# =====================================================================================
# 5. ЕКСПОРТ ЗВІТУ (TXT / PDF)
# =====================================================================================

def build_text_report(report: DiagnosticReport) -> str:
    is_photo = report.source_type == "photo"
    lines = []
    lines.append("=" * 70)
    lines.append("ЗВІТ ДІАГНОСТИКИ iPhone (LOG АБО OCR-ФОТО)")
    lines.append("=" * 70)
    lines.append(f"Дата формування звіту: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    if report.source_file:
        lines.append(f"Джерело логу: {report.source_file}")
    lines.append(f"Тип джерела: {'Фото / OCR' if is_photo else report.source_type}")
    if report.device_model:
        lines.append(f"Модель пристрою: {report.device_model}")
    if report.ios_version:
        lines.append(f"Версія iOS: {report.ios_version}")
    if report.serial:
        lines.append(f"Серійний номер: {report.serial}")
    if report.udid:
        lines.append(f"UDID: {report.udid}")
    if report.log_timestamp:
        lines.append(f"Мітка часу логу: {report.log_timestamp}")
    lines.append("-" * 70)
    lines.append("ВЕРДИКТ:")
    lines.append(report.verdict)
    lines.append("-" * 70)

    if is_photo:
        if report.matched_keywords:
            lines.append("ЗНАЙДЕНІ КЛЮЧОВІ СЛОВА:")
            lines.append(", ".join(report.matched_keywords))
            lines.append("")
    elif not report.is_panic_source:
        lines.append("Panic Full логів не знайдено, тому причина не визначалась.")
    elif report.panic_cause:
        lines.append("ПРИЧИНА (перший рядок panicString):")
        lines.append(report.panic_cause)
        lines.append("")

    if report.findings:
        lines.append("ДЕТАЛЬНІ ЗНАХІДКИ:")
        for i, f in enumerate(report.findings, 1):
            lines.append("")
            lines.append(f"{i}. [{SEVERITY_LABEL.get(f.severity, f.severity)}] Компонент: {f.component}")
            lines.append(f"   Ключове слово: {f.keyword}")
            lines.append(f"   Рекомендація: {f.recommendation}")
            if f.matched_snippet:
                lines.append(f"   Контекст у лозі: ...{f.matched_snippet}...")
    elif report.is_panic_source or is_photo:
        lines.append("Збігів за базою знань не знайдено.")

    lines.append("")
    lines.append("=" * 70)
    lines.append("Звіт сформовано автоматично. Остаточний діагноз має "
                  "підтверджуватись майстром на основі повторної перевірки.")
    lines.append("=" * 70)
    return "\n".join(lines)


def _register_pdf_fonts():
    """Реєструє TTF-шрифт із підтримкою кирилиці для reportlab.

    Повертає (font_normal, font_bold), або None, якщо жодного системного
    TTF не знайдено (тоді залишається стандартний Helvetica)."""
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
    except ImportError:
        return None

    candidates = [
        ("SegoeUI", ("C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/segoeuib.ttf",
                     "C:/Windows/Fonts/segoeuii.ttf")),
        ("Arial", ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf",
                   "C:/Windows/Fonts/ariali.ttf")),
    ]
    for family, (reg_f, bold_f, italic_f) in candidates:
        if not (os.path.exists(reg_f) and os.path.exists(bold_f)):
            continue
        has_italic = os.path.exists(italic_f)
        pdfmetrics.registerFont(TTFont(family, reg_f))
        pdfmetrics.registerFont(TTFont(family + "-Bold", bold_f))
        if has_italic:
            pdfmetrics.registerFont(TTFont(family + "-Italic", italic_f))
        pdfmetrics.registerFontFamily(
            family,
            normal=family,
            bold=family + "-Bold",
            italic=(family + "-Italic" if has_italic else family),
            boldItalic=family + "-Bold",
        )
        return family, family + "-Bold"
    return None


def export_txt(report: DiagnosticReport, path: str):
    with open(path, "w", encoding="utf-8") as f:
        f.write(build_text_report(report))


def export_pdf(report: DiagnosticReport, path: str):
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.lib import colors
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
        )
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    except ImportError as exc:
        raise RuntimeError(
            "Бібліотека reportlab не встановлена. Встановіть її командою: "
            "pip install reportlab"
        ) from exc

    styles = getSampleStyleSheet()
    pdf_fonts = _register_pdf_fonts()
    font_normal = pdf_fonts[0] if pdf_fonts else "Helvetica"
    font_bold = pdf_fonts[1] if pdf_fonts else "Helvetica-Bold"
    title_style = ParagraphStyle(
        "TitleUA", parent=styles["Title"], fontSize=16, spaceAfter=10,
        fontName=font_bold
    )
    normal = ParagraphStyle("NormalUA", parent=styles["Normal"], fontName=font_normal)
    bold = ParagraphStyle("BoldUA", parent=normal, fontName=font_bold)

    # Стилі клітинок таблиці: довгий текст переноситься всередині комірки
    # (splitLongWords дозволяє рвати наддовгі слова), висота рядка
    # автоматично обчислюється ReportLab з Paragraph.
    cell_st = ParagraphStyle(
        "CellUA", parent=normal, fontSize=7.5, leading=9.5,
        splitLongWords=1, wordWrap="LTR"
    )
    cell_bold_st = ParagraphStyle("CellBoldUA", parent=cell_st, fontName=font_bold)
    cell_head_st = ParagraphStyle(
        "CellHeadUA", parent=cell_st, fontName=font_bold, textColor=colors.white
    )
    meta_key_st = ParagraphStyle("MetaKeyUA", parent=normal, fontName=font_bold, fontSize=9)
    meta_val_st = ParagraphStyle("MetaValUA", parent=normal, fontSize=9)

    def _pdf_escape(text) -> str:
        """Безпечний текст для Paragraph: екранує XML-спецсимволи."""
        from xml.sax.saxutils import escape as _xml_escape
        return _xml_escape(str(text or "")).replace("\n", "<br/>")

    def _para(text, style) -> Paragraph:
        return Paragraph(_pdf_escape(text), style)

    # Доступна ширина сторінки A4 за мінусом полів (18mm з кожного боку).
    _avail_w = A4[0] - 2 * 18 * mm

    def _fit_col_widths(widths, available=_avail_w):
        total = sum(widths)
        if total <= available:
            return widths
        scale = available / total
        return [w * scale for w in widths]

    doc = SimpleDocTemplate(path, pagesize=A4,
                             leftMargin=18 * mm, rightMargin=18 * mm,
                             topMargin=16 * mm, bottomMargin=16 * mm)
    story = []
    story.append(Paragraph("Звіт діагностики iPhone (Log або OCR-фото)", title_style))
    story.append(Paragraph(
        f"Дата формування: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", normal
    ))
    meta_rows = []
    if report.source_file:
        meta_rows.append(["Джерело логу", report.source_file])
    meta_rows.append(
        ["Тип джерела", "Фото / OCR" if report.source_type == "photo"
         else report.source_type]
    )
    if report.device_model:
        meta_rows.append(["Модель пристрою", report.device_model])
    if report.ios_version:
        meta_rows.append(["Версія iOS", report.ios_version])
    if report.serial:
        meta_rows.append(["Серійний номер", report.serial])
    if report.udid:
        meta_rows.append(["UDID", report.udid])
    if report.log_timestamp:
        meta_rows.append(["Мітка часу логу", report.log_timestamp])
    if meta_rows:
        meta_td = [[_para(k, meta_key_st), _para(v, meta_val_st)] for k, v in meta_rows]
        t = Table(meta_td, colWidths=_fit_col_widths([120, 320]))
        t.setStyle(TableStyle([
            ("GRID", (0, 0), (0, -1), 0.4, colors.grey),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        story.append(Spacer(1, 8))
        story.append(t)

    story.append(Spacer(1, 12))
    story.append(Paragraph("Вердикт", bold))
    story.append(_para(report.verdict, normal))
    if report.source_type == "photo":
        # Фото/OCR: показуємо лише знайдені ключові слова (без сирого тексту).
        story.append(Spacer(1, 6))
        if report.matched_keywords:
            story.append(Paragraph("Знайдені ключові слова:", bold))
            story.append(_para(", ".join(report.matched_keywords), normal))
    elif not report.is_panic_source:
        story.append(_para(
            "Panic Full логів не знайдено, тому причина не визначалась.", normal
        ))
    elif report.panic_cause:
        story.append(Spacer(1, 6))
        story.append(Paragraph("Причина (перший рядок panicString):", bold))
        story.append(_para(report.panic_cause, normal))
    story.append(Spacer(1, 12))

    if report.findings:
        story.append(Paragraph("Детальні знахідки", bold))
        story.append(Spacer(1, 6))
        table_data = [[
            "#", "Рівень", "Компонент", "Ключове слово", "Рекомендація"
        ]]
        table_data[0] = [_para(h, cell_head_st) for h in table_data[0]]
        for i, f in enumerate(report.findings, 1):
            table_data.append([
                _para(str(i), cell_st),
                _para(SEVERITY_LABEL.get(f.severity, f.severity), cell_st),
                _para(f.component, cell_st),
                _para(f.keyword, cell_st),
                _para(f.recommendation, cell_st),
            ])
        tbl = Table(
            table_data, colWidths=_fit_col_widths([16, 60, 90, 95, 180]),
            repeatRows=1
        )
        tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#333333")),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f2f2f2")]),
        ]))
        story.append(tbl)
    else:
        story.append(Paragraph("Збігів за базою знань не знайдено.", normal))

    story.append(Spacer(1, 16))
    story.append(_para(
        "Звіт сформовано автоматично. Остаточний діагноз має підтверджуватись "
        "майстром на основі повторної перевірки пристрою.", normal
    ))

    doc.build(story)


# =====================================================================================
# 6. ТЕМНА ТЕМА (QSS)
# =====================================================================================

DARK_STYLESHEET = """
QMainWindow, QWidget {
    background-color: #1e1f24;
    color: #e8e8ea;
    font-family: 'Segoe UI', sans-serif;
    font-size: 13px;
}
QLabel#StatusLabel {
    font-size: 15px;
    font-weight: 600;
    padding: 4px 10px;
    border-radius: 6px;
}
QLabel#DeviceInfoLabel {
    color: #b8b9c0;
    font-size: 12px;
}
QFrame#TopBar {
    background-color: #26272e;
    border-bottom: 1px solid #34353d;
}
QFrame#Card {
    background-color: #26272e;
    border-radius: 10px;
    border: 1px solid #34353d;
}
QPushButton {
    background-color: #34353d;
    color: #e8e8ea;
    border: none;
    border-radius: 6px;
    padding: 8px 14px;
    font-weight: 500;
}
QPushButton:hover {
    background-color: #3f414b;
}
QPushButton:pressed {
    background-color: #2a2b31;
}
QPushButton:disabled {
    background-color: #2a2b31;
    color: #6a6b73;
}
QPushButton#PrimaryButton {
    background-color: #3d7bfd;
    color: white;
}
QPushButton#PrimaryButton:hover {
    background-color: #5c8fff;
}
QListWidget, QTextEdit, QPlainTextEdit, QTableWidget {
    background-color: #17181c;
    border: 1px solid #34353d;
    border-radius: 6px;
    color: #e8e8ea;
    gridline-color: #34353d;
}
QHeaderView::section {
    background-color: #26272e;
    color: #b8b9c0;
    padding: 6px;
    border: none;
    border-bottom: 1px solid #34353d;
}
QListWidget::item {
    padding: 8px;
    border-bottom: 1px solid #2a2b31;
}
QListWidget::item:selected {
    background-color: #3d7bfd;
    color: white;
}
QGroupBox {
    border: 1px solid #34353d;
    border-radius: 8px;
    margin-top: 12px;
    font-weight: 600;
    padding-top: 10px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 6px;
    color: #b8b9c0;
}
QProgressBar {
    border: 1px solid #34353d;
    border-radius: 6px;
    text-align: center;
    background-color: #17181c;
}
QProgressBar::chunk {
    background-color: #3d7bfd;
    border-radius: 6px;
}
QScrollBar:vertical {
    background: #1e1f24;
    width: 10px;
}
QScrollBar::handle:vertical {
    background: #3f414b;
    border-radius: 5px;
}
"""


# =====================================================================================
# 7. ГОЛОВНЕ ВІКНО
# =====================================================================================

class LogDropZone(QFrame):
    """Зона прийому файлів логів через Drag & Drop.

    Приймає локальні файли та папки і передає список їх шляхів сигналом
    `filesDropped`. Імпорт виконується ТІЄЮ САМОЮ логікою, що й кнопка
    «Завантажити .panic/.txt файл вручну».
    """

    filesDropped = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("DropZone")
        self.setAcceptDrops(True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 6, 10, 6)
        lay.setSpacing(2)
        self.drop_hint = QLabel("📥 Перетягніть файл логу або фото сюди")
        self.drop_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.drop_hint.setStyleSheet("font-weight: 600; color: #c8c9d0;")
        self.drop_sub = QLabel(
            "логи: .panic .ips .txt .log  ·  фото: .png .jpg .jpeg .webp"
        )
        self.drop_sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.drop_sub.setStyleSheet("font-size: 11px; color: #6a6b73;")
        lay.addWidget(self.drop_hint)
        lay.addWidget(self.drop_sub)
        self._set_dragging(False)

    def _set_dragging(self, active: bool):
        style = (
            "QFrame#DropZone { border: 2px dashed #5c8fff; border-radius: 8px; "
            "background-color: rgba(93,143,255,0.14); }"
            if active else
            "QFrame#DropZone { border: 2px dashed #4a4b55; border-radius: 8px; "
            "background-color: #17181c; }"
        )
        self.setStyleSheet(style)

    def dragEnterEvent(self, event):  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self._set_dragging(True)
        else:
            event.ignore()

    def dragLeaveEvent(self, event):  # noqa: N802
        self._set_dragging(False)
        event.accept()

    def dropEvent(self, event):  # noqa: N802
        self._set_dragging(False)
        mime = event.mimeData()
        if not mime.hasUrls():
            event.ignore()
            return
        paths = [u.toLocalFile() for u in mime.urls() if u.isLocalFile()]
        event.acceptProposedAction()
        if paths:
            self.filesDropped.emit(paths)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} {APP_VERSION}")
        self.resize(1280, 800)

        self.current_report: Optional[DiagnosticReport] = None
        self.device_info: Dict[str, Any] = {}
        self.loaded_logs: List[Dict[str, str]] = []  # [{name, content, date}]

        self._build_ui()
        self._connect_signals()

    # ------------------------------------------------------------------ UI BUILD
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        root_layout.addWidget(self._build_top_bar())

        body = QSplitter(Qt.Orientation.Horizontal)
        body.setContentsMargins(10, 10, 10, 10)
        body.addWidget(self._build_left_panel())
        body.addWidget(self._build_center_panel())
        body.setSizes([320, 960])
        root_layout.addWidget(body, stretch=1)

        root_layout.addWidget(self._build_bottom_bar())

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)  # indeterminate
        self.progress_bar.setVisible(False)
        self.progress_bar.setFixedHeight(4)
        self.progress_bar.setTextVisible(False)
        root_layout.addWidget(self.progress_bar)

    def _build_top_bar(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("TopBar")
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(16, 12, 16, 12)

        self.status_label = QLabel("● Очікування підключення iPhone...")
        self.status_label.setObjectName("StatusLabel")
        self._set_status_color("waiting")
        layout.addWidget(self.status_label)

        layout.addSpacing(20)

        self.device_info_label = QLabel(
            "Модель: —    Версія iOS: —    Серійний номер: —    UDID: —"
        )
        self.device_info_label.setObjectName("DeviceInfoLabel")
        layout.addWidget(self.device_info_label, stretch=1)

        self.refresh_btn = QPushButton("🔄 Перевірити підключення")
        layout.addWidget(self.refresh_btn)

        return frame

    def _build_left_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)

        actions_box = QGroupBox("Дії")
        actions_layout = QVBoxLayout(actions_box)
        self.read_device_btn = QPushButton("📲 Зчитати Panic Logs з пристрою")
        self.read_device_btn.setObjectName("PrimaryButton")
        self.load_file_btn = QPushButton("📁 Завантажити .panic/.txt файл вручну")
        self.load_photo_btn = QPushButton("🖼 Розпізнати текст з фото (OCR)")
        self.install_btn = QPushButton("⬇ Встановити pymobiledevice3")
        actions_layout.addWidget(self.read_device_btn)
        actions_layout.addWidget(self.load_file_btn)
        actions_layout.addWidget(self.load_photo_btn)
        actions_layout.addWidget(self.install_btn)

        model_label = QLabel("Модель iPhone:")
        model_label.setStyleSheet("color: #b8b9c0; margin-top: 8px;")
        actions_layout.addWidget(model_label)
        self.model_combo = QComboBox()
        self.model_combo.addItem("АВТО (визначити з логу)", "")
        for fam_key, fam_data in SENSOR_ARRAY_KB.items():
            self.model_combo.addItem(fam_data["label"], fam_key)
        self.model_combo.setToolTip(
            "Впливає на розшифровку числових кодів 'SMC PANIC - Sensor Array'. "
            "Режим АВТО визначає модель з product-id у самому логу."
        )
        actions_layout.addWidget(self.model_combo)
        layout.addWidget(actions_box)

        # Зона Drag & Drop — імпортує логи ТИМ САМИМ механізмом, що й кнопка.
        self.drop_zone = LogDropZone()
        layout.addWidget(self.drop_zone)

        logs_box = QGroupBox("Знайдені логи")
        logs_layout = QVBoxLayout(logs_box)
        self.logs_list = QListWidget()
        self.logs_list.setMinimumHeight(300)
        logs_layout.addWidget(self.logs_list)
        layout.addWidget(logs_box, stretch=1)

        return panel

    def _build_center_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)

        # Картка вердикту
        self.verdict_frame = QFrame()
        self.verdict_frame.setObjectName("Card")
        v_layout = QVBoxLayout(self.verdict_frame)
        self.verdict_title = QLabel("Вердикт з'явиться тут після аналізу логу")
        self.verdict_title.setWordWrap(True)
        self.verdict_title.setStyleSheet("font-size: 17px; font-weight: 700;")
        v_layout.addWidget(self.verdict_title)
        self.verdict_subtitle = QLabel(
            "Зчитайте логи з пристрою або завантажте файл вручну, щоб почати діагностику."
        )
        self.verdict_subtitle.setWordWrap(True)
        self.verdict_subtitle.setStyleSheet("color: #b8b9c0;")
        v_layout.addWidget(self.verdict_subtitle)
        layout.addWidget(self.verdict_frame)

        # Таблиця деталей
        details_box = QGroupBox("Детальні результати діагностики")
        details_layout = QVBoxLayout(details_box)
        self.details_table = QTableWidget(0, 4)
        self.details_table.setHorizontalHeaderLabels(
            ["Рівень", "Компонент", "Ключове слово / сенсор", "Рекомендація"]
        )
        self.details_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.Stretch
        )
        self.details_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self.details_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents
        )
        self.details_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.details_table.verticalHeader().setVisible(False)
        details_layout.addWidget(self.details_table, stretch=1)
        layout.addWidget(details_box, stretch=1)

        # Raw-перегляд сирого логу у зручному текстовому полі
        raw_box = QGroupBox("Сирий текст логу (Raw Panic)")
        raw_layout = QVBoxLayout(raw_box)
        self.raw_text_edit = QPlainTextEdit()
        self.raw_text_edit.setReadOnly(True)
        self.raw_text_edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.raw_text_edit.setPlaceholderText("Сирий текст логу з'явиться тут...")
        self.raw_text_edit.document().setMaximumBlockCount(0)
        raw_layout.addWidget(self.raw_text_edit)
        layout.addWidget(raw_box, stretch=1)
        self._raw_box = raw_box
        self._details_box = details_box

        return panel

    def _build_bottom_bar(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("TopBar")
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(16, 10, 16, 10)

        self.view_mode_btn = QToolButton()
        self.view_mode_btn.setText("👁 Переглянути сирий лог (Raw Panic)")
        self.view_mode_btn.setCheckable(True)
        layout.addWidget(self.view_mode_btn)

        self.check_update_btn = QPushButton("⤓ Перевірити оновлення")
        layout.addWidget(self.check_update_btn)

        layout.addStretch(1)

        donate_box = QWidget()
        donate_layout = QVBoxLayout(donate_box)
        donate_layout.setContentsMargins(0, 0, 0, 0)
        donate_layout.setSpacing(4)
        self.donate_label = QLabel("💛 Задонатити на розвиток проєкту")
        self.donate_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.donate_btn = QPushButton("Підтримати автора")
        self.donate_btn.setObjectName("PrimaryButton")
        donate_layout.addWidget(self.donate_label)
        donate_layout.addWidget(self.donate_btn)
        layout.addWidget(donate_box, alignment=Qt.AlignmentFlag.AlignCenter)

        layout.addStretch(1)

        self.save_txt_btn = QPushButton("💾 Зберегти звіт (TXT)")
        self.save_pdf_btn = QPushButton("💾 Зберегти звіт (PDF)")
        self.save_pdf_btn.setObjectName("PrimaryButton")
        layout.addWidget(self.save_txt_btn)
        layout.addWidget(self.save_pdf_btn)

        return frame

    # -------------------------------------------------------------- SIGNALS
    def _connect_signals(self):
        self.refresh_btn.clicked.connect(lambda: self._start_worker(mode="detect"))
        self.read_device_btn.clicked.connect(lambda: self._start_worker(mode="fetch_logs"))
        self.load_file_btn.clicked.connect(self._on_load_file_clicked)
        self.load_photo_btn.clicked.connect(self._on_load_photo_clicked)
        self.drop_zone.filesDropped.connect(self._on_files_dropped)
        self.logs_list.itemClicked.connect(self._on_log_selected)
        self.view_mode_btn.toggled.connect(self._on_view_mode_toggled)
        self.save_txt_btn.clicked.connect(lambda: self._on_save_report("txt"))
        self.save_pdf_btn.clicked.connect(lambda: self._on_save_report("pdf"))
        self.donate_btn.clicked.connect(self._on_donate_clicked)
        self.install_btn.clicked.connect(self._on_install_clicked)
        self.model_combo.currentIndexChanged.connect(self._on_model_changed)
        self.check_update_btn.clicked.connect(self._on_check_update_clicked)

        # Перевірка наявності бібліотеки pymobiledevice3
        try:
            import pymobiledevice3  # noqa: F401
            self._device_lib_available = True
            self.install_btn.setVisible(False)
            self._start_worker(mode="detect", silent=True)
        except ImportError:
            self._device_lib_available = False
            self.status_label.setText("● Бібліотека pymobiledevice3 відсутня")
            self.status_label.setStyleSheet(
                f"color: #ffb84d; background-color: rgba(255,255,255,0.03);"
            )
            self.read_device_btn.setEnabled(False)
            self.refresh_btn.setEnabled(False)
            self.read_device_btn.setText("⚠ Зчитати Panic Logs (потрібна pymobiledevice3)")
            self.verdict_subtitle.setText(
                "Бібліотека pymobiledevice3 не встановлена, тому робота з "
                "пристроєм недоступна. Щоб активувати підключення iPhone, "
                "натисніть кнопку «Встановити pymobiledevice3» у меню «Дії» "
                "ліворуч. Ви також можете вручну завантажити .panic/.txt "
                "файл кнопкою «Завантажити файл вручну»."
            )

    # -------------------------------------------------------------- HELPERS
    def _set_status_color(self, state: str):
        colors = {
            "waiting": ("#ffb84d", "● Очікування підключення iPhone..."),
            "error": ("#ff5c5c", "● Помилка підключення"),
            "connected": ("#4ddc7f", "● iPhone підключено"),
        }
        color, text = colors.get(state, colors["waiting"])
        self.status_label.setStyleSheet(
            f"color: {color}; background-color: rgba(255,255,255,0.03);"
        )
        self.status_label.setText(text)

    def _start_worker(self, mode: str, silent: bool = False):
        self.progress_bar.setVisible(True)
        self.read_device_btn.setEnabled(False)
        self.refresh_btn.setEnabled(False)

        self.worker = DeviceWorker(mode=mode)
        self.worker.device_connected.connect(self._on_device_connected)
        self.worker.logs_found.connect(self._on_logs_found)
        self.worker.error_occurred.connect(
            lambda m: self._on_worker_error(m, silent=silent)
        )
        self.worker.progress.connect(self._on_worker_progress)
        self.worker.finished.connect(self._on_worker_finished)
        self.worker.start()

    def _on_worker_finished(self):
        self.progress_bar.setVisible(False)
        self.read_device_btn.setEnabled(True)
        self.refresh_btn.setEnabled(True)

    def _on_worker_progress(self, message: str):
        self.verdict_subtitle.setText(message)

    def _on_device_connected(self, info: Dict[str, Any]):
        self.device_info = info
        self._set_status_color("connected")
        self.device_info_label.setText(
            f"Модель: {info.get('model', '—')}    "
            f"Версія iOS: {info.get('ios_version', '—')}    "
            f"Серійний номер: {info.get('serial', '—')}    "
            f"UDID: {info.get('udid', '—')}"
        )
        # Автоматично підставити групу розшифровки Sensor Array за product-id
        fam = PRODUCT_TO_SENSOR_FAMILY.get(str(info.get("model", "")).strip())
        if fam:
            idx = self.model_combo.findData(fam)
            if idx >= 0:
                self.model_combo.setCurrentIndex(idx)

    def _on_logs_found(self, logs: List[Dict[str, str]]):
        self.loaded_logs = logs
        self.logs_list.clear()
        if not logs:
            item = QListWidgetItem("Проблем не виявлено. Panic Full логів не знайдено.")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.logs_list.addItem(item)
            # Очистити попередній аналіз і показати результат: panic-full не знайдено.
            self.current_report = None
            self.verdict_frame.setStyleSheet("")
            self.verdict_title.setText("Проблем не виявлено. Panic Full логів не знайдено.")
            self.verdict_subtitle.setText("")
            self.details_table.setRowCount(0)
            return
        for log in logs:
            src_type = classify_log_source(log["content"], log["name"])
            badge = {"panic-full": "🛑 panic-full", "panic": "⚠️ panic",
                     "analytics": "аналітика", "other": "інше"}.get(src_type, src_type)
            item = QListWidgetItem(f"{badge}  ·  {log['name']}   ({log['date']})")
            self.logs_list.addItem(item)
        # Автоматично відкрити перший знайдений лог (worker вже відсортував
        # panic-full раніше за інші)
        self.logs_list.setCurrentRow(0)
        self._analyze_and_display(logs[0]["content"], source=logs[0]["name"])

    def _on_worker_error(self, message: str, silent: bool = False):
        self._set_status_color("error")
        self.verdict_subtitle.setText(message.split("\n")[0])
        if silent:
            return
        if not getattr(self, "_device_lib_available", True):
            return
        QMessageBox.warning(self, "Помилка підключення", message)

    # ------------------------------------------------------ INSTALL LOGIC
    def _on_install_clicked(self):
        answer = QMessageBox.question(
            self,
            "Встановлення pymobiledevice3",
            "Це встановить бібліотеку pymobiledevice3 через pip, щоб "
            "застосунок міг працювати з iPhone по USB.\n\n"
            "Продовжити?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        self.install_btn.setEnabled(False)
        self.install_btn.setText("⏳ Встановлення...")
        self.progress_bar.setVisible(True)
        self.verdict_subtitle.setText("Встановлення pymobiledevice3... Це може зайняти кілька хвилин.")

        self.install_thread = InstallWorker()
        self.install_thread.log.connect(self._on_install_log)
        self.install_thread.finished_ok.connect(self._on_install_success)
        self.install_thread.failed.connect(self._on_install_failed)
        self.install_thread.start()

    def _on_install_log(self, message: str):
        self.verdict_subtitle.setText(message)

    def _on_install_success(self):
        self.progress_bar.setVisible(False)
        self.install_btn.setText("✅ pymobiledevice3 встановлено")
        QMessageBox.information(
            self,
            "Готово",
            "Бібліотеку pymobiledevice3 встановлено успішно.\n\n"
            "Перезапустіть програму, щоб активувати підключення iPhone.",
        )

    def _on_install_failed(self, message: str):
        self.progress_bar.setVisible(False)
        self.install_btn.setEnabled(True)
        self.install_btn.setText("⬇ Встановити pymobiledevice3")
        QMessageBox.critical(
            self,
            "Помилка встановлення",
            "Не вдалося встановити pymobiledevice3:\n\n" + message,
        )

    def _on_load_file_clicked(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Оберіть panic-full файл або фото логу",
            "",
            "Логи (*.panic *.ips *.txt *.log);;"
            "Зображення/фото логу (*.png *.jpg *.jpeg *.webp);;"
            "Усі файли (*.*)"
        )
        if not path:
            return
        # Авто-визначення типу: зображення — за сигнатурою, інакше файл логу.
        if _looks_like_image(path) \
                or os.path.splitext(path)[1].lower() in SUPPORTED_IMAGE_EXTENSIONS:
            self._start_ocr_import(path)
        else:
            self._import_log_file(path)

    def _on_load_photo_clicked(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Оберіть фото або скріншот логу",
            "",
            "Зображення (*.png *.jpg *.jpeg *.webp);;"
            "Усі файли (*.*)"
        )
        if not path:
            return
        self._start_ocr_import(path)

    def _import_log_file(self, path: str) -> bool:
        """Спільний імпорт файлу логу з диска.

        Використовується ОДНАКОВО і кнопкою «Завантажити файл вручну», і
        зоною Drag & Drop. Читає файл, класифікує джерело, додає лог до
        робочого списку та запускає стандартний аналіз.
        """
        try:
            content = read_text_with_auto_encoding(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Помилка читання файлу", str(exc))
            return False

        name = os.path.basename(path)
        src_type = classify_log_source(content, name)
        entry = {"name": name, "content": content,
                  "date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M")}
        self.loaded_logs.insert(0, entry)
        badge = {"panic-full": "🛑 panic-full", "panic": "⚠️ panic",
                 "analytics": "аналітика", "other": "інше"}.get(src_type, src_type)
        item = QListWidgetItem(f"{badge}  ·  {name}   (завантажено вручну)")
        self.logs_list.insertItem(0, item)
        self.logs_list.setCurrentRow(0)
        self._analyze_and_display(content, source=path)

        if src_type not in ("panic-full", "panic"):
            QMessageBox.information(
                self,
                "Проблем не виявлено",
                "Проблем не виявлено. Panic Full логів не знайдено.",
            )
        return True

    def _on_files_dropped(self, paths: List[str]):
        """Обробка файлів, перетягнутих у зону Drag & Drop.

        Автоматично визначає: зображення (за сигнатурою/розширенням) йде
        на OCR-аналіз, лог — звичайним імпортом; папки та файли невідомого
        типу ігноруються зі зрозумілим повідомленням.
        """
        imported, problems = 0, []
        for p in paths:
            if os.path.isdir(p):
                problems.append(
                    f"Папка «{os.path.basename(p)}»: очікувався файл логу "
                    "або зображення, а не директорія."
                )
                continue
            ext = os.path.splitext(p)[1].lower()
            if _looks_like_image(p) or ext in SUPPORTED_IMAGE_EXTENSIONS:
                self._start_ocr_import(p)
                imported += 1
                continue
            if ext not in SUPPORTED_LOG_EXTENSIONS:
                problems.append(
                    f"«{os.path.basename(p)}»: тип "
                    f"«{ext or '(без розширення)'}» не підтримується. "
                    "Підтримуються логи: .panic, .ips, .txt, .log; "
                    "фото: .png, .jpg, .jpeg, .webp."
                )
                continue
            if self._import_log_file(p):
                imported += 1
        if problems:
            QMessageBox.warning(self, "Деякі файли не імпортовано",
                                "\n\n".join(problems))

    # ------------------------------------------------------ OCR (фото -> аналіз)
    def _start_ocr_import(self, path: str):
        """Запускає розпізнавання тексту з фото у фоновому потоці.

        Після завершення OCR результат аналізується спільною логікою
        `_finalize_image_import` (та сама база знань, що й для логів).
        """
        self.progress_bar.setVisible(True)
        self.verdict_subtitle.setText("Розпізнавання тексту з фото (OCR)...")
        self.ocr_worker = OcrWorker(path)
        self.ocr_worker.done.connect(lambda text: self._on_ocr_ready(path, text))
        self.ocr_worker.failed.connect(lambda msg: self._on_ocr_error(path, msg))
        self.ocr_worker.finished.connect(self._on_ocr_finished)
        self.ocr_worker.start()

    def _on_ocr_finished(self):
        self.progress_bar.setVisible(False)

    def _on_ocr_error(self, path: str, message: str):
        self.progress_bar.setVisible(False)
        QMessageBox.critical(
            self, "Помилка OCR",
            f"Не вдалося розпізнати текст на зображенні.\n\n({message})"
        )

    def _on_ocr_ready(self, path: str, text: str):
        """OCR завершено: якщо тексту немає — повідомляємо, інакше аналізуємо."""
        text = (text or "").strip()
        if not text:
            QMessageBox.warning(self, "OCR", OCR_NO_TEXT_MSG)
            return
        self._finalize_image_import(path, text)

    def _finalize_image_import(self, path: str, text: str):
        """Спільна обробка розпізнаного тексту: аналіз + додавання у список.

        Використовує той самий `analyze_ocr_text` (спільна база знань).
        Якщо ключів не знайдено — інформуємо користувача.
        """
        model_hint = self.model_combo.currentData() or ""
        report = analyze_ocr_text(text, source_file=path, model_hint=model_hint)
        name = os.path.basename(path)
        self.loaded_logs.insert(0, {"name": name, "content": text,
                                    "date": datetime.datetime.now().strftime(
                                        "%Y-%m-%d %H:%M")})
        item = QListWidgetItem(f"🖼 OCR  ·  {name}   (фото)")
        self.logs_list.insertItem(0, item)
        self.logs_list.setCurrentRow(0)
        self._finalize_report(report)
        if not report.findings:
            QMessageBox.information(self, "OCR", OCR_NO_KEYWORDS_MSG)

    def _on_log_selected(self, item: QListWidgetItem):
        row = self.logs_list.row(item)
        if 0 <= row < len(self.loaded_logs):
            log = self.loaded_logs[row]
            self._analyze_and_display(log["content"], source=log["name"])

    def _analyze_and_display(self, raw_text: str, source: str):
        self._last_analyzed = {"raw_text": raw_text, "source": source}
        model_hint = self.model_combo.currentData() or ""
        report = parse_panic_log(raw_text, source_file=source, model_hint=model_hint)
        self._finalize_report(report)

    def _finalize_report(self, report: DiagnosticReport):
        """Підмішує відому інформацію пристрою та показує звіт.

        Використовується ОДНАКОВО для логів (panic-full) і фото/OCR.
        """
        if not report.device_model and self.device_info.get("model"):
            report.device_model = self.device_info["model"]
        if not report.ios_version and self.device_info.get("ios_version"):
            report.ios_version = self.device_info["ios_version"]
        if not report.serial and self.device_info.get("serial"):
            report.serial = self.device_info["serial"]
        if not report.udid and self.device_info.get("udid"):
            report.udid = self.device_info["udid"]
        self.current_report = report
        self._render_report(report)

    def _on_model_changed(self, *_):
        last = getattr(self, "_last_analyzed", None)
        if last:
            self._analyze_and_display(last["raw_text"], last["source"])

    def _render_report(self, report: DiagnosticReport):
        if getattr(self, '_raw_view_active', False):
            self._raw_view_active = False
            self._raw_box.setVisible(False)
            self._details_box.setVisible(True)
        self._raw_box.setTitle("Сирий текст логу (Raw Panic)")
        # Вердикт
        self.verdict_title.setText(report.verdict)
        model_info = f"Модель: {report.device_model}. " if report.device_model else ""

        if report.source_type == "photo":
            # Повний розпізнаний текст користувачу не показуємо: силого
            # перегляду немає, кнопка режиму перегляду знову з'являється
            # лише для логів.
            self.view_mode_btn.blockSignals(True)
            self.view_mode_btn.setChecked(False)
            self.view_mode_btn.blockSignals(False)
            self.view_mode_btn.setVisible(False)
            self._render_photo_report(report, model_info)
            return

        self.view_mode_btn.setVisible(True)

        cause_info = ""
        if report.panic_cause:
            cause_info = f"\nПричина (перший рядок panicString): {report.panic_cause}"
        if not report.is_panic_source:
            self.verdict_frame.setStyleSheet("")
            self.verdict_subtitle.setText(
                model_info + "Panic Full логів не знайдено, тому причина не визначалась."
            )
            # Таблиця (порожня, оскільки не-panic джерело не аналізується)
            self.details_table.setRowCount(0)
            if self.view_mode_btn.isChecked():
                self._show_raw_view(report)
            return
        if report.findings:
            top = report.findings[0]
            color = SEVERITY_COLOR.get(top.severity, "#5cc8ff")
            self.verdict_frame.setStyleSheet(
                f"QFrame#Card {{ border: 1.5px solid {color}; }}"
            )
            self.verdict_subtitle.setText(
                f"{model_info}Знайдено {len(report.findings)} збіг(ів) за базою знань. "
                f"Найважливіший: {top.recommendation}{cause_info}"
            )
        else:
            self.verdict_frame.setStyleSheet("")
            self.verdict_subtitle.setText(
                model_info
                + "Явних апаратних несправностей за базою ознак не виявлено. "
                  "Перевірте лог вручну на нижній панелі (Raw Panic)."
                + cause_info
            )

        # Таблиця
        self.details_table.setRowCount(0)
        for f in report.findings:
            row = self.details_table.rowCount()
            self.details_table.insertRow(row)

            sev_item = QTableWidgetItem(SEVERITY_LABEL.get(f.severity, f.severity))
            sev_item.setForeground(QColor(SEVERITY_COLOR.get(f.severity, "#e8e8ea")))
            self.details_table.setItem(row, 0, sev_item)
            self.details_table.setItem(row, 1, QTableWidgetItem(f.component))
            self.details_table.setItem(row, 2, QTableWidgetItem(f.keyword))
            self.details_table.setItem(row, 3, QTableWidgetItem(f.recommendation))

        self.details_table.resizeRowsToContents()

        if self.view_mode_btn.isChecked():
            self._show_raw_view(report)

    def _render_photo_report(self, report: DiagnosticReport, model_info: str):
        """Показ результатів аналізу фото/OCR: вердикт, ключі, знахідки.

        При джерелі «photo» таблиця знахідок заповнюється тими самими
        ключовими словами, що й для panic-full; повний розпізнаний текст
        користувачу не показується (лише знайдені коди/ключі та діагноз).
        """
        if report.findings:
            top = report.findings[0]
            color = SEVERITY_COLOR.get(top.severity, "#5cc8ff")
            self.verdict_frame.setStyleSheet(
                f"QFrame#Card {{ border: 1.5px solid {color}; }}"
            )
            kw = ", ".join(report.matched_keywords) if report.matched_keywords \
                else top.keyword
            self.verdict_subtitle.setText(
                f"{model_info}Знайдено {len(report.findings)} збіг(ів) за базою "
                f"знань. Ключові слова: {kw}. Найважливіший: {top.recommendation}"
            )
        else:
            self.verdict_frame.setStyleSheet("")
            self.verdict_subtitle.setText(
                f"{model_info}Ключових слів за базою знань не знайдено. "
                "Спробуйте завантажити більш чітке фото або вкажіть модель "
                "iPhone у випадаючому списку."
            )

        # Таблиця знахідок (спільна з panic-full)
        self.details_table.setRowCount(0)
        for f in report.findings:
            row = self.details_table.rowCount()
            self.details_table.insertRow(row)

            sev_item = QTableWidgetItem(SEVERITY_LABEL.get(f.severity, f.severity))
            sev_item.setForeground(QColor(SEVERITY_COLOR.get(f.severity, "#e8e8ea")))
            self.details_table.setItem(row, 0, sev_item)
            self.details_table.setItem(row, 1, QTableWidgetItem(f.component))
            self.details_table.setItem(row, 2, QTableWidgetItem(f.keyword))
            self.details_table.setItem(row, 3, QTableWidgetItem(f.recommendation))

        self.details_table.resizeRowsToContents()

    def _on_view_mode_toggled(self, checked: bool):
        if checked:
            self.view_mode_btn.setText("📊 Переглянути інтерпретований звіт")
            if self.current_report:
                self._show_raw_view(self.current_report)
        else:
            self.view_mode_btn.setText("👁 Переглянути сирий лог (Raw Panic)")
            if self.current_report:
                self._render_report(self.current_report)

    def _show_raw_view(self, report: DiagnosticReport):
        self._details_box.setVisible(False)
        self._raw_box.setVisible(True)
        self.raw_text_edit.setPlainText(report.raw_text or "Порожній лог.")
        self.raw_text_edit.moveCursor(
            self.raw_text_edit.textCursor().MoveOperation.Start
        )
        self._raw_view_active = True

    # -------------------------------------------------------------- ОНОВЛЕННЯ
    _UPDATE_FRIENDLY = {
        "network": "Не вдалося перевірити оновлення. Перевірте підключення до Інтернету.",
        "server": "Сервер оновлень тимчасово недоступний. Спробуйте пізніше.",
        "data": "Не вдалося перевірити оновлення. Спробуйте пізніше.",
        "integrity": "Не вдалося перевірити цілісність оновлення. Встановлення скасовано.",
        "download": "Не вдалося завантажити оновлення.",
        "unknown": "Сталася неочікувана помилка під час перевірки оновлень.",
    }

    def _on_check_update_clicked(self):
        self._latest_release = None
        self.check_update_btn.setEnabled(False)
        self.check_update_btn.setText("Перевірка оновлень...")
        self.update_check_worker = UpdateCheckWorker(current_version=APP_VERSION)
        self.update_check_worker.result.connect(self._on_update_check_result)
        self.update_check_worker.failed.connect(self._on_update_check_failed)
        self.update_check_worker.finished.connect(self._on_update_worker_finished)
        self.update_check_worker.start()

    def _on_update_worker_finished(self):
        self.check_update_btn.setEnabled(True)
        self.check_update_btn.setText("⤓ Перевірити оновлення")

    def _on_update_check_failed(self, kind: str, _detail: str):
        QMessageBox.warning(
            self, "Оновлення",
            self._UPDATE_FRIENDLY.get(kind, self._UPDATE_FRIENDLY["unknown"]),
        )

    def _on_update_check_result(self, data: dict):
        self._latest_release = data.get("release") or {}
        if not data.get("available"):
            QMessageBox.information(
                self, "Оновлення",
                f"У вас встановлена остання версія {APP_NAME} {APP_VERSION}.",
            )
            return
        latest = data.get("latest", "")
        asset = get_installer_asset(self._latest_release)
        if not asset:
            QMessageBox.information(
                self, "Оновлення",
                "Для цієї версії не знайдено інсталятор PanicIF-Setup.exe.",
            )
            return
        mb = QMessageBox(self)
        mb.setWindowTitle("Оновлення")
        mb.setIcon(QMessageBox.Icon.Question)
        mb.setText(
            f"Доступна нова версія {APP_NAME} {latest}.\n\n"
            f"Встановлена версія: {APP_VERSION}\n"
            f"Нова версія: {latest}\n\n"
            "Бажаєте завантажити та встановити оновлення?"
        )
        update_btn = mb.addButton("Оновити", QMessageBox.ButtonRole.AcceptRole)
        cancel_btn = mb.addButton("Скасувати", QMessageBox.ButtonRole.RejectRole)
        mb.setDefaultButton(cancel_btn)
        mb.exec()
        if mb.clickedButton() is not update_btn:
            return
        digest = get_digest_asset(self._latest_release) or {}
        self.check_update_btn.setEnabled(False)
        self.check_update_btn.setText("Завантаження оновлення... 0%")
        self.update_download_worker = UpdateDownloadWorker(
            url=asset.get("browser_download_url", ""),
            digest_url=digest.get("browser_download_url", "") or "",
        )
        self.update_download_worker.progress.connect(self._on_update_download_progress)
        self.update_download_worker.downloaded.connect(self._on_update_downloaded)
        self.update_download_worker.failed.connect(self._on_update_download_failed)
        self.update_download_worker.finished.connect(self._on_update_worker_finished)
        self.update_download_worker.start()

    def _on_update_download_progress(self, got: int, total: int):
        if total and total > 0:
            percent = max(0, min(100, int(got * 100 / total)))
            self.check_update_btn.setText(f"Завантаження оновлення... {percent}%")
        else:
            self.check_update_btn.setText("Завантаження оновлення...")

    def _on_update_download_failed(self, kind: str, _detail: str):
        QMessageBox.critical(
            self, "Оновлення",
            self._UPDATE_FRIENDLY.get(kind, self._UPDATE_FRIENDLY["unknown"]),
        )

    def _on_update_downloaded(self, path: str):
        mb = QMessageBox(self)
        mb.setWindowTitle("Встановлення оновлення")
        mb.setIcon(QMessageBox.Icon.Question)
        mb.setText(
            "Оновлення завантажено. PanicIF буде закрито, після чого "
            "запуститься інсталятор нової версії."
        )
        install_btn = mb.addButton("Встановити", QMessageBox.ButtonRole.AcceptRole)
        cancel_btn = mb.addButton("Скасувати", QMessageBox.ButtonRole.RejectRole)
        mb.setDefaultButton(cancel_btn)
        mb.exec()
        if mb.clickedButton() is not install_btn:
            return
        try:
            launch_installer(path)
        except UpdaterError:
            QMessageBox.critical(
                self, "Оновлення",
                "Не вдалося запустити інсталятор оновлення.",
            )
            return
        QApplication.instance().quit()

    def _on_donate_clicked(self):
        QDesktopServices.openUrl(QUrl("https://send.monobank.ua/jar/ZazdhqcJa"))

    def _on_save_report(self, fmt: str):
        if not self.current_report:
            QMessageBox.information(
                self, "Немає звіту",
                "Спочатку зчитайте або завантажте панік-лог для аналізу."
            )
            return

        default_name = f"iphone_panic_report_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.{fmt}"
        filter_str = "PDF файли (*.pdf)" if fmt == "pdf" else "Текстові файли (*.txt)"
        path, _ = QFileDialog.getSaveFileName(self, "Зберегти звіт", default_name, filter_str)
        if not path:
            return

        try:
            if fmt == "pdf":
                export_pdf(self.current_report, path)
            else:
                export_txt(self.current_report, path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Помилка збереження", str(exc))
            return

        QMessageBox.information(self, "Готово", f"Звіт збережено:\n{path}")


# =====================================================================================
# 8. ТОЧКА ВХОДУ
# =====================================================================================

def main():
    def exception_hook(exc_type, exc_value, exc_tb):
        tb_lines = traceback.format_exception(exc_type, exc_value, exc_tb)
        tb_text = "".join(tb_lines)
        print(tb_text, file=sys.stderr)
        QMessageBox.critical(None, "Невідома помилка", tb_text[-3000:])

    sys.excepthook = exception_hook

    app = QApplication(sys.argv)
    app.setStyleSheet(DARK_STYLESHEET)
    app.setApplicationName(APP_NAME)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
