# approach_minimum / analysis — SCAM2026 paper 用分析パイプライン

`outputs/scam/approach_minimum/integrate/` のクラスタリング結果 (M2 = `integrate.py` の per-depth 出力) を、 SCAM2026 投稿論文 (`thesis/SCAM2026_NoguchiH_ja/main.tex`) の **結果・考察** に落とし込むための分析スクリプトと中間レポートを置く。

paper の現実験結果 (`tab:exp-tau` / `tab:exp-min-size`) は事前分析以外すべて差替える方針。 ここでは新規数値を生成し、 分析ごとに Markdown レポートを作成してユーザレビューを経てから paper 本文へ反映する。

---

## 確定設定

| 項目 | 値 |
|---|---|
| 主軸 method | **M2 = approach_minimum** (per-depth、 class_id prefix `L{level}_M2_*`) |
| τ | **0.7, 0.9 のみ** (0.5 は対象外) |
| level | 0, 1 |
| depth | Diff, Brother, ExParent, Parent |
| 既知パターン | Stage-B 通過 ≥ 1 の **7 種**: 1, 2, 3, 6, 7, 8, 9 |
| 新規パターン候補数 | levelとdepthの各組み合わせから30 件 |
| fast 側データ源 | `outputs/AST_HEAD/scope_*_all.json` |
| 代表値アルゴリズム | mode_medoid — **個別評価** |
| approach_minimum_neo | 本タスクでは扱わない |

---

## depth ↔ AST_HEAD scope ファイル名対応

| depth (本研究) | AST_HEAD scope ファイル |
|---|---|
| Diff (σ1) | `scope_DIFF_BLOCK_all.json` |
| Brother (σ2) | `scope_BROTHER_DIFF_all.json` |
| ExParent (σ3) | `scope_BLOCK_EXCLUDE_PARENT_all.json` |
| **Parent (σ4)** | **`scope_BLOCK_INCLUDE_DIFF_all.json`** (`BLOCK_INCLUDE_PARENT` ではないことに注意) |

---

## 分析スクリプト一覧

| ID | スクリプト | 目的 | レポート | paper 対応 |
|---|---|---|---|---|
| E1 | `E1_recall.py` | 既知 7 パターンを再現できるかの recall 評価 (share/purity/F1) | `E1_recall.md` | §6.2「従来パターンとの被覆」 |
| E2 | `E2_grid.py` | 32 セル (τ×level×depth) のクラス数・単独率・最大占有率 | `E2_grid.md` | §結果1 (tab:exp-tau 差替え) |
| E3 | `E3_min_size.py` | 各事例の min effective size 分布 | `E3_min_size.md` | §結果2 (tab:exp-min-size 差替え) |
| E4 | `E4_singleton.py` | Isolated 性質と巨大擬似クラスタの特性 | `E4_singleton.md` | §6.2「集約されなかったもの」 |
| E5 | `E5_fast_diversity.py` | E1 の top class メンバの fast 側多様性 (AST_HEAD 利用) | `E5_fast.md` | §6.2「fast 側の類似性」 |
| E6 | `E6_novel.py` | 新規パターン候補 30 件 × 4 代表値アルゴリズム × fast 側ペア | `E6_novel.md` | §6.3.2「新規パターン」 |

---

## 共通ユーティリティ (`_common.py`)

- `normalize_value(value)`: integrate.py:80-95 と同一の slot 番号 strip
- `load_classes(tau, level, depth)`: integrate 結果の `{depth}.json` を読込
- `load_representatives(tau, level, depth, strategy)`: 4 代表値 JSON のいずれかを読込
- `load_rq1_ground_truth(pattern_id)`: `outputs/scam/RQ1/pattern_{p}/diff_linked.jsonl` を読込
- `load_ast_head(depth)`: AST_HEAD の depth 対応 scope ファイルを読込
- `DEPTH_TO_SCOPE_FILE`: depth → AST_HEAD ファイル名の辞書

---

## 実行方法

```bash
# 単独実行
uv run python experiments/scam/approach_minimum/analysis/E1_recall.py
uv run python experiments/scam/approach_minimum/analysis/E2_grid.py
# ...

# 全実行 (Markdown レポートは別途手動更新)
for script in experiments/scam/approach_minimum/analysis/E*.py; do
  uv run python "$script"
done
```

各スクリプトは `outputs/` 配下に CSV / JSON を出力し、 stdout にサマリを表示する。 Markdown レポートはスクリプト実行後にユーザ + AI で執筆する。

---

## ワークフロー

```
1. _common.py 完成
2. E1 実装 → E1_recall.csv 生成 → E1_recall.md 執筆 → ユーザレビュー
3. ベスト設定 (τ, level, depth) 確定
4. E2-E6 実装 (E5/E6 は E1 ベスト設定に依存)
5. E1-E6 Markdown レポートを束ねてユーザに最終確認
6. (別タスク) paper 本文の結果・考察セクション差替え
```

---

## 入出力データのパス

| 用途 | パス |
|---|---|
| 入力: クラスタリング結果 | `outputs/scam/approach_minimum/integrate/jaccard{07,09}/level{0,1,2,3}/{Diff,Brother,ExParent,Parent}/` |
| 入力: 既知パターン正解 | `outputs/scam/RQ1/pattern_{1..10}/diff_linked.jsonl` (使うのは 1, 2, 3, 6, 7, 8, 9 のみ) |
| 入力: fast 側 AST | `outputs/AST_HEAD/scope_*_all.json` |
| 入力: bigram cache (E4 で使用) | `outputs/scam/approach_minimum/abstract/bigrams_level0_n2.pkl` |
| 出力: CSV/JSON | `outputs/scam/approach_minimum/analysis/` (= `_common.OUT_DIR`) |
| 出力: 分析レポート (Markdown) | `experiments/scam/approach_minimum/analysis/E{1..6}_*.md` |

**コード/レポート ↔ データ成果物の分離**: スクリプトと中間レポートは `experiments/` 配下、 CSV/JSON 等の集計成果物は `outputs/scam/approach_minimum/analysis/` 配下に出力する。 出力先は `_common.OUT_DIR` で一元管理。
