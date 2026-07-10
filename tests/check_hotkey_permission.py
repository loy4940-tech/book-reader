"""OS権限確認用の最小スクリプト。F9押下でコンソールに出力できるか確認する。
グローバルフックが取得できない場合、管理者権限で実行するか確認すること。
"""
import keyboard

print("F9を押してください（Ctrl+Cで終了）")
keyboard.add_hotkey("F9", lambda: print("F9が検知されました。権限は正常です。"))
keyboard.wait()
