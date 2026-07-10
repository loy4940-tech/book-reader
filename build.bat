@echo off
REM 自動ページめくりプログラムのexeをビルドする。
REM 使い方: venvを有効化した状態で build.bat を実行。

echo === PyInstaller でexeをビルドします ===
python -m PyInstaller AutoPageTurner.spec --noconfirm
if errorlevel 1 (
    echo ビルドに失敗しました。
    exit /b 1
)

echo === config.json を dist にコピーします ===
copy /Y config.json dist\config.json

echo.
echo 完了しました。dist\AutoPageTurner.exe を実行してください。
echo config.json は exe と同じフォルダに置いて編集できます。
