# Slow Pattern Clustering — experiments/scam/approach_temp

独立サンドボックス実験パイプライン。`src/hayalab/` への依存なし。

## 概要

入力 `outputs/scam/approach/01_cutouts.json` の各 cutout に対して A0〜A5 の 6 段階抽象化を施し、
M0〜M3 の 4 手法で独立に集約（計 24 通り）。抽象度を上げるにつれ各 cutout がどのクラスに帰属するかを
「集約軌跡」として記録し、Sankey 図で可視化する。

## ファイル構成

```
experiments/scam/approach_temp/
├── README.md
├── ast_node.py             # Cutout / NodePayload / TemplateNode / Pattern / TreeNode
├── loader.py               # 01_cutouts.json 読み込み + フィルタリング
├── abstract.py             # A0..A5 抽象化規則
├── cluster.py              # UnionFind + クラス構築ユーティリティ
├── observe.py              # 集約実行 + 軌跡生成 + 単調性チェック
├── evaluate.py             # Purity / NMI / ARI
├── export.py               # classes_{level}_{method}.json 出力
├── visualize_sankey.py     # trajectory → sankey_{method}.html
├── run.py                  # メインランナー
└── methods/
    ├── __init__.py
    ├── m0_hash.py          # M0: ハッシュ完全一致
    ├── m1_inclusion.py     # M1: 単方向 tree inclusion
    ├── m2_bi_inclusion.py  # M2: 双方向 tree inclusion (hit set)
    └── m3_antiunify.py     # M3: anti-unification (LGG)
```

出力先: `outputs/scam/approach_temp/`

## 実行方法

```bash
# 依存ライブラリの追加（初回のみ）
uv add plotly

# サンプル実行（M0 のみ、50 件）
uv run python experiments/scam/approach_temp/run.py --sample 50 --methods M0 --levels 0

# 全手法・全レベル実行
uv run python experiments/scam/approach_temp/run.py

# 詳細オプション
uv run python experiments/scam/approach_temp/run.py \
    --input outputs/scam/approach/01_cutouts.json \
    --output outputs/scam/approach_temp \
    --levels 0 1 2 3 4 5 \
    --methods M0 M1 M2 M3 \
    --sample 200
```

## 抽象化レベル

| レベル | 概要 |
|--------|------|
| A0 | 変更なし（完全具象） |
| A1 | VAR_* → スロット ID |
| A2 | VAR_* + LITERAL_* → スロット ID |
| A3 | + 関数系 7 種を `function_like` に統一 |
| A4 | + 非組み込み識別子を抽象化（組み込みは保持） |
| A5 | 全識別子値を抽象化（最高抽象度） |

## 集約手法

| 手法 | 概要 |
|------|------|
| M0 | SHA-256 完全一致ハッシュ |
| M1 | 単方向 tree inclusion（P ⊑ T or T ⊑ P） |
| M2 | 双方向 hit-set 等価（hit_set(P1) == hit_set(P2)） |
| M3 | Anti-unification (LGG) 貪欲併合 |
