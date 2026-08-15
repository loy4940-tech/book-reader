# 引き継ぎ書（OCR機能追加 / Phase 6〜11）

作成日: 2026-08-12

---

## 0. この文書について

Kindle自動ページめくり＋画面キャプチャツールに、**OCRによるテキスト抽出機能**を追加する作業の引き継ぎ資料。設計は確定済みで、実装は Phase 6 の途中まで完了している。

**最初に読むべきもの**

| 順 | ファイル | 内容 |
|---|---|---|
| 1 | この `HANDOVER.md` | 現在地・注意点・次の手順 |
| 2 | [PLAN.md](PLAN.md) の「Phase 6 以降」（192行目〜） | **仕様の正本**。設計判断はすべてここに集約 |
| 3 | [README.md](README.md) | 既存機能（キャプチャ・ページめくり）の使い方 |

PLAN.md の Phase 0〜5 は既存機能の開発記録であり、今回の作業とは直接関係しない。

---

## 1. プロジェクト概要

**目的**：Kindleの書籍内容を要約・構造化・知識抽出したい。そのためのテキストを用意する。

**現状**：ページめくりとキャプチャ、PDF化までは実装済み・稼働中。テキストは未取得。

**やること**：キャプチャ済みPNGからローカルOCRでテキストを抽出し、AIエージェントに投入できる形式で出力する。

**重要な制約**

| 制約 | 内容 |
|---|---|
| コスト | ゼロ。OCRのAPI従量課金は使わない（ローカルOCRのみ） |
| 精度要件 | ルビ混入は許容。**読み順の保持が最優先**（出口がAIなので文字誤りは文脈で回復するが、順序破壊は回復しない） |
| 抽出方式 | 画面キャプチャのみ。DRM解除を伴う経路は本プロジェクトの対象外 |
| 配布 | キャプチャ側のexe配布は維持。**OCR側はexe化しない** |

---

## 2. 現在地

```
Phase 6   原本保全・評価基盤
  ✅ 6-1 keep_png_after_pdf を true に（config 2ファイル）
  ✅ 6-2 config を「既定値＋ユーザー上書き」方式へ再設計
  ✅ 6-3 build.bat がユーザー設定を上書きしないよう修正
  ✅ 6-4 セッション整合性チェック実装（tools/verify_session.py）
  ✅ 6-5 撮影条件の metadata 記録
  ⬜ 6-6 Kindle運用条件の適用（全画面＋文字サイズ2〜3段階UP）※要ユーザー操作
  ⬜ 6-7 日本語縦書き書籍20ページのキャプチャ ※要ユーザー操作
  ⬜ 6-8 Calibration / Acceptance への層化分割
  ⬜ 6-9 gold text（正解テキスト）の作成

Phase 7A  候補OCRの評価環境構築
  ✅ requirements-ocr.txt / tools/ocr_env_check.py 作成
  ✅ Python 3.12.10 と Tesseract v5.4.0.20240606 の導入
  ✅ eng / jpn / jpn_vert とOCR専用venvの検証
  ✅ ocr_environment.json の初期環境manifest生成
  ✅ 非Acceptance画像1ページのTesseract smoke test

Gate 1  DEFERRED（E2E implementation completionまで延期）
  Tesseract: TEMPORARY / UNVALIDATED

Gate 1 exact spec corrective work（2026-08-14）:
  `GATE1_EXACT_SPEC_MISSING = RESOLVED`
  Gate 1 = `NOT_STARTED / READY`
  canonical specificationはPLAN.md「Gate 1 canonical specification」を参照
  runner / validator / tests = `tools/run_gate1.py` / `tools/validate_gate1.py` / `tests/test_gate1.py`
  Gate 1正式OCR run = 0、Acceptance isolation = ACTIVE
  `PHASE8B_BLANK_SPEC_RECONCILIATION = OPEN / NOT_GATE1_PREREQUISITE`
  validator CLI import blockerは2026-08-14に解消済み。Gate 1 = `NOT_STARTED / READY_FOR_FORMAL_RERUN`、正式OCR run = 0。
  `GATE1_FORMAL_EVIDENCE_FINALIZATION_MISSING = RESOLVED`。Gate 1 = `NOT_STARTED / READY_FOR_NEW_FORMAL_RUN`。
  historical blocked attempt `G1-20260814T093205+0900` はCalibration OCR 10実行を確認済み。Acceptance access 0、再利用・final昇格なし。今後はhistorical実行数とcurrent formal run実行数を分離して報告する。
  `GATE1_RUN_ID_PROPAGATION_BLOCKER = RESOLVED`。blocked Stage A attempt `G1-20260814T102416+0900`（evidence run_id誤記録=`formal`、OCR 10実行）は再利用しない。Gate 1 = `NOT_STARTED / READY_FOR_NEW_STAGE_A_RUN`。
  `GATE1_EMPTY_OUTPUT_STATUS_CLASSIFICATION_BLOCKER = RESOLVED`。runnerはstructured worker JSONをparseし、canonical `text == ""`を`EMPTY_OUTPUT`へ分類する。finalizer / validatorはstatusと参照OCR textの矛盾を拒否する。human review済みrun `G1-20260814T110014+0900`は`BLOCKED AFTER HUMAN REVIEW`、reuse=`NO`。Gate 1 = `NOT_STARTED / READY_FOR_NEW_STAGE_A_RUN`、current eligible formal OCR executions = 0。
  `GATE1_FINAL_EVIDENCE_SCHEMA_SELECTION_RESULT_MISMATCH = RESOLVED`。final evidenceのselectionは`gate_status / selection_result / candidate_id` aggregate objectでschema・finalizer・validator・testsを統一。formal run `G1-20260814T165448+0900`のStage B retryはfinalizer / JSON Schema / canonical validatorすべてPASS。`HUMAN-GATE-G1-REVIEW-002 = COMPLETED`、Major=11、Minor=3、None=36、page PASS=5/10、EMPTY_OUTPUT=1、dataset PASS=NO、Gate 1=`FAILED`、provisional selection=`NO_SELECTION`。Tesseractは`TEMPORARY / UNVALIDATED`のまま。
`HUMAN-GATE-G1-NEXT-ENGINE-001 = APPROVED`。YomiToku `yomitoku-0.13.1-cpu-lite-fixed-v1`を非商用個人研究検証用途の次candidateとした。専用Python 3.12 venv、Windows native CPU lite、固定model revision/checksum、offline executionを採用。adapter・candidate dispatch・synthetic Gate 1 E2EとWindows CPU synthetic inferenceはPASS。Gate 1=`FAILED / YOMITOKU_READY_FOR_FORMAL_STAGE_A`、YomiToku quality=`NOT_YET_EVALUATED`、Calibration OCR=0、Acceptance isolation=`ACTIVE`。
`GATE1_YOMITOKU_WORKER_STDOUT_PROTOCOL_DEFECT = RESOLVED`。YomiToku実行中の第三者stdoutをworker内でcaptureしてstderrへ分離し、stdoutをcanonical JSON 1件だけに固定した。runnerのwhole-stdout strict JSON parseは維持。blocked run `G1-20260814T201750+0900`（OCR execution 10）はreuse=`NO`。Gate 1=`YOMITOKU_READY_FOR_NEW_FORMAL_STAGE_A`、corrective work中のCalibration OCR=0、YomiToku quality=`NOT_YET_EVALUATED`。
YomiToku formal run `G1-20260814T203325+0900` はStage B finalizer / JSON Schema / canonical validatorすべてPASS。`HUMAN-GATE-G1-YOMITOKU-REVIEW-001 = COMPLETED`、Major=4、Minor=0、None=46、page PASS=6/10、EMPTY_OUTPUT=2、dataset PASS=NO、YomiToku attempt=`FAILED`、selection=`NO_SELECTION`。Tesseract / YomiTokuの両attemptがFAILEDしcurrent provisional candidateはNONE。candidate exhaustion decisionは直後の`DEC-G1-EXHAUST-001`で解決済み。
`DEC-G1-EXHAUST-001 = RECORDED`。Tesseract / YomiTokuの両canonical candidateが正式FAILEDとなったため、Gate 1=`FAILED / FORMALLY_RESOLVED`、failure code=`CANDIDATE_EXHAUSTED`、candidate attempts=2、passed candidates=0、provisional candidate=`NONE`、candidate search=`CLOSED`。未規定の第3candidate探索は開始せず、将来のengine探索には明示的なGate 1 reopen decisionを要する。Gate 2A=`NOT_STARTED`、Acceptance isolation=`ACTIVE`、`PHASE8B_BLANK_SPEC_RECONCILIATION = OPEN / NOT_GATE1_PREREQUISITE`。`FIGURE_EXTRACTION_PERSISTENCE_FOUNDATION = READY_TO_START`。
`FIGURE_EXTRACTION_PERSISTENCE_FOUNDATION = COMPLETED`。YomiToku structured figure bboxをoriginal source座標へ戻し、deterministic ID、lossless PNG、SHA-256、relative path metadata manifestでatomic / idempotentにfilesystem保存する基盤を追加した。明示的feature optionの既定はdisabled。現repositoryにはDB/migration layerがないためDB変更はなく、binary BLOBも使用しない。canonical OCR text、figure内部text除外、standalone caption、table処理は不変。Gate 1=`FAILED / FORMALLY_RESOLVED`、Acceptance isolation=`ACTIVE`を維持する。
Phase 6の正式dataset完成後に再開
```

**Phase 7Aは完了。Gate 1はcandidate exhaustionにより`FAILED / FORMALLY_RESOLVED`。** Tesseract / YomiTokuはいずれも`FAILED / NO_SELECTION`で、provisional candidateは`NONE`。candidate searchは`CLOSED`、Gate 2AとPhase 7Bの正式環境固定は開始しない。Figure Extraction / Persistence Foundationは`COMPLETED`。

---

## Phase 7C: CAPTURE_SESSION_INGESTION_WORKER_FOUNDATION

**実装完了（2026-08-14）**

CaptureService が生成する captured session を、独立 worker process から discovered・validated・claimed・processed できる single-run CLI 基盤を実装。

### ✅ 実装済み機能

| 機能 | 実装 | 検証 |
|---|---|---|
| Session discovery | `ocr/ingestion.py:discover_sessions()` | tests/test_ingestion_worker.py |
| Readiness validation | `ocr/ingestion.py:validate_session()` | ✅ TERMINAL/NOT_READY/READY states |
| Atomic claim acquisition | `ocr/ingestion.py:acquire_claim()` | ✅ concurrent 1-winner assurance |
| Stale claim recovery | `ocr/ingestion.py:_claim_staleness()` | ✅ crash recovery + audit trail |
| SessionOcrBatch handoff | `ocr/batch.py:SessionOcrBatch.run()` | ✅ session_dir → ocr.json |
| Worker state persistence | `ocr/ingestion.py:write_worker_state()` | ✅ CLAIMED→PROCESSING→COMPLETED/FAILED |
| Independent CLI | `ocr/ingestion_worker.py:main()` | ✅ --capture-root / --candidate-id |
| Completion signal handoff | `.capture_complete.json` + `.bookreader_claim.json` + `.bookreader_ingestion.json` | ✅ testified |

### 📝 Worker CLI Usage

```bash
# Single-run execution: discover session(s), validate, claim, batch, finalize
python -m ocr.ingestion_worker \
  --capture-root output \
  --candidate-id <OCR_ID> \
  [--manifest ocr_environment.json] \
  [--figure-storage-root <PATH>] \
  [--stale-claim-seconds 86400]
```

Output: JSON `[WorkerOutcome, ...]`  
Exit codes: 0 = success, 1 = retryable failure, 2 = terminal failure

### 📁 Session File Semantics

| File | Role | Semantics |
|---|---|---|
| `metadata.json` | Session record | CaptureService created; sessionid, captures, finished_at |
| `.capture_complete.json` | Completion signal | Atomic JSON; ready for handoff |
| `.bookreader_claim.json` | Exclusive lock | Worker PID; stale recovery via pid_alive check |
| `.bookreader_ingestion.json` | State journal | IngestionState enum; retryable/terminal classification |
| `ocr.json` | Batch output | SessionOcrBatch results; atomic write after success |

### 🔗 Integration with Phase 8

Formal OCR candidate = `NONE` のため、live real-engine E2E は未実施。

次 Phase では、

```text
1. OCR engine を選定 (Gate 1 reopen)
2. real engine で SessionOcrBatch を execute
3. OCR品質を Gate 2A で判定
4. 合格後 Phase 9 へ進む
```

その際、本 Foundation の session handoff 部分は **変更されずに利用される** 想定。



E2E先行範囲はcapture / page handling / OCR interface・invocation / raw output / session・path・file管理 / output / logging / error・retry / CLI・UI導線 / functional・regression test。E2E完成はOCR品質合格を意味せず、Gate 1を自動PASSにしない。Acceptance setはE2E開発・debugging・parameter/preprocessing tuning・engine selectionに使用禁止。

Phase 6の6-6〜6-9（正式20ページ、Calibration 10 / Acceptance 10の固定、Calibration gold、capture conditions）は未完了のまま保留する。実書籍画像とgoldは`dist/output`配下の`LOCAL_ONLY`でGit管理しない。本文を含まないdataset metadataはrepository管理可能。`ocrenv/`は`LOCAL_ONLY / GIT_IGNORED`、`ocr_environment.json`はrepository管理を推奨し、正式固定時にabsolute pathのportable性を確認する。

---

## 3. リポジトリ構成

### 今回追加・変更したもの

| ファイル | 状態 | 役割 |
|---|---|---|
| `PLAN.md` | 変更 | Phase 6以降を追記。**仕様の正本** |
| `config_defaults.py` | **新規** | 既定値・マージ・スキーマ照会 |
| `config_loader.py` | 変更 | 既定値マージ、未知キーのERROR化 |
| `build.bat` | 変更 | `dist/config.json` を上書きしない |
| `config.json` / `dist/config.json` | 変更 | `keep_png_after_pdf: true` |
| `screen_capture_pdf/metadata_store.py` | 変更 | `environment` / `pdf_page_count` / `pdf_summary_page` 追加 |
| `screen_capture_pdf/capture_service.py` | 変更 | 撮影条件の収集、PDF情報の記録 |
| `tools/page_analyze.py` | **新規** | 画像解析（解像度・本文領域・組方向・言語・文字サイズ） |
| `tools/capture_probe.py` | **新規** | ライブ診断（`--maximize` で最大化前後を比較） |
| `tools/verify_session.py` | **新規** | セッション整合性・config スキーマ検証 |
| `tools/ocr_env_check.py` | **新規** | OCR環境検証・`ocr_environment.json` 生成 |
| `requirements-ocr.txt` | **新規** | OCR側のpip依存 |

### これから作るもの（Phase 8）

```
ocr/
  config.py       設定読み込み
  classifier.py   言語・組方向の判定
  preprocess.py   本文領域の切り出し・二値化
  dedupe.py       重複／白紙の「分類」（削除ではない）
  engines/
    base.py       抽象インターフェース
    tesseract.py
    yomitoku.py   （Gate 1 で必要と判定された場合のみ）
  runner.py       バッチ実行・resume
  writers.py      出力
run_ocr.py        エントリポイント
```

`tools/page_analyze.py` の判定ロジック（`detect_language` / `_content_box` / `_profile_stats`）は `ocr/classifier.py` と `ocr/preprocess.py` へ移植して使う。

---

## 4. 確定済みの設計判断（再議論不要）

複数回の外部レビューを経て確定した項目。**変更する場合は理由の再検討が必要。**

| ID | 決定 | 理由 |
|---|---|---|
| D01 | キャプチャとOCRを別プロセスに分離 | Python 3.14でPyTorch系が動かない／exe肥大化回避／再実行性 |
| D02 | 原本PNGはOCR後も保持。削除は明示操作のみ | OCR方式を変更した際の再処理性を確保 |
| D03 | OCRエンジンは実OCR結果で選定 | 文字サイズ等の間接指標では精度を予測できない |
| D04 | エンジンは抽象インターフェース経由 | Gate 2Aで差し替える可能性がある |
| D05 | 評価セットを Calibration / Acceptance に分離し、**OCR実行前に**分割を固定 | 評価データへの過適合を防ぐ |
| D06 | Gate 2A（OCR品質）と Gate 2B（AI投入）を分離 | OCR精度とAI性能は別の変数。混ぜると原因を切り分けられない |
| D07 | **Gate 2B は Phase 9 の後**に置く | Gate 2Bが評価するのはPhase 9の出力形式そのもの |
| D08 | 重複・白紙ページは**物理除外せず状態として記録** | 「撮影成功数 = 出力レコード数」の不変条件と元画像への追跡性を維持 |
| D09 | OCRプロファイル認定とセッション検証を分離 | Gate 2Aが認定するのは方式であって個々の書籍ではない |
| D10 | resume は `source_hash` / `ocr_profile_id` 一致時のみ skip | 設定変更後の再実行で新旧OCR結果が混在するのを防ぐ |
| D11 | 未知の設定キーは**ERROR** | 綴り誤りが既定値採用で通ると、データ保持設定が黙って無効になる |
| D12 | MVPはページ構造の保持まで。章構造解析・図版抽出は範囲外 | OCRと文書構造解析は別問題 |
| D13 | 長文分割（chunking）の責任はAIエージェント側 | 章構造解析をOCR側に持ち込まないため |
| D14 | 言語は**書籍単位**判定、組方向は**ページ単位**判定 | `window_title` は書籍単位の情報なので、言語のページ単位自動判定は原理的に不可 |

詳細は PLAN.md の該当節を参照。

---

## 5. 実行環境と実測値

```
CPU        i7-13700H（14コア20スレッド）
GPU        Intel Iris Xe（CUDA非対応）… YomiTokuはCPU実行に限定
RAM        16 GB
空き容量    約875 GB
画面        2880×1800 / スケーリング200% / DPI 192
Python     3.14.2 のみ（OCR用に3.12の別venvが必要）
導入済み    Pillow / reportlab のみ（numpy・OpenCV・Tesseractは未導入）
```

**キャプチャ実測値**

```
キャプチャ全体   1586×1173（ウィンドウ最大化時 2906×1826）
本文領域         1406×865（最大化時 2674×1490）… 全体の65%、残りはKindleのUI
行送り           約28px（最大化しても27.9pxで変わらない）
PNGサイズ        約400KB/ページ → 300ページで約120MB/冊
```

**既存セッション**：21件。うち19件はPNG削除済み（`legacy_pdf_only`）、2件は空（`empty`）。全件で `PDFページ数 = 撮影成功数 + 概要ページ1` が成立し整合性を確認済み。

---

## 6. 次にやること

### 手順1：Phase 7A の完了（ユーザー操作＋検証）

```bash
# 1. Python 3.12 の導入
winget install Python.Python.3.12

# 2. Tesseract の導入
#    winget search tesseract で UB Mannheim 版を探してインストール
#    ★ インストーラの「Additional language data」で
#      Japanese と Japanese (vertical) を必ず選択すること
#      （選ばないと jpn / jpn_vert が入らず縦書き検証ができない）

# 3. OCR用venvの作成
py -3.12 -m venv ocrenv
ocrenv\Scripts\activate
pip install -r requirements-ocr.txt

# 4. 検証と初期環境manifest生成
python tools/ocr_env_check.py --write
```

`判定: OK` が出て `ocr_environment.json` が生成されれば、環境面のPhase 7A完了条件を満たす。Calibration用画像があれば1ページのTesseract smoke testを行い、未取得なら `BLOCKED_BY_SAMPLE` として持ち越してよい。YomiTokuはPhase 7Aの必須環境ではない。`ocr_environment.json` はここでは評価環境の実測証跡であり、Gate 1後のPhase 7Bで採用engine / model / traineddata / parametersを反映して正式に最終固定する。

### 手順2：Phase 6 の残り（評価セット取得）

1. Kindleを**全画面表示**にする（ツールバーの ⛶ アイコン）
2. **文字サイズ（Aa）を2〜3段階上げる**
3. 日本語縦書き書籍を20ページほどキャプチャ
4. 測定：`python tools/page_analyze.py "dist/output/<書籍>/images" --limit 20`
5. PLAN.md 6.9 の層化分割規則に従い Calibration 10 / Acceptance 10 に分割（**OCR実行前に確定すること**）
6. PLAN.md 6.9 の規約に従い gold text を作成
7. `capture_conditions.md` に Kindle表示モード・文字サイズ・フォント・書籍名を記録

### 手順3：Gate 1（エンジン選定）

**現在はDEFERRED。** Calibration 10ページ（3/2/1/2/2）、同構成のAcceptance 10ページ、OCR前の分割固定、Calibration gold 10ページ、`capture_conditions.md`、Acceptance未使用・未汚染、利用可能なOCR環境がすべて揃った場合だけ再開する。再開後はCalibration setをまずTesseractでOCRし、gold textと比較する。判定基準は**行順・段組順の正しさ**（CER/WERは観測指標）。要件を満たせばTesseractをprovisional engineとしてPhase 7Bへ進み、不足する場合のみengine選定を再オープンしてYomiToku候補環境を追加構築し、同じCalibration setで比較する。

---

## 7. 落とし穴（重要）

実作業で実際にハマった点。**知らないと同じ失敗を繰り返す。**

### 7-1. 出力先は `output/` ではなく `dist/output/`

exeは自分と同じフォルダを基準にする（[app_paths.py](app_paths.py)）。リポジトリ直下の `output/` は空。**実データはすべて `dist/output/` にある。**

### 7-2. config は2系統ある

| 実行形態 | 読み込むファイル |
|---|---|
| `python main.py` / `gui.py` | `<repo>/config.json` |
| `AutoPageTurnerGUI.exe` | `dist/config.json` |

**片方だけ直しても実運用に反映されない。** 実際に `screen_capture.enabled` が repo=false / dist=true で乖離していた。旧 `build.bat` は `copy /Y` で無条件上書きしていたため、ビルドすると実運用設定が壊れる状態だった（修正済み）。

### 7-3. 未知の設定キーは起動時エラーになる

`keep_png_after_pdff` のような綴り誤りで `ValueError` が出て起動しない（意図的な仕様、D11）。設定項目を増やすときは **`config_defaults.py` の `DEFAULTS` に必ず追加する**こと。追加を忘れると、その項目を書いたconfigが読めなくなる。

### 7-4. PowerShell / Bash で日本語出力が文字化けする

```powershell
$env:PYTHONIOENCODING='utf-8'
[Console]::OutputEncoding=[System.Text.Encoding]::UTF8
```

を先に実行する。Bash（Git Bash）経由だと cp932 で化けるため、日本語を出すスクリプトは PowerShell から実行するのが確実。

### 7-5. Kindleはリフローするので、ウィンドウ拡大は文字サイズに効かない

実測で確認済み。ウィンドウを最大化すると面積は3.2倍になるが**行送りは28.7px→27.9pxで不変**、行数が28→52に増えるだけ。DPI Awareness も既に `PER_MONITOR_AWARE` で実装済み（[screen_capture.py:11](screen_capture.py:11)）。

**文字を大きくする唯一の手段は Kindle の文字サイズ設定（Aa）。**

### 7-6. キャプチャセッション稼働中はPNGが消えることがある

作業中に実際に発生した。セッション終了時に `finish_session` がPDFを生成し、`keep_png_after_pdf: false` ならPNGを削除する。現在は `true` にしてあるが、**古い設定のまま動いているプロセスがあれば消える**。解析用の画像は別フォルダにコピーしておくのが安全。

### 7-7. `page_analyze.py` の組方向判定は図版ページで不安定

本文ページでは正しく判定できるが、図版が主体のページやカバーページでは誤判定する。**書籍単位の多数決で使う前提**。個別ページの判定を信用しすぎないこと。

なお、当初は自己相関で周期を検出していたが、横書きでも文字ピッチが周期を作るため区別できず、**行間の空白帯の検出**に変更した経緯がある。同じ轍を踏まないこと。

### 7-8. 未コミットの変更が多数ある

このセッション開始時点で、`README.md` / `gui.py` / `main.py` / `screen_capture.py` / `tests/test_screen_capture_pdf.py` は**既に変更済み**だった（今回の作業とは無関係）。今回の変更と混在しているため、コミットする際は内容を確認すること。**現時点でコミットは一度も行っていない。**

---

## 8. 検証コマンド

```bash
# 既存テスト（44件）
venv\Scripts\python.exe -m pytest tests -q

# セッション整合性（全21件）
venv\Scripts\python.exe tools\verify_session.py

# config スキーマ互換性
venv\Scripts\python.exe tools\verify_session.py --config-diff

# 画像解析
venv\Scripts\python.exe tools\page_analyze.py "dist/output/<書籍>/images" --limit 8

# ライブ診断（Kindle起動が必要）
venv\Scripts\python.exe tools\capture_probe.py --maximize

# OCR環境検証
python tools\ocr_env_check.py
```

いずれも Pillow 以外の依存なしで動く（`ocr_env_check.py` は標準ライブラリのみ）。

---

## 9. 未検証事項

| 項目 | 状態 | 影響 |
|---|---|---|
| Tesseractの縦書き日本語精度 | 未検証 | Gate 1 で判定。不足ならYomiTokuへ |
| YomiToku の CPU実行速度 | 未検証 | GPU非搭載のため遅い可能性 |
| Python 3.12 での PyTorch 動作 | 未検証 | Fallback時のブロッカーになりうる |
| 日本語ページの実効文字サイズ | **未測定** | Kindle設定変更後に測定。Gate 1 の前提条件 |
| PDFのピクセル同一性 | 未検証 | FlateDecode使用・DCTDecodeなし・画像幅一致までは確認済み。復旧元として利用可能と考えられるが、元PNGとのピクセル一致は未確認。MVPのブロッカーではない |

---

## 10. 工数見積もり（planning estimate・実績ではない）

| ケース | 合計 |
|---|---|
| Base（Tesseractで通過） | 約7日 |
| Fallback（YomiToku切替） | ＋2〜3日 |

内訳は PLAN.md 6.11 を参照。**下振れより上振れリスクの方が大きい**と評価している。

---

## 11. 作業の進め方について

この計画は、実装前に外部レビューを複数回通して矛盾を潰してきた経緯がある。特に以下は**レビューで指摘されて修正した項目**なので、元に戻さないこと。

- Gate 2B を Phase 9 の後に移動（順序矛盾の解消）
- dedupe を物理削除から状態分類へ（不変条件の維持）
- OCRプロファイル認定とセッション検証の分離（purge事故の防止）
- resume の鮮度判定（新旧OCR結果の混在防止）
- Gate 2A の合格基準を Acceptance set を見る前に固定（ゴールの後付け防止）

仕様を変更する場合は、PLAN.md の該当節も同時に更新すること。
