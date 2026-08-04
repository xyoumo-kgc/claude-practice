@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ================================
echo  バーチャルオフィス セットアップ
echo ================================
echo.

rem -- Node.js の確認 --
where node >nul 2>nul
if errorlevel 1 (
  echo [エラー] Node.js が見つかりません。
  echo          https://nodejs.org からインストールしてから、もう一度実行してください。
  echo.
  pause
  exit /b 1
)

echo [1/3] Claude の使用量を初回取得しています...（1分ほどかかることがあります）
node update-usage.mjs
if errorlevel 1 (
  echo [注意] 取得に失敗しました。update-usage.log を確認してください。
  echo        ゲージはサンプル値のまま表示されます。
)
echo.

echo [2/3] 10分おきの自動更新タスクを登録しています...
schtasks /Create /TN "VirtualOfficeUsage" /TR "\"%~dp0update-usage.bat\"" /SC MINUTE /MO 10 /F >nul
if errorlevel 1 (
  echo [注意] タスク登録に失敗しました。管理者権限が必要な環境かもしれません。
) else (
  echo        登録OK: VirtualOfficeUsage（10分おきに usage.js を更新）
)
echo.

set /p OPEN7="毎朝7時にオフィスを自動で開くようにしますか？ (y/N): "
if /i "%OPEN7%"=="y" (
  schtasks /Create /TN "OpenVirtualOffice" /TR "cmd /c start \"\" \"%~dp0office.html\"" /SC DAILY /ST 07:00 /F >nul
  echo        登録OK: OpenVirtualOffice（毎朝7時に office.html を開く）
)
echo.

echo [3/3] オフィスを開きます...
start "" "%~dp0office.html"
echo.
echo 完了！このウィンドウは閉じてOKです。
echo （やめたいときは uninstall.bat を実行）
pause
