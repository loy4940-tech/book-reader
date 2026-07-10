@echo off
REM 自動ページめくりプログラムのexeをビルドする。
REM 使い方: venvを有効化した状態で build.bat を実行。
REM   build.bat        … GUI版とコンソール版の両方をビルド
REM   build.bat gui    … GUI版のみ
REM   build.bat cui    … コンソール版のみ

if "%1"=="cui" goto cui
if "%1"=="gui" goto gui

:gui
echo === GUI版 AutoPageTurnerGUI.exe をビルドします ===
python -m PyInstaller AutoPageTurnerGUI.spec --noconfirm
if errorlevel 1 ( echo GUI版のビルドに失敗しました。& exit /b 1 )
if "%1"=="gui" goto copy

:cui
echo === コンソール版 AutoPageTurner.exe をビルドします ===
python -m PyInstaller AutoPageTurner.spec --noconfirm
if errorlevel 1 ( echo コンソール版のビルドに失敗しました。& exit /b 1 )

:copy
echo === config.json を dist にコピーします ===
copy /Y config.json dist\config.json

echo.
echo 完了しました。
echo   GUI版      : dist\AutoPageTurnerGUI.exe （ダブルクリックで起動、ボタン操作）
echo   コンソール版: dist\AutoPageTurner.exe   （ダブルクリックで起動、F9/F10操作）
echo config.json は exe と同じフォルダに置いて編集できます。
