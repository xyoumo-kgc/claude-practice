@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo バーチャルオフィスを解除します...
node install.mjs --uninstall
node -e "fetch('http://127.0.0.1:4649/api/shutdown',{method:'POST',headers:{'content-type':'application/json'},body:'{}'}).catch(()=>{})"
schtasks /Delete /TN "OpenVirtualOffice" /F >nul 2>nul
schtasks /Delete /TN "VirtualOfficeUsage" /F >nul 2>nul
echo.
echo 完了。フック・自動起動・タスクを削除し、サーバーを停止しました。
echo ファイル自体は残っているので、フォルダごと削除すれば全部消えます。
pause
