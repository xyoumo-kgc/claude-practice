@echo off
chcp 65001 >nul
echo 登録したタスクを削除します...
schtasks /Delete /TN "VirtualOfficeUsage" /F
schtasks /Delete /TN "OpenVirtualOffice" /F 2>nul
echo 完了。ファイル自体は残っているので、フォルダごと削除すれば全部消えます。
pause
