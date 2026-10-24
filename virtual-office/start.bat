@echo off
rem バーチャルオフィスのサーバーを裏で起動して、ブラウザで開きます（起動済みなら開くだけ）。
cd /d "%~dp0"
powershell -NoProfile -WindowStyle Hidden -Command "Start-Process -FilePath node -ArgumentList 'server.mjs' -WorkingDirectory (Get-Location) -WindowStyle Hidden -RedirectStandardOutput server.log -RedirectStandardError server.err.log"
timeout /t 2 /nobreak >nul
start "" http://127.0.0.1:4649
