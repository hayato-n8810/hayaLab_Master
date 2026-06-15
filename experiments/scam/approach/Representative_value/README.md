# Representative_value — クラスの代表 value 抽出

`integrate.py` が生成したクラスタ（n-gram + Jaccard complete-linkage 併合）に対して、
「このクラスのパターンはこれ」と人間に説明するための**代表 value**を抽出するスクリプト群。

論文採用は `mode_medoid.py`（過半数 mode → bigram-Jaccard medoid の二段構え）のみ。
共通処理（bigram トークン化、Jaccard、IO）は `_common.py` に集約しており、
bigram の定義は `integrate.py` と完全に同一（クラスタ生成と整合）。

## 入力

| パス | 役割 |
|---|---|
| `outputs/scam/approach/integrate/{tau_dir}/level{L}/{depth}.json` | クラスタ結果 (`classes: {class_id: [cutout_id, ...]}`) |
| `outputs/scam/approach/integrate/{tau_dir}/level{L}/{depth}_label.json` | 各メンバーの value 文字列 (`{class_id: [{id, value}, ...]}`) |
| `outputs/scam/approach/abstract/abstract_level{L}.json` | bigram 計算用の raw nodes |

`tau_dir` は `jaccard05` / `jaccard07` / `jaccard09` のいずれか。
`{depth}` は `Diff` / `Brother` / `ExParent` / `Parent`。

## 出力

同じ `level{L}/` 配下に代表 value JSON を書き出す:

```
outputs/scam/approach/integrate/{tau_dir}/level{L}/
├── {depth}.json                           # integrate.py 出力（既存）
├── {depth}_label.json                     # show_label.py 出力（既存）
└── {depth}_pattern_mode_medoid.json       # mode_medoid.py の出力
```

## 戦略

### `mode_medoid.py` — mode + medoid 二段構え

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

## CLI オプション

| オプション | 既定 | 説明 |
|---|---|---|
| `--tau-dir` | `jaccard07` | 入出力に使う `jaccard{NN}` ディレクトリ名 |
| `--levels` | `0 1` | 抽象化レベル（複数指定可） |
| `--depths` | 全 4 種 | `Diff Brother ExParent Parent` のサブセット |
| `--workers` | `os.cpu_count()` | クラスごとに並列化するワーカー数。`1` で逐次実行 |


## 並列化

**クラス単位**（`(class_id, rows)` ペア）で `ProcessPoolExecutor.map`
により並列化される。重いデータ（`id_to_bigrams`・閾値）は `initializer` で
ワーカープロセスごとに 1 回だけ展開し、タスクあたりの pickle 量を抑える。

`map(..., chunksize=64)` が入力順を保つため、`--workers` を変えても出力 JSON は
byte-identical（同点解消はすべて明示済み、frozenset → list 変換時には必ず
`sorted()` を挟む）。`PYTHONHASHSEED` の影響も受けない。

`--workers 1` で逐次フォールバック（デバッグ・テスト時）。

## n-gram キャッシュ

`abstract_level{L}.json` は各 2.6 GB ありパースが重いため、bigram テーブルは
`integrate.py` がクラスタリング処理の副産物として pickle で書き出す:

```
outputs/scam/approach/abstract/bigrams_level{L}_n{N}.pkl
```

`mode_medoid.py` は `_common.load_id_to_bigrams_cached(config, level)` 経由でこの cache
を読み、 abstract JSON を再パースしない（[BIGRAMS] cache hit のログを出す）。

cache が `abstract_level{L}.json` より古い場合は自動的に abstract から
計算する fallback 経路に入る（[BIGRAMS] cache miss → fallback (json)）。
fallback は in-memory のみで pickle は書かない — cache の producer は
`integrate.py` に一本化している。

cache pickle の生成・更新は `integrate.py --create-cache` を**明示指定**した
ときだけ起こる:

| 状況 | コマンド |
|---|---|
| 初回・abstract 更新時 | `python3 .../integrate.py --server --create-cache ...` |
| クラスタリング設定だけ変えて再実行（cache はそのまま使う） | `python3 .../integrate.py --server ...`（フラグ無し） |

`--create-cache` 未指定の integrate 実行では cache を読むだけで書き換えない
（高速 + ディスク変更なし）。 cache が無い・古い・破損なら in-memory で
rebuild してクラスタリングは継続するが、 pickle は更新されない。

cache のスキーマバージョン（`integrate.py:NGRAMS_CACHE_VERSION` と
`_common.py:NGRAMS_CACHE_VERSION`）を bump すると古い pickle は無視され、
fallback 経路に倒れる（n-gram ロジックを変更したら版数を上げ、
`--create-cache` 付きで integrate を 1 度走らせる）。

## 実行例

個別実行:
```bash
uv run python experiments/scam/approach/Representative_value/mode_medoid.py \
    --tau-dir jaccard07 --levels 1 --depths Diff
```

全 tau × 全 level × 全 depth を一括実行（パイプライン全体は `approach/run.sh`）:
```bash
bash experiments/scam/approach/run.sh
```

`run.sh` の主な環境変数:

| 環境変数 | 既定 | 説明 |
|---|---|---|
| `TAU_DIRS` | `jaccard07 jaccard09` | 処理する tau ディレクトリ群 |
| `LEVELS` | `1 2` | 抽象化レベル |
| `DEPTHS` | `Diff Brother ExParent Parent` | depth 群 |
| `WORKERS` | （未指定→`os.cpu_count()`）| `mode_medoid.py --workers` を一括指定 |

例: 8 並列で jaccard07 level1 Diff のみ:
```bash
WORKERS=8 TAU_DIRS="jaccard07" LEVELS="1" DEPTHS="Diff" \
  bash experiments/scam/approach/Representative_value/run.sh
```

## 依存

`integrate.py` と `show_label.py` の出力が事前に存在することが前提。
未生成の `(tau_dir, level, depth)` は `[SKIP]` で読み飛ばす。
