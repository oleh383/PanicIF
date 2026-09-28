# Збірка інсталятора Windows для «PanicIF»

Ця папка повністю готує готований установочний файл для користувача:
запускний EXE (PyInstaller) + фінальний інсталятор (Inno Setup), який
тихо доставляє драйвери Apple Mobile Device Support.

## Що вже зібрано

| Файл | Призначення |
|---|---|
| `dist/PanicIF/PanicIF.exe` | Запускний .exe (onedir, без консолі). Працює без встановленого Python |
| `dist/PanicIF-Setup.exe` | **Фінальний інсталятор** — це його віддаєте користувачу |
| `app/iphone_panic_diagnostics.py` | Копія вихідного коду, з якої збирається EXE |
| `packaging/iphone_panic.spec` | Конфігурація PyInstaller (включно з pymobiledevice3) |
| `packaging/Setup.iss` | Конфігурація Inno Setup (тиха установка драйверів) |
| `packaging/build.ps1` | Автоматична перебудова: EXE → Setup |
| `packaging/drivers/` | Сюди кладете файл драйвера Apple (див. далі) |

## Залежності для збірки на вашій машині

1. **Python 3.11–3.13** — вже є (3.13.14).
2. **PyInstaller** — буде встановлений автоматично `build.ps1`.
3. **Inno Setup 6** — вже встановлено (6.7.3).

## Як перебудувати повністю

```powershell
# з папки C:\Users\Laptop\iPhonePanicDiagnostics
powershell -ExecutionPolicy Bypass -File packaging\build.ps1
```

Скрипт самовиявляє Inno Setup, ставить PyInstaller, збирає EXE і компілює Setup.

## Драйвери Apple (крок для «без ручного налаштування»)

Щоб кнопка «Зчитати Panic Logs з пристрою» працювала у кінцевого користувача,
інсталятор тихо встановлює **Apple Mobile Device Support (usbmuxd)**.
Для цього покладіть у `packaging/drivers/` **один** із файлів:

- `AppleMobileDeviceSupport64.msi` — рекомендовано (тільки драйвери);
- `iTunes64Setup.exe` — повний iTunes (~150 МБ);
- `AppleDevicesSetup.exe` — сучасний застосунок Apple Devices (iOS 17+/iPhone 17+).

Джерело: офіційний розділ завантажень Apple
(`https://www.apple.com/itunes/download/win64`). Прямий CDN-URL не фіксуємо —
він змінюється; покладіть файл, який скачали, у папку drivers/, і
`Setup.iss` сам підхопить його через `FileExists`.

Інсталятор вже містить логіку:
1. Перевіряє службу `Apple Mobile Device Service` у реєстрі + наявність
   `usbmuxd64.exe` — якщо вже є, драйвер **не** ставить повторно.
2. Якщо немає і файл драйвера прикладено — ставить тихо:
   `msiexec /i ... /qn /norestart` (або `/quiet` для exe-збірників).
3. Якщо файлу драйвера немає — інсталятор все одно збереться і
   попередить у вікні установки.

## Як розповсюджувати

1. Віддайте файл `dist/PanicIF-Setup.exe`.
2. Користувач запускає його: ставиться додаток + драйвери (якщо потрібно).
3. Після установки з'являється ярлик на робочому столі та в меню «Пуск».
4. iPhone підключається USB-кабелем; перше підключення — натиснути
   «Довіряти» на iPhone.

## Підписання (щоб Windows SmartScreen не лякав)

Без підпису користувач побачить попередження SmartScreen («Невідомий
видавець»). Щоб прибрати:

1. Купіть код-підписувальний сертифікат (наприклад, у Sectigo, DigiCert).
2. Встановіть Windows SDK (signtool.exe) або use «SignTool» з Visual Studio.
3. Отримайте `.pfx` і запустіть один раз:

   ```powershell
   signtool sign /f "cert.pfx" /p "ПАРОЛЬ" /tr http://timestamp.digicert.com /td sha256 /fd sha256 `
       "dist\PanicIF\PanicIF.exe" ``
       "dist\PanicIF-Setup.exe"
   ```

4. У `Setup.iss` розкоментуйте рядок `SignTool=signtool $f` (після
   налаштування ключових шляхів), або підписуйте готовий Setup після збірки,
   як показано вище.

## Обмеження

- Розмір інсталятора ~90 МБ через повну збірку PyQt6 + pymobiledevice3.
- Для роботи з пристроєм на iOS 17+ сучасніші моделі можуть потребувати
  застосунок Apple Devices замість iTunes — див. `packaging/drivers/README.txt`.
- onedir-збірка: EXE запускається швидко, але поруч із ним зберігається
  вся папка `PanicIF\` (DLL, моделі OCR) — це нормальний режим роботи.