# DEC-G1-REOPEN-001: Gate 1再開認可

**決定日:** 2026-08-15  
**決定者:** P0フェーズ正式完了時点  
**決定ID:** DEC-G1-REOPEN-001

---

## 1. 決定内容

**Gate 1を再開し、正式OCR engine候補の新規探索を認可します。**

---

## 2. 背景

### 旧Gate 1の履歴

```
Gate 1: FAILED / FORMALLY_RESOLVED
decision: DEC-G1-EXHAUST-001
timestamp: <when 旧candidatesが exhausted した時点>

tested candidates:
- Tesseract v5.4.0: FAILED
- YomiToku-0.13.1: FAILED

result:
formal candidate = NONE
candidate search = CLOSED
```

旧Decision `DEC-G1-EXHAUST-001` は本Decision内で **保存・保持されます。** 上書き・削除はしません。

### 現在のプロジェクト状態

```
E2E_QUALITY_INDEPENDENT_FOUNDATION: FORMALLY_COMPLETED (2026-08-15)

Implementation status:
- Phase 6  원본保全: ✅ COMPLETED
- Phase 7A OCR環境: ✅ COMPLETED
- Phase 8A Ingestion Worker: ✅ COMPLETED
- Phase 8B Figure Persistence: ✅ COMPLETED
- Phase 9 Output Foundation: ✅ COMPLETED

Blocked phases (no formal candidate):
- Phase 7B engine/profile固定: ⏸ BLOCKED
- Gate 2A OCR品質評価: ⏸ BLOCKED
- Gate 2B AI実用性確認: ⏸ BLOCKED
- Phase 11 quality-dependent operations: ⏸ BLOCKED

Conclusion:
Product core goal requires real OCR engine
→ formal candidate必須
→ Phase 7B以降のunblock必須
```

---

## 3. 再開認可の条件確認

### 再開許可条件

| 条件 | 状態 | 根拠 |
|---|---|---|
| formal candidate = NONE | ✅ 確認 | DEC-G1-EXHAUST-001により正式決定 |
| Phase 7B blocked | ✅ 確認 | engine/profile固定待ち |
| Gate 2A待機中 | ✅ 確認 | Phase 7B待ち |
| Gate 2B待機中 | ✅ 確認 | Gate 2A待ち |
| core goal にreal OCR必須 | ✅ 確認 | capture→OCR→structured output→AI の正式architecture |
| repo正本に再開禁止規定なし | ✅ 確認 | PLAN/HANDOVER上に禁止なし |
| Acceptance isolationを維持可 | ✅ 確認 | 本Decision内で isolation enforcement確保 |

**全条件確認済み。再開を認可します。**

---

## 4. 再開Scope

本Decisionによる再開は、**新しいOCR engine候補の eligibility screening → environment installation → Calibration evaluation** を実施するための authorization です。

### スコープ内

```
✅ 新OCR候補engine（Tesseract/YomiToku以外）の探索・screening
✅ 候補engineの環境構築（Python venv等）
✅ Calibration set（10ページ）でのOCR評価
✅ 旧Decisionを参考にした comparative analysis
✅ formal candidate候補の絞込み
```

### スコープ外（禁止）

```
❌ Acceptance set の使用（isolation保持）
❌ real productionデータへのOCR実行
❌ Engine selection decision内での正式採用判定
❌ Phase 7B fixed engine version決定（形式上の候補選定まで）
❌ Gate 2A実施（Phase 7B待ち）
❌ Gate 1 PASS判定変更（本Decision内では判定不変）
```

---

## 5. 実施フェーズ（次工程）

本Decisionによる再開は、以下Phaseで実施されます：

```
P1: Gate1_Reopened_Candidate_Qualification
    - OCR candidate inventory
    - Eligibility screening
    - Environment installability
    - Calibration evaluation (10 pages)
    - Formal candidate selection (最大1候補）

P2: Phase 7B
    - Selected engine version / trained data / parameters 固定

P3: Gate 2A
    - Acceptance set上でのOCR品質評価

P4: Gate 2B
    - AI投入用途性確認

P5: Phase 11 quality-dependent
    - qualified/disposable/purge classification完成
```

本Decisionはこれ以上の先行実装を認可するものではありません。

---

## 6. 制約条件

### 6-1 Acceptance Isolation

```
Acceptance dataset: PRESERVED / UNCHANGED / INACCESSIBLE

Calibration dataset: 
使用可（前Gate 1比較基準として参照可）

New Engine Calibration evaluation:
Calibration setのみ使用
```

### 6-2 Tesseract / YomiToku

```
旧Decision DEC-G1-EXHAUST-001 に基づき:
- Tesseract: NOT FORMALLY SELECTED (旧evaluation結果参考可)
- YomiToku: NOT FORMALLY SELECTED (旧evaluation結果参考可)

新Decisionでも同様:
- 両engineを「正式採用」として扱わない
- 新candidate同等に評価する
- 旧評価結果は単なる参考資料扱い
```

### 6-3 Gate 1 State

```
Previous:
Gate 1 = FAILED / FORMALLY_RESOLVED
decision = DEC-G1-EXHAUST-001

This Decision (DEC-G1-REOPEN-001):
adds reopen authorization
does NOT change previous decision state
does NOT imply future PASS

both decisions coexist in history
```

---

## 7. 代替案の検討

| 選択肢 | 影響 |
|---|---|
| **A. 再開する（本Decision）** | Phase 7B～11のunblock 必須選択 |
| B. 再開しない | real OCR engine なし  →  core product incomplete  →  不可 |
| C. 棚上げ（延期） | 同上 |

real OCR engine がcore requirementである以上、**再開は必須です。**

---

## 8. レビュー・承認

| ロール | 確認 |
|---|---|
| Development | P0フェーズ正式完了により implicit approval |
| Project | User指示により E2E完了→P1へ進め、という指示あり |
| Architecture | dependency chain confirm済み |

---

## 9. Decision履歴管理

```
DEC-G1-EXHAUST-001 (旧)
↓ [参考・比較基準]
DEC-G1-REOPEN-001 (本)
→ [実装引継ぎ] P1フェーズへ
```

**両Decisionは並行して保存されます。** 旧をArchive化・削除しません。

---

## 10. 実装注記

### 候補探索方針

P1実施時には以下を推奨：

1. **Free/OpenSource engine優先:** ライセンス・コスト・長期保守性を考慮
2. **日本語対応必須:** 縦書き判定・vertical text OCRが essential
3. **CPU-only実行可:** GPU非搭載環境での動作
4. **前Gate参考活用:** Tesseract/YomiToku評価基準を新engineにも適用
5. **Calibration efficiency:** 10ページで candidate判別可能な metrics設計

### 旧evaluationの参考方法

```
DEC-G1-EXHAUST-001時点:

Tesseract:
- Major error(行順破壊): 11件
- Minor error(文字誤認): 3件
- None (正常): 36件
- Page PASS: 5/10
- Dataset PASS: NO

YomiToku:
- Major error: 4件
- Minor error: 0件
- None: 46件
- Page PASS: 6/10
- Dataset PASS: NO

→ 新engineはこれ以上の精度を目指す
→ 特に Major error(順序破壊)を重視
```

---

## 11. 最終確認

```
このDecisionにより:

✅ Gate 1 新候補探索cycle開始 authorized
✅ Phase 7B unblock条件整備 開始可
✅ Acceptance isolation maintained
✅ 旧Gate 1履歴保存 継続
✅ 正式採用判定 先送り (P1完了後)

Reopen:
YES (explicit, conditional, bounded)
```
