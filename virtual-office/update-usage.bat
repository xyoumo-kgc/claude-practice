@echo off
rem タスクスケジューラから呼ばれる用。このフォルダに移動して更新スクリプトを実行します。
cd /d "%~dp0"
node update-usage.mjs >> update-usage.log 2>&1
