ДРАЙВЕРИ APPLE MOBILE DEVICE SUPPORT
=====================================

Щоб кнопка «Зчитати Panic Logs з пристрою» працювала, на ПК користувача
обовʼязково має бути служба "Apple Mobile Device Service" (usbmuxd).
Вона ставиться разом із iTunes або застосунком Apple Devices.

Цей інсталятор може встановити драйвер АВТОМАТИЧНО і тихо. Для цього
покладіть У ЦЮ ПАПКУ (packaging\drivers) ОДИН із файлів:

  1. AppleMobileDeviceSupport64.msi     (рекомендовано — тільки драйвери,
                                         без iTunes)
  2. iTunes64Setup.exe                  (повний iTunes, ~150MB)
  3. AppleDevicesSetup.exe              (сучасний застосунок Apple Devices)

Звідки взяти:

  - Завантажте macOS/Windows розділ на офіційному сайті Apple:
      https://www.apple.com/itunes/download/win64
    (це "iTunes64Setup.exe" / "Apple Devices"; посилання веде на актуальний
     збірник Apple, CDN-адреси змінюються, тому прямий URL тут не фіксуємо).
  - Або запустіть офіційний iTunesSetup.exe на будь-якому ПК і знайдіть
    розпакований "AppleMobileDeviceSupport64.msi" у %TEMP%, або завантажте
    standalone-версію від надійного джерела.

Після розміщення файлу просто зберіть інсталятор (build.ps1) — Setup.iss
сам побачить файл за допомогою FileExists і додасть відповідний крок у [Run].

ВАЖЛИВО:
  - Якщо папка drivers порожня — інсталятор все одно збереться, просто
    драйвер не ставитиме (у цьому випадку користувачу треба вручну
    встановити iTunes/Apple Devices).
  - Перевірку наявності служби робить Setup.iss своєю функцією
    AppleDriverNeeded — повторно драйвер не встановлюється.
  - Для роботи з iPhone 17+ та iOS 17+ рекомендується сучасний
    застосунок Apple Devices (не старий iTunes).