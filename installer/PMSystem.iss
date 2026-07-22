#define MyAppName "电商打包发货监控溯源系统"
#ifndef MyAppVersion
  #error MyAppVersion must be supplied by build_installer.bat
#endif
#define MyAppPublisher "JsonLin"
#define MyAppExeName "电商打包发货监控溯源系统.exe"
#define MyAppUserModelID "JsonLin.PMSystem"
#define MyLicenseHelper "PMSystemLicenseHelper.exe"
#define MyAppIcon "..\app\assets\app_icon.ico"
#define MyDistRoot "..\dist\电商打包发货监控溯源系统"
#if !FileExists(MyAppIcon)
  #error Formal application icon not found: {#MyAppIcon}
#endif
#if !FileExists(MyDistRoot + "\_internal\tools\ffmpeg\ffmpeg.exe")
  #error Bundled ffmpeg.exe not found in PyInstaller output
#endif
#if !FileExists(MyDistRoot + "\_internal\tools\ffmpeg\ffprobe.exe")
  #error Bundled ffprobe.exe not found in PyInstaller output
#endif

[Setup]
AppId={{8E9E4952-8336-4B8A-A6F4-219604E6CC0F}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} version {#MyAppVersion}
AppPublisher={#MyAppPublisher}
VersionInfoVersion={#MyAppVersion}
VersionInfoProductVersion={#MyAppVersion}
VersionInfoProductName=PMSystem
VersionInfoDescription={#MyAppName}
VersionInfoCompany={#MyAppPublisher}
DefaultDirName={autopf}\PMSystem
DefaultGroupName={#MyAppName}
UsePreviousAppDir=yes
AllowNoIcons=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\release\client\{#MyAppVersion}
OutputBaseFilename=PMSystem-Setup-{#MyAppVersion}-x64
SetupIconFile={#MyAppIcon}
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "chinesesimp"; MessagesFile: "ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务："; Flags: unchecked

[Files]
Source: "{#MyDistRoot}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#MyDistRoot}\{#MyAppExeName}"; DestDir: "{app}"; DestName: "{#MyLicenseHelper}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\{#MyAppExeName}"; AppUserModelID: "{#MyAppUserModelID}"
Name: "{commondesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\{#MyAppExeName}"; AppUserModelID: "{#MyAppUserModelID}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "运行{#MyAppName}"; Flags: nowait postinstall skipifsilent

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  ResultCode: Integer;
begin
  if CurUninstallStep = usUninstall then
  begin
    Exec(
      ExpandConstant('{app}\{#MyLicenseHelper}'),
      '--deactivate-before-uninstall',
      '',
      SW_HIDE,
      ewWaitUntilTerminated,
      ResultCode
    );
  end;
end;
