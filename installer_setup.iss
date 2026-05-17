[Setup]
AppName=Калькулятор Транспортного Налога
AppVersion=1.0
AppPublisher=TaxCalculator
AppPublisherURL=
DefaultDirName={autopf}\TaxCalculator
DefaultGroupName=Калькулятор Транспортного Налога
UninstallDisplayIcon={app}\tax_app.exe
Compression=lzma2
SolidCompression=yes
OutputBaseFilename=Setup_Калькулятор_ТН
SetupIconFile=icon.ico
WizardImageFile=
WizardSmallImageFile=
LicenseFile=
InfoBeforeFile=
InfoAfterFile=
PrivilegesRequired=lowest
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; GroupDescription: "Дополнительные ярлыки:"
Name: "quicklaunchicon"; Description: "Создать ярлык в панели быстрого запуска"; GroupDescription: "Дополнительные ярлыки:"; Flags: unchecked
Name: "startmenuicon"; Description: "Создать ярлык в меню Пуск"; GroupDescription: "Дополнительные ярлыки:"; Flags: checkablealone

[Files]
Source: "dist\tax_app.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "icon.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Калькулятор Транспортного Налога"; Filename: "{app}\tax_app.exe"; WorkingDir: "{app}"
Name: "{group}\{cm:UninstallProgram,Калькулятор Транспортного Налога}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Калькулятор ТН"; Filename: "{app}\tax_app.exe"; WorkingDir: "{app}"; Tasks: desktopicon
Name: "{userappdata}\Microsoft\Internet Explorer\Quick Launch\Калькулятор ТН"; Filename: "{app}\tax_app.exe"; WorkingDir: "{app}"; Tasks: quicklaunchicon

[Run]
Filename: "{app}\tax_app.exe"; Description: "Запустить Калькулятор Транспортного Налога"; Flags: nowait postinstall skipifsilent

[Code]
procedure InitializeWizard;
begin
  WizardForm.WelcomeLabel1.Caption := 'Добро пожаловать в мастер установки';
  WizardForm.WelcomeLabel2.Caption := 'Калькулятор Транспортного Налога';
end;
