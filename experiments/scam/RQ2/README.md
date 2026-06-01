# RQ2 集計スクリプト

論文 `\subsection{RQ2：設計次元の集約への影響}` に載せる図表の元データを生成する。
詳しい議論の組み立ては `docs/graph_jaccard_paper.md` を参照。

## 入力

| パス | 用途 |
|---|---|
| `outputs/scam/approach_temp_v2_jaccard_tau{0.5,0.7,0.9}/classes_A{0..3}_M{1,2}.json` | 集約結果 (τ × α × M で 24 ファイル) |
| `outputs/scam/RQ1/matches.jsonl` | RQ1 既知パターン検出結果 (`postproc_rq1_xref.py` のみ使用) |

cutout_id のスキーマは `{mb_id}_{depth}` (例: `10014_Parent`)。

## 出力

| 出力先 | 中身 |
|---|---|
| `outputs/scam/RQ2/alpha_sigma_grid_tau{tau}.{json,csv}` | α × σ クロス表 (Tab. RQ2-2a/2b) |
| `outputs/scam/RQ2/min_effective_size_tau{tau}.{json,csv}` | mb_id ごとの最小有効サイズ判定 (Fig. RQ2-4) |
| `outputs/scam/RQ2/min_effective_size_summary_tau{tau}.csv` | α × M ごとの分布サマリ (Tab. RQ2-4) |
| `outputs/scam/RQ2/rq1_xref_tau{tau}.{json,csv}` | RQ1 × RQ2 突き合わせ |

## 実行

### 1. α × σ クロス表

各 (τ, α, M, σ) について `n_cutouts / n_singletons / singleton_ratio /
mean_class_size / median_class_size / survival_count / survival_ratio` を集計。

```bash
uv run python experiments/scam/RQ2/postproc_alpha_sigma_grid.py --tau 0.7
uv run python experiments/scam/RQ2/postproc_alpha_sigma_grid.py --all
```

### 2. mb_id ごとの最小有効サイズ

各 mb_id についてサイズの小さい順に所属クラスを引き、最初に再現性のあるクラス
(size>=2) に到達したサイズを `min_effective_size` とラベル。
全 4 サイズが singleton なら `"none"`。

```bash
uv run python experiments/scam/RQ2/postproc_min_effective_size.py --tau 0.7
uv run python experiments/scam/RQ2/postproc_min_effective_size.py --all
```

派生指標：

- `n_redundant`: `min_effective_size` より大きいサイズで同一クラスに属する cutout 数 (mb_id 単位)
- `n_divergent`: 同 別クラスに属する cutout 数 (mb_id 単位)

論文の主張「画一的なサイズ設定では不十分で、mb_id ごとに最適なサイズが異なる」
の経験的裏付けはこのスクリプトで生成する。

### 3. RQ1 × RQ2 突き合わせ

各 target_id (1..10) について `diff_linked=true` の mb_id 集合を取り、それらが
RQ2 集約結果のどのクラスに分散したかを集計。`depth_scope` は `{"any", "Diff",
"Brother", "ExParent", "Parent"}` の 5 通り (cutout を抽出する対象サイズ)。

```bash
uv run python experiments/scam/RQ2/postproc_rq1_xref.py --tau 0.7
uv run python experiments/scam/RQ2/postproc_rq1_xref.py --tau 0.7 \
    --levels 1 --methods M1
```

`--levels` / `--methods` で特定の (α, M) のみに絞ることもできる
(論文で報告する代表設定は α=1, M=M1)。

## モジュール構成

```
experiments/scam/RQ2/
├── __init__.py
├── README.md
├── _common.py                       # 共通ユーティリティ (cutout_id 解析、JSON/CSV I/O)
├── postproc_alpha_sigma_grid.py     # 1
├── postproc_min_effective_size.py   # 2
└── postproc_rq1_xref.py             # 3
```

境界規約 (`.agent/agent-instructions.md`): I/O とパス決定はすべて本ディレクトリで
完結する。ロジック (cutout_id 解析、クラス逆引き、mb_id 単位判定) は本ディレクトリ
内の純関数として実装し、`src/hayalab/` には移していない (RQ2 集計に固有のため)。
