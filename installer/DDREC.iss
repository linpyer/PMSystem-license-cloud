#define MyAppName "DD Rec"
#ifndef MyAppVersion
  #error MyAppVersion must be supplied by build_installer.bat
#endif
#define MyAppPublisher "JsonLin"
#define MyAppExeName "DDREC.exe"
#define MyAppUserModelID "JsonLin.DDREC"
#define MyLicenseHelper "DDRECLicenseHelper.exe"
#define MyAppIcon "..\app\assets\app_icon.ico"
#define MyDistRoot "..\dist\DDREC"
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
AppId={{A6F47CF0-90AC-4497-875B-749A17A42C31}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} version {#MyAppVersion}
AppPublisher={#MyAppPublisher}
VersionInfoVersion={#MyAppVersion}
VersionInfoProductVersion={#MyAppVersion}
VersionInfoProductName=DDREC
VersionInfoDescription={#MyAppName}
VersionInfoCompany={#MyAppPublisher}
DefaultDirName={autopf}\DDREC
DefaultGroupName={#MyAppName}
UsePreviousAppDir=yes
AllowNoIcons=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\release\client\{#MyAppVersion}
OutputBaseFilename=DDREC-Setup
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
