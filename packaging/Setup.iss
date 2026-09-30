; -------------------------------------------------------------------------------
;  PanicIF — інсталятор (Inno Setup 6+)
;
;  Збірка:  ISCC.exe packaging/Setup.iss   (або через build.ps1)
;
;  Що робить інсталятор:
;    1) Встановлює застосунок (dist/PanicIF/ — onedir збірка PyInstaller) в Program Files.
;    2) ТИХО встановлює драйвери Apple Mobile Device Support (usbmuxd), якщо:
;         - в папці packaging/drivers лежить AppleMobileDeviceSupport64.msi
;           або iTunes64Setup.exe / AppleDevicesSetup.exe, І
;         - на системі ще немає служби "Apple Mobile Device Service"
;       (перевірка робиться перед запуском, повторно не ставить).
;
;  Куди покласти драйвер — див. packaging/drivers/README.txt
;
;  ВЕРСІЯ ПРОГРАМИ: єдине джерело — APP_VERSION у
;  app/iphone_panic_diagnostics.py. Завжди запускайте PyInstaller ПЕРЕД ISCC:
;  інсталятор читає ProductVersion зі зібраного dist\PanicIF\PanicIF.exe.
; -------------------------------------------------------------------------------

#define MyAppName "PanicIF"
#define MyAppExeName "PanicIF.exe"
#define MyAppExePath AddBackslash(SourcePath) + "..\dist\PanicIF\PanicIF.exe"
#define MyAppVersion GetStringFileInfo(MyAppExePath, "ProductVersion")
#if Len(MyAppVersion) == 0
#define MyAppVersion "1.1.0"
#endif
#define MyAppPublisher "OpenCode"
#define MyAppId "{{3A2F8E9C-7B41-4D6A-9C0E-1F5B8D2A6C47}"

[Setup]
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
VersionInfoVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog commandline
OutputDir=..\dist
OutputBaseFilename={#MyAppName}-Setup
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
Source: "..\dist\{#MyAppName}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

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