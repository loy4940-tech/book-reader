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
| Phase 4 | テスト・調整 | 進行中 |
| Phase 5 | パッケージング | 未開始 |

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
