# Сборка PriceSnap Agent

В Windows установите Python 3.12, Inno Setup 6 и поместите `SumatraPDF.exe` в `agent/`. В каталоге `agent/` выполните:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pyinstaller --noconfirm --clean PriceAgent.spec
iscc installer.iss
```

Результат: `backend/releases/PriceAgent_Setup.exe`. При выпуске обновления синхронизируйте версию в `version.py`, `installer.iss` и настройке backend `AGENT_VERSION`. Установщик предназначен для установки в профиль пользователя и при необходимости загружает WebView2 Runtime с сайта Microsoft.
