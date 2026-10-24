@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ==========================================
echo  バーチャルオフィス セットアップ（リアルタイム版）
echo ==========================================
echo.

rem -- Node.js 18 以上があるか確認 --
where node >nul 2>nul
if errorlevel 1 goto nonode
node -e "process.exit(+process.versions.node.split('.')[0]<18?1:0)"
if errorlevel 1 goto nonode

echo [1/4] Claude Code にフックを登録しています...
node install.mjs
if errorlevel 1 goto failed
echo.

echo [2/4] 古い「10分おき更新タスク」があれば削除します（サーバーが代わりに更新します）
schtasks /Delete /TN "VirtualOfficeUsage" /F >nul 2>nul
echo.

echo [3/4] オフィスのサーバーを起動して、ブラウザで開きます...
call "%~dp0start.bat"
echo.

set /p OPEN7="[4/4] 毎朝7時にオフィスを自動で開くようにしますか？ (y/N): "
if /i "%OPEN7%"=="y" schtasks /Create /TN "OpenVirtualOffice" /TR "\"%~dp0start.bat\"" /SC DAILY /ST 07:00 /F >nul
if /i "%OPEN7%"=="y" echo        登録OK: 毎朝7時にオフィスが開きます
echo.
echo 完了！ブラウザに「LIVE 接続中」と出ていれば成功です。
echo ※ いま開いている Claude Code は一度終了して起動し直してください（フックは起動時に読み込まれます）
echo （やめたいときは uninstall.bat）
pause
exit /b 0

:nonode
echo [エラー] Node.js 18 以上が見つかりません。
echo          https://nodejs.org からインストールしてから、もう一度実行してください。
pause
exit /b 1

:failed
echo [エラー] フック登録に失敗しました。上のメッセージを確認してください。
pause
exit /b 1
