# Representative_value — クラスの代表 value 抽出

`integrate.py` が生成したクラスタ（n-gram + Jaccard 貪欲併合）に対して、
「このクラスのパターンはこれ」と人間に説明するための**代表 value**を
4 通りの戦略で抽出する一連のスクリプト群。

戦略はそれぞれ独立したファイルに分けてあり、CLI から個別に呼び出せる。
共通処理（bigram トークン化、Jaccard、IO）は `_common.py` に集約しており、
bigram の定義は `integrate.py` と完全に同一（クラスタ生成と整合）。

## 入力

| パス | 役割 |
|---|---|
| `outputs/scam/approach_minimum/integrate/{tau_dir}/level{L}/{depth}.json` | クラスタ結果 (`classes: {class_id: [cutout_id, ...]}`) |
| `outputs/scam/approach_minimum/integrate/{tau_dir}/level{L}/{depth}_label.json` | 各メンバーの value 文字列 (`{class_id: [{id, value}, ...]}`) |
| `outputs/scam/approach_minimum/abstract/abstract_level{L}.json` | bigram 計算用の raw nodes |

`tau_dir` は `jaccard05` / `jaccard07` / `jaccard09` のいずれか。
`{depth}` は `Diff` / `Brother` / `ExParent` / `Parent`。

## 出力

各戦略は同じ `level{L}/` 配下に戦略別 JSON を書き出す:

```
outputs/scam/approach_minimum/integrate/{tau_dir}/level{L}/
├── {depth}.json                           # integrate.py 出力（既存）
├── {depth}_label.json                     # show_label.py 出力（既存）
├── {depth}_pattern_mode_medoid.json       # 戦略 1
├── {depth}_pattern_common_bigrams.json    # 戦略 2
├── {depth}_pattern_skeleton.json          # 戦略 3
└── {depth}_pattern_medoid_outlier.json    # 戦略 4
```

## 戦略一覧

### `mode_medoid.py` — mode + medoid 二段構え（推奨）

1. クラスメンバーの label value 文字列を集計し、**過半数 (support > size/2)** を占める value があればそれを mode として採用。
2. 過半数 mode が無ければ **bigram-Jaccard medoid**（他メンバーへの Jaccard 平均最大のメンバー、同点は id 昇順）を採用。
3. メンバー 1 件は `single`。

出力スキーマ:
```json
{
  "L0_M2_xxx": {
    "size": 3,
    "strategy": "mode" | "medoid" | "single",
    "representative": {"id": 9683, "value": "..."},
    "support": 3
  }
}
```

### `common_bigrams.py` — クラス内 bigram の intersection

クラスの全メンバーが共有する bigram 集合 `∩_i bigrams(member_i)` を抽出する。
クラスタ生成に使った n-gram + Jaccard の**根拠そのもの**を残す方針。
参考として medoid メンバーの id も併記する。

出力スキーマ:
```json
{
  "L0_M2_xxx": {
    "size": 3,
    "common_count": 7,
    "common_bigrams": [[["name","val"],["name","val"]], ...],
    "medoid_id": 9683
  }
}
```

注意: 推移併合の影響が大きい巨大クラスタでは intersection が極端に小さくなる
（外れメンバーが 1 つでも該当 bigram を持たないと落ちる）。

### `skeleton.py` — ≥k% トークン残存スケルトン

label value の空白区切りトークン列を簡易整列し、各位置で `k_threshold` 以上の
メンバーが同じトークンを持つ位置だけ残し、可変位置を `*` で表現する。

基準列は「token 数が中央値に最も近いメンバー」（タイは id 昇順）。
連続する `*` は 1 つに圧縮。

出力スキーマ:
```json
{
  "meta": {..., "k_threshold": 0.66},
  "classes": {
    "L0_M2_xxx": {
      "size": 3,
      "base_id": 3119,
      "skeleton": "filter function $v0 * indexOf $v0 ===",
      "support_per_token": [3, 3, 3, 2, 3, 3, 3]
    }
  }
}
```

注意: 位置ベースの近似 MSA なので、長さや並びが大きく揺らぐクラスタでは
スケルトンが `*` 中心に潰れる。

### `medoid_outlier.py` — medoid 代表 + 外れ値分離

medoid を代表に採用しつつ、medoid からの Jaccard が `--outlier-tau` 未満の
メンバーを「外れメンバー」として別ラベルに切り出す。推移併合で混入した
周縁メンバーの可視化に有効。

出力スキーマ:
```json
{
  "meta": {..., "outlier_tau": 0.5},
  "classes": {
    "L0_M2_xxx": {
      "size": 8,
      "representative": {"id": 222, "value": "...", "avg_jaccard": 0.56},
      "core_ids": [222, 232, 239, ...],
      "outliers": [
        {"id": 22211, "value": "...", "jaccard_to_medoid": 0.21}
      ]
    }
  }
}
```

## CLI 共通オプション

| オプション | 既定 | 説明 |
|---|---|---|
| `--tau-dir` | `jaccard07` | 入出力に使う `jaccard{NN}` ディレクトリ名 |
| `--levels` | `0 1 2 3` | 抽象化レベル（複数指定可） |
| `--depths` | 全 4 種 | `Diff Brother ExParent Parent` のサブセット |
| `--workers` | `os.cpu_count()` | クラスごとに並列化するワーカー数。`1` で逐次実行 |

戦略固有:
- `skeleton.py --k 0.66` — トークン採用閾値
- `medoid_outlier.py --outlier-tau 0.5` — 外れメンバー判定の Jaccard 閾値

## 並列化

各戦略は **クラス単位**（`(class_id, rows)` ペア）で `ProcessPoolExecutor.map`
により並列化される。重いデータ（`id_to_bigrams`・閾値）は `initializer` で
ワーカープロセスごとに 1 回だけ展開し、タスクあたりの pickle 量を抑える。

`map(..., chunksize=64)` が入力順を保つため、`--workers` を変えても出力 JSON は
byte-identical（同点解消はすべて明示済み、frozenset → list 変換時には必ず
`sorted()` を挟む）。`PYTHONHASHSEED` の影響も受けない。

`--workers 1` で逐次フォールバック（デバッグ・テスト時）。

## 実行例

個別実行:
```bash
uv run python experiments/scam/approach_minimum/Representative_value/mode_medoid.py \
    --tau-dir jaccard07 --levels 0 --depths Diff
```

全戦略 × 全 tau × 全 level × 全 depth を一括実行:
```bash
bash experiments/scam/approach_minimum/Representative_value/run.sh
```

`run.sh` の主な環境変数:

| 環境変数 | 既定 | 説明 |
|---|---|---|
| `TAU_DIRS` | `jaccard05 jaccard07 jaccard09` | 処理する tau ディレクトリ群 |
| `LEVELS` | `0 1 2 3` | 抽象化レベル |
| `DEPTHS` | `Diff Brother ExParent Parent` | depth 群 |
| `SKELETON_K` | `0.66` | `skeleton.py --k` |
| `OUTLIER_TAU` | `0.5` | `medoid_outlier.py --outlier-tau` |
| `WORKERS` | （未指定→`os.cpu_count()`）| 全戦略の `--workers` を一括指定 |

例: 8 並列で jaccard07 level0 Diff のみ:
```bash
WORKERS=8 TAU_DIRS="jaccard07" LEVELS="0" DEPTHS="Diff" \
  bash experiments/scam/approach_minimum/Representative_value/run.sh
```

## 依存

`integrate.py` と `show_label.py` の出力が事前に存在することが前提。
未生成の `(tau_dir, level, depth)` は `[SKIP]` で読み飛ばす。
