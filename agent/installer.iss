#define MyAppVersion "2.1.0"
[Setup]
AppId={{6A84D957-B2F0-48AF-BD80-7C9EDACF8971}
AppName=PriceSnap Agent
AppVersion={#MyAppVersion}
AppPublisher=PriceSnap
AppPublisherURL=https://cardifyrbx.shop
DefaultDirName={localappdata}\Programs\PriceSnap Agent
DefaultGroupName=PriceSnap Agent
PrivilegesRequired=lowest
OutputDir=..\backend\releases
OutputBaseFilename=PriceAgent_Setup
SetupIconFile=pricesnap.ico
UninstallDisplayIcon={app}\PriceAgent.exe
Compression=lzma2
SolidCompression=yes
CloseApplications=yes
RestartApplications=yes
CloseApplicationsFilter=PriceAgent.exe
WizardStyle=modern

[Files]
Source: "dist\PriceAgent\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\PriceSnap Agent"; Filename: "{app}\PriceAgent.exe"
Name: "{autodesktop}\PriceSnap Agent"; Filename: "{app}\PriceAgent.exe"

[Run]
Filename: "{app}\PriceAgent.exe"; Description: "Запустить PriceSnap Agent"; Flags: nowait postinstall skipifsilent

[Code]
function HasWebView: Boolean;
var V: String;
begin
  Result := (RegQueryStringValue(HKLM32, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', V) and (V <> '') and (V <> '0.0.0.0')) or
    (RegQueryStringValue(HKCU, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', V) and (V <> '') and (V <> '0.0.0.0'));
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var Code: Integer; RuntimePath: String;
begin
  Result := '';
  if not HasWebView then begin
    RuntimePath := ExpandConstant('{tmp}\MicrosoftEdgeWebview2Setup.exe');
    try
      DownloadTemporaryFile('https://go.microsoft.com/fwlink/p/?LinkId=2124703', 'MicrosoftEdgeWebview2Setup.exe', '', nil);
      if not Exec(RuntimePath, '/silent /install', '', SW_HIDE, ewWaitUntilTerminated, Code) or (Code <> 0) then
        Result := 'Не удалось установить Microsoft Edge WebView2 Runtime. Установите его и повторите попытку.';
    except
      Result := 'Не удалось скачать Microsoft Edge WebView2 Runtime. Проверьте подключение к интернету.';
    end;
  end;
end;
