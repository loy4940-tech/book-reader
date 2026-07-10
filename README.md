# 自動ページめくりプログラム（Book Reader Auto Page Turner）

電子書籍やPDFを自動でページめくりするPythonスクリプトです。設定可能な待機時間とランダム幅により、自然な読書ペースをシミュレートします。

## 特徴

- ✅ **ランダム待機時間:** 固定間隔ではなく、指定範囲内でランダムに待機（より自然な読書パターン）
- ✅ **フォーカス管理:** 対象ウィンドウが非アクティブの場合は自動スキップ
- ✅ **ページ遷移検証:** スクリーンショット差分でページめくりの成功を確認
- ✅ **ホットキー制御:** F9で開始/一時停止、F10で終了
- ✅ **詳細ログ:** コンソール・ファイル出力で運用管理
- ✅ **例外処理:** 権限エラー・ウィンドウ消失等を個別に対応

## システム要件

- **OS:** Windows 10/11, macOS, Linux
- **Python:** 3.8 以上
- **権限:** ホットキー使用時は管理者権限が必要（Windows）

## インストール

```bash
# 仮想環境作成
python -m venv venv

# 仮想環境有効化
# Windows
venv\Scripts\activate
# macOS/Linux
source venv/bin/activate

# 依存パッケージインストール
pip install -r requirements.txt
```

## 使用方法

### 1. 設定ファイル作成 (`config.json`)

```json
{
  "target_window_title": "対象アプリのウィンドウタイトル",
  "turn_key": "right",
  "min_interval": 8,
  "max_interval": 14,
  "jitter_distribution": "uniform",
  "max_turns": null
}
```

**設定項目：**
- `target_window_title`: 対象アプリウィンドウのタイトル（部分一致で判定）
- `turn_key`: ページめくり用キー（`right`, `space`, `pagedown` など）
- `min_interval`: 待機時間最小値（秒）
- `max_interval`: 待機時間最大値（秒）
- `jitter_distribution`: 分布方式（`uniform` または `gaussian`）
- `max_turns`: 最大ターン数（`null`で無制限）
- `verify_page_change`: ページ遷移検証を有効化するか（`true`/`false`）
- `diff_threshold`: 変化ありと判定する差分の閾値（0.0〜1.0）
- `max_consecutive_no_change`: 連続で変化を検出できなかった場合に自動停止する回数
- `auto_flip_on_no_change`: 起動直後に空振りが続く場合、左右方向を一度だけ自動反転するか

### 動作方式（方式A：バックグラウンド）

対象ウィンドウを**アクティブにせず**、Win32 の PostMessage で直接キーを送信します。
そのため、Kindle を他ウィンドウの裏に隠したまま別アプリで作業を続けられます。
ページ遷移検証は PrintWindow API を使い、隠れたウィンドウの中身も撮影して比較します。

### ページめくり方向について

縦書き（右→左）の本は「次ページ＝左キー」、横書き（左→右）の本は「次ページ＝右キー」と
本によって異なります。基本は `turn_key` で本ごとに指定してください（②主軸）。
本の先頭から開始して設定が逆だった場合は、`auto_flip_on_no_change` により
一度だけ自動で左右反転して救済します（③保険）。ただし本の途中から逆方向で始めた場合は
画面が変化してしまうため自動検知できません。その場合は `turn_key` を正しく設定してください。

### 2. スクリプト実行

```bash
python main.py
```

### 3. ホットキー操作

- **F9:** スクリプト開始/一時停止（トグル）
- **F10:** スクリプト完全終了

## 開発フェーズ

詳細は [PLAN.md](./PLAN.md) を参照してください。

| フェーズ | 目標 | ステータス |
|---------|------|----------|
| Phase 0 | 対象操作の実地検証 | ✅ 完了 |
| Phase 1 | 環境構築・権限確認 | ✅ 完了 |
| Phase 2 | コアロジック実装 | ✅ 完了 |
| Phase 3 | 制御機能追加 | ✅ 完了 |
| Phase 4 | テスト・調整 | ✅ 完了 |
| Phase 5 | パッケージング | ✅ 完了 |

## exe化（配布用ビルド）

Python環境がないPCでも起動できる単一exeを作成できます。

```powershell
# venvを有効化した状態で
.\build.bat
```

または手動で：

```powershell
python -m PyInstaller AutoPageTurner.spec --noconfirm
copy config.json dist\config.json
```

生成物は `dist\AutoPageTurner.exe` です。**`config.json` を exe と同じフォルダに置く**ことで、
非エンジニアでもテキストエディタで設定を変更できます。ログは `dist\logs\app.log` に出力されます。

## ライセンス

MIT License

## 注意事項

- 対象アプリの利用規約を確認し、自動操作が許可されていることを確認してください
- `pyautogui.FAILSAFE`は有効です。マウスを画面四隅に移動させると緊急停止します
- キー操作が対象アプリに届かない場合は、スクリプトを管理者権限で実行してください

## トラブルシューティング

### キーが送信されない
- スクリプトを管理者権限で実行してください
- 対象ウィンドウがアクティブか確認してください

### ホットキーが反応しない
- Windows: スクリプトを管理者権限で実行してください
- macOS: ターミナルに「アクセシビリティ」権限を付与してください

### ページめくりを検知できない
- 対象アプリの待機時間を増やしてみてください
- ページめくり後の画面変化が小さい場合、差分検出の閾値を調整してください

## 参考資料

- [pyautogui ドキュメント](https://pyautogui.readthedocs.io/)
- [keyboard ライブラリ](https://github.com/boppreh/keyboard)
- [Pillow ドキュメント](https://python-pillow.org/)
