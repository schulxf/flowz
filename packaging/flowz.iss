#ifndef AppVersion
  #define AppVersion "0.1.5"
#endif

#define AppName "Flowz"
#define AppExeName "Flowz.exe"
#define RepoRoot ".."

[Setup]
AppId={{C01C32D5-CC87-4F71-ACBA-DA3DE23C52A7}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Flowz
AppPublisherURL=https://github.com/schulxf/flowz
AppSupportURL=https://github.com/schulxf/flowz/issues
AppUpdatesURL=https://github.com/schulxf/flowz/releases
DefaultDirName={localappdata}\Flowz
DefaultGroupName=Flowz
DisableDirPage=yes
DisableProgramGroupPage=yes
OutputDir={#RepoRoot}\release
OutputBaseFilename=FlowzSetup-{#AppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
PrivilegesRequired=lowest
WizardStyle=modern
SetupIconFile={#RepoRoot}\assets\flowz.ico
WizardImageFile={#RepoRoot}\assets\flowz-installer-sidebar.bmp
WizardSmallImageFile={#RepoRoot}\assets\flowz-installer-small.bmp
WizardImageBackColor=$000B0707
UninstallDisplayIcon={app}\{#AppExeName}
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Messages]
WelcomeLabel1=Install Flowz
WelcomeLabel2=Fast voice dictation for Windows.%n%nHold Ctrl + Windows, speak, release, and Flowz pastes the text where your cursor is.
FinishedHeadingLabel=Flowz is ready
FinishedLabel=Flowz was installed successfully.%n%nOpen Flowz Settings to configure your provider, microphone, ready cue, and startup behavior.

[Tasks]
Name: "startup"; Description: "Start Flowz when Windows starts"; GroupDescription: "Startup options:"; Flags: unchecked

[Files]
Source: "{#RepoRoot}\dist\{#AppExeName}"; DestDir: "{app}"; DestName: "{#AppExeName}"; Flags: ignoreversion restartreplace
Source: "{#RepoRoot}\config.example.json"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#RepoRoot}\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#RepoRoot}\THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#RepoRoot}\uninstall.ps1"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Flowz"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"
Name: "{group}\Flowz Settings"; Filename: "{app}\{#AppExeName}"; Parameters: "--settings"; WorkingDir: "{app}"

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch Flowz"; Flags: nowait postinstall skipifsilent unchecked

[InstallDelete]
Type: filesandordirs; Name: "{userprograms}\FreeFlowWin"
Type: files; Name: "{userprograms}\Flowz\FreeFlowWin.lnk"

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "FreeFlowWin"; Flags: deletevalue
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "Flowz"; Flags: uninsdeletevalue

[Code]
function KillImage(ImageName: String): Boolean;
var
  ResultCode: Integer;
begin
  Exec(
    ExpandConstant('{cmd}'),
    '/C taskkill /IM "' + ImageName + '" /F >NUL 2>NUL',
    '',
    SW_HIDE,
    ewWaitUntilTerminated,
    ResultCode
  );
  Result := True;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  KillImage('Flowz.exe');
  KillImage('FreeFlowWin.exe');
  Result := '';
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  RunValue: String;
begin
  if CurStep = ssPostInstall then
  begin
    RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'FreeFlowWin');

    if WizardIsTaskSelected('startup') then
    begin
      RunValue := '"' + ExpandConstant('{app}\Flowz.exe') + '"';
      RegWriteStringValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'Flowz', RunValue);
    end
    else
    begin
      RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'Flowz');
    end;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
  begin
    KillImage('Flowz.exe');
    KillImage('FreeFlowWin.exe');
    RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'Flowz');
    RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'FreeFlowWin');
  end;
end;
