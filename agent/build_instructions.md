# Сборка PriceAgent_Setup.exe

1. Установите Python 3.12 и SumatraPDF в каталог `agent/`.
2. Выполните в PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pyinstaller --noconfirm --clean --onefile --noconsole --name PriceAgent --collect-all customtkinter --collect-all numpy --add-data "SumatraPDF.exe;." agent.py
```

3. Для прямого скачивания скопируйте `dist\PriceAgent.exe` в `backend\releases\PriceAgent_Setup.exe`. Это исполняемая программа без мастера установки.

4. Необязательно: для создания мастера установки установите Inno Setup 6 и сохраните следующий скрипт как `PriceAgent.iss` рядом с `agent.py`:

```iss
[Setup]
AppName=PriceAgent
AppVersion=1.0.0
DefaultDirName={autopf}\PriceAgent
DefaultGroupName=PriceAgent
OutputBaseFilename=PriceAgent_Setup
Compression=lzma
SolidCompression=yes

[Files]
Source: "dist\PriceAgent.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\PriceAgent"; Filename: "{app}\PriceAgent.exe"
```

5. Откройте `PriceAgent.iss` в Inno Setup и нажмите **Compile**. Получившийся `Output\PriceAgent_Setup.exe` можно распространять отдельно.
