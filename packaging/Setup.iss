; -------------------------------------------------------------------------------
;  iPhone Panic Log Diagnostics — інсталятор (Inno Setup 6+)
;
;  Збірка:  ISCC.exe packaging/Setup.iss   (або через build.ps1)
;
;  Що робить інсталятор:
;    1) Встановлює застосунок (dist/iPhonePanicDiagnostics.exe) в Program Files.
;    2) ТИХО встановлює драйвери Apple Mobile Device Support (usbmuxd), якщо:
;         - в папці packaging/drivers лежить AppleMobileDeviceSupport64.msi
;           або iTunes64Setup.exe / AppleDevicesSetup.exe, І
;         - на системі ще немає служби "Apple Mobile Device Service"
;       (перевірка робиться перед запуском, повторно не ставить).
;
;  Куди покласти драйвер — див. packaging/drivers/README.txt
; -------------------------------------------------------------------------------

#define MyAppName "iPhone Panic Log Diagnostics"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "OpenCode"
#define MyAppExeName "iPhonePanicDiagnostics.exe"
#define MyAppId "{{C4E1E4C2-8F0B-4B7A-9D2E-7E1A5B3F6D01}"

[Setup]
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\iPhonePanicDiagnostics
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=admin
OutputDir=..\dist
OutputBaseFilename=iPhonePanicDiagnostics-Setup
SetupIconFile=icon.ico
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#MyAppExeName}
ArchitecturesInstallIn64BitMode=x64
; Підписання (необов'язково): розкоментуйте та вкажіть свій .pfx
; SignTool=signtool $f

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
; Головний застосунок (onedir: вся папка PyInstaller-білда)
Source: "..\dist\iPhonePanicDiagnostics\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

; --- Драйвери Apple Mobile Device Support (тихол установка нижче в [Run]) ---
; Файли підхоплюються ЛИШЕ якщо фізично лежать у packaging/drivers.
#if FileExists("drivers\AppleMobileDeviceSupport64.msi")
Source: "drivers\AppleMobileDeviceSupport64.msi"; DestDir: "{tmp}"; Flags: dontcopy
#endif
#if FileExists("drivers\iTunes64Setup.exe")
Source: "drivers\iTunes64Setup.exe"; DestDir: "{tmp}"; Flags: dontcopy
#endif
#if FileExists("drivers\AppleDevicesSetup.exe")
Source: "drivers\AppleDevicesSetup.exe"; DestDir: "{tmp}"; Flags: dontcopy
#endif

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon; IconFilename: "{app}\{#MyAppExeName}"

[Tasks]
Name: "desktopicon"; Description: "Створити ярлик на робочому столі"; GroupDescription: "Додаткові завдання:"

[Run]
#if FileExists("drivers\AppleMobileDeviceSupport64.msi")
; Тихе встановлення драйверів. Перевірка наявності — у функції AppleDriverNeeded.
Filename: "{sys}\msiexec.exe"; Parameters: "/i ""{tmp}\AppleMobileDeviceSupport64.msi"" /qn /norestart REBOOT=ReallySuppress"; WorkingDir: "{tmp}"; StatusMsg: "Встановлення драйверів Apple Mobile Device Support (usbmuxd)..."; Flags: runhidden waituntilterminated; Check: AppleDriverNeeded
#endif
#if FileExists("drivers\iTunes64Setup.exe")
Filename: "{tmp}\iTunes64Setup.exe"; Parameters: "/quiet /norestart /NoDesktopShortcut /NoLaunchApp"; WorkingDir: "{tmp}"; StatusMsg: "Встановлення iTunes / Apple Mobile Device Support..."; Flags: runhidden waituntilterminated; Check: AppleDriverNeeded
#endif
#if FileExists("drivers\AppleDevicesSetup.exe")
Filename: "{tmp}\AppleDevicesSetup.exe"; Parameters: "/quiet /norestart"; WorkingDir: "{tmp}"; StatusMsg: "Встановлення Apple Devices / Apple Mobile Device Support..."; Flags: runhidden waituntilterminated; Check: AppleDriverNeeded
#endif
Filename: "{app}\{#MyAppExeName}"; Description: "Запустити {#MyAppName}"; Flags: nowait postinstall skipifsilent

[Code]
// Перевіряє, чи вже встановлена служба Apple Mobile Device Service (usbmuxd).
function AppleMobileDeviceServiceInstalled(): Boolean;
var
  ImagePath: String;
  UsbmuxExe: String;
begin
  Result := False;
  if RegQueryStringValue(HKLM64, 'SYSTEM\CurrentControlSet\Services\Apple Mobile Device Service', 'ImagePath', ImagePath) then
  begin
    Result := True;
    Exit;
  end;
  // Фолбек — перевірка наявності безпосередньо виконуваного файлу usbmuxd.
  UsbmuxExe := ExpandConstant('{commonpf64}\Apple\Mobile Device Support\usbmuxd64.exe');
  if not FileExists(UsbmuxExe) then
    UsbmuxExe := ExpandConstant('{commonpf64}\Apple\Mobile Device Support\usbmuxd.exe');
  if FileExists(UsbmuxExe) then
    Result := True;
end;

// Потрібні драйвери — ставимо лише якщо їх ще немає.
function AppleDriverNeeded(): Boolean;
begin
  Result := not AppleMobileDeviceServiceInstalled();
end;