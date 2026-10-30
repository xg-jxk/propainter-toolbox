; Inno Setup 安装脚本：把 dist\ProPainterToolbox 打成安装包
; 生成：ISCC.exe build\installer.iss
; 产物：build\out\ProPainterToolbox-Setup-1.3.6.exe
;
; 设计：装到 %LOCALAPPDATA%\Programs\ProPainterToolbox（免 UAC，且能写 .venv）
;       首次启动由应用引导在线安装运行时（PyTorch/权重/Real-CUGAN）

#define MyAppName "ProPainter Toolbox"
#define MyAppVersion "1.3.6"
#define MyAppPublisher "xg-jxk"
#define MyAppExeName "ProPainterToolbox.exe"

[Setup]
AppId={{8E4C2B1A-6F3D-4A57-9C21-0B7A9D7E5C11}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\ProPainterToolbox
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=out
OutputBaseFilename=ProPainterToolbox-Setup-{#MyAppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
SetupIconFile=..\app\resources\app.ico

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务:"

[Files]
Source: "..\dist\ProPainterToolbox\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "立即运行"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; 只删程序目录里的产物，weights/.venv 留给用户自行清理
Type: filesandordirs; Name: "{app}\_internal"
