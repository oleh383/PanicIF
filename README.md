# PanicIF

**A free, offline Windows tool for analyzing Apple iPhone Panic Full (kernel panic) and crash logs.**

PanicIF is designed for iPhone repair technicians and technical users. It inspects the panic log, decodes
known failure signatures (including the modern `SMC sensor array` codes such as `0x4000`), and reports the
**most likely faulty component** together with practical repair recommendations — all locally on your PC,
without sending any data to a server.

> PanicIF is **not** an Apple product and is **not** approved or endorsed by Apple Inc.

---

## Download Latest Release

| | |
|---|---|
| **Latest version:** | **v1.2.0** |
| **Download:** | <kbd>**[PanicIF-Setup.exe](https://github.com/oleh383/PanicIF/releases/latest)**</kbd> |

Direct link: <https://github.com/oleh383/PanicIF/releases/latest>

---

## Installation

1. Open the **[Latest Release](https://github.com/oleh383/PanicIF/releases/latest)** page.
2. Download the **`PanicIF-Setup.exe`** installer (about 90 MB).
3. Run the installer and follow the wizard. Administrator rights may be required.
4. Open **PanicIF** from the desktop shortcut or the Start menu.

**Optional (needed for USB reading):** the installer can silently install the Apple Mobile Device Support
drivers when bundled. If they are missing, the app tells you what to install — see
[USB reading](#how-the-iphone-panic-logs-reach-panicif) and [Troubleshooting](#troubleshooting).

---

## Features

Everything below is implemented in the current release (`v1.2.0`):

- **Read Panic Full / CrashLogs directly from a USB-connected iPhone** — device detection and log
  enumeration are performed through `pymobiledevice3` / `usbmuxd`, the same protocol Apple services use.
- **Manual file import** — load a panic log file in `.panic`, `.ips`, `.txt` or `.log` format.
- **Drag & drop** — drop log files (or photos of logs) straight onto the window.
- **Photo / screenshot OCR** — recognize the log text from a photo and run it through the *same*
  analysis engine. OCR uses **RapidOCR on ONNX Runtime and runs 100% locally/offline**; images are never
  uploaded anywhere.
- **Knowledge-base analysis** — a signature database maps log keywords and modern `SMC sensor array`
  values to likely faulty components: battery/BSI/Tigris, microphones, proximity/Face ID, power button/PMU,
  volume flex, Taptic Engine, Home button, display module, audio codec, Wi-Fi/Bluetooth, baseband modem,
  Tristar/Hydra/Kraken charge/USB controllers, NAND, CPU and more.
- **SMC sensor array decoding** for modern iPhone families (iPhone 13 / 14 / 14 Pro / 15 and later),
  e.g. `0x4000` on iPhone 13 -> battery related issue.
- **Automatic model detection** from the log, with an optional manual model override.
- **Clear verdict + findings table** — each finding includes its severity (*Critical / Warning*), the
  matched component, the matched keyword, and a repair recommendation.
- **Export reports** to **TXT** or **PDF**.
- **Raw log view** — toggle between the interpreted report and the raw panic text.
- **Built-in updater** — check for new releases right from the app and install them (downloads the
  official `PanicIF-Setup.exe` from the GitHub Releases page).
- **Dark desktop UI** (Qt6/PyQt6).

> **Note on language:** the on-screen labels of the application are currently in **Ukrainian**. The
> report itself and the analysis database describe components in the same language. This README documents
> the program so that any user can start with it.

---

## System Requirements

- **OS:** Windows 10 / 11 (64-bit).
- **Disk space:** installer is ~90 MB; installed application needs additional space for the bundled
  runtime, OCR models and Apple device support files.
- **Python:** not required — the installer ships a ready-to-run executable.
- **USB reading** additionally requires:
  - An **iPhone** and a working **USB cable**;
  - **Apple Mobile Device Support** (included in iTunes from `apple.com`, *not* the stripped-down
    Microsoft Store version), or the **Apple Devices** app for the newest iOS 17+ / iPhone 17+ models;
  - the **Apple Mobile Device Service** running in Windows services;
  - the phone must be **unlocked**, and on the first connection you must tap **"Trust This Computer"**
    on the iPhone.
- **OCR photo analysis** works without any drivers or internet connection.

---

## Usage

1. **Connect your iPhone over USB**, unlock it and confirm **"Trust This Computer"** on the device.
2. In PanicIF press **"Read Panic Logs from device"** — available panic logs are enumerated; pick the one
   you want (typically a `PanicFull-...ips` entry).
   - No driver/device access? Use one of the alternatives below.
3. **Alternative inputs:**
   - **Load a file:** press **"Load .panic/.txt file manually"** and choose the exported `.ips` / `.panic`
     / `.txt` file;
   - **Drag & drop** a log file onto the window;
   - **Photo of a log:** press **"Recognize text from photo (OCR)"** and select a sharp photo/screenshot of
     the panic log screen.
4. Read the **verdict card** and the **findings table** below it. Each row shows the severity, the
   component, the matched keyword and a repair recommendation.
5. If needed, switch to the **raw log view** to inspect the original text.
6. Save the report with **"Save report (TXT)"** or **"Save report (PDF)"**.
7. Use **"Check for updates"** occasionally to get new releases.

### How the iPhone panic logs reach PanicIF

Panic Full logs (files like `PanicFull-2026-...ips`) are stored **on the device** in
*Settings → Privacy & Security → Analytics & Improvements → Analytics Data*. There are three ways to
feed them into PanicIF:

1. **Automatic (recommended):** with Apple Mobile Device Support installed, open PanicIF with the phone
   connected and press **"Read Panic Logs from device"** — the phone's crash-log directory is read over
   USB.
2. **Export the file:** in the Analytics Data list on the iPhone, tap the `PanicFull-*.ips` entry and use
   the share button to save/email the file, then import it in PanicIF (button or drag & drop).
3. **Photo:** keep the panic-log text on the phone screen and use PanicIF's **OCR** feature; the
   screenshot/photo is analyzed locally.

> If a panicked iPhone shows no recent logs at all, double-check that **Analytics & Improvements** is
> enabled on the phone (incident data is not collected while it is off).

---

## Sample Diagnostic Report

The report is rendered as a verdict card plus a findings table. Example for an iPhone 13 log containing
the sensor-array value `0x4000`:

**Verdict:** Likely faulty component: **Battery (Battery) — `0x4000`**

| Severity | Component | Matched keyword | Recommendation |
|---|---|---|---|
| Critical | Battery | `0x4000` (SMC sensor array) | Problem with the battery (data line). Check the battery connector, flex cable and the Tigris controller on the board. |

The first line of the `panicString` (the reported "cause") is also shown, together with general device
information (model, timestamps) when it is available in the log.

---

## Troubleshooting

| Problem | What to check / do |
|---|---|
| **SmartScreen "Unknown publisher" warning** | The installer is currently **not code-signed**. Click **More info → Run anyway**. |
| **"pymobiledevice3 is missing"** message | Install the bundled drivers via the app's install button, or run `pip install pymobiledevice3`. |
| **Device not detected / "no Apple Mobile Device Service"** | Install iTunes from `apple.com` (contains Apple Mobile Device Support), verify the **Apple Mobile Device Service** is *Running* (`services.msc`), re-plug the cable, unlock the phone and confirm **"Trust This Computer"**. |
| **No logs found on the device** | Enable *Settings → Privacy & Security → Analytics & Improvements*; the phone needs an active "Analytics Data" collection. Panic logs are generated after a crash/restart. |
| **iOS 17+ / newer iPhone not recognized via USB** | Newer models may require the **Apple Devices** app instead of classic iTunes drivers. |
| **OCR returns no text** | Use a clear, well-lit, sharp photo focused on the text of the panic log; keep the log lines inside the frame. |
| **Installer asks for administrator rights** | That is expected for a machine-wide install into `C:\Program Files`. |
| **The analysis looks wrong** | PanicIF is a heuristic assistant, not a warranty-quality diagnosis. Cross-check the **raw log** view and, if necessary, consult a service reference manual. |

---

## Privacy

- **Fully local processing.** Panic logs, files and photos are analyzed **on your computer**. No log
  content, photo or document is sent to any cloud service.
- **Offline OCR.** The photo OCR engine (RapidOCR/ONNX) runs locally with bundled models.
- **Network usage is limited to the updater.** The only network calls in the program are a `GET` request
  to `api.github.com/repos/oleh383/PanicIF/releases/latest` to check for a newer release, and the download
  of the official installer from the GitHub **Releases** page when you confirm an update. There is no
  telemetry, no analytics, no third-party endpoints.
- **No personal data collection.** The author does not collect UDIDs, serial numbers, logs or any
  user-generated data.

---

## Reporting Issues

Found a bug, a false-positive signature, or an idea for a new feature?

Please open an issue: **[github.com/oleh383/PanicIF/issues](https://github.com/oleh383/PanicIF/issues)**
— attach a sanitized panic log (or describe the model and the exact `panicString`) whenever possible.

---

## Latest Release

**v1.2.0** — installer: [`PanicIF-Setup.exe`](https://github.com/oleh383/PanicIF/releases/latest)

---

## Important Disclaimer

The results of the automatic analysis are **heuristic hints**, not a definitive hardware diagnosis.
A keyword match or a decoded sensor-array value points to the *likely* area of failure, but the real
defect may be different (for example, a failed flex cable instead of the chip itself). Always verify with
component-level testing and/or an experienced repair service before replacing parts.

PanicIF is provided **as-is, without warranty of any kind**. It is not affiliated with, approved, or
endorsed by Apple Inc.

---

## Building from Source

See [README_BUILD.md](README_BUILD.md) for the full build pipeline
(PyInstaller executable + Inno Setup installer) used to produce the official release.