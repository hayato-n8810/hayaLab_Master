# Step 3: ライブラリごとの試行環境

`outputs/jsperf/setup/step2/tags.jsonl` で `node_success=false` になった program に対し、npm ライブラリを 1 つずつ試行して Node 実行可否を確認する。

## 構成

- `Dockerfile`: Node 25 + uv 管理 Python の共存イメージ
- `docker-compose.yml`: リポジトリルートを `/workspace` にマウント
- `package.json`: npm 依存を蓄積するワークスペース (試行のたびに `--save` で追記される)
- `trial_library.py`: 単一ライブラリ試行スクリプト
- `node_modules/`: 各試行で `npm install` されるパッケージ（gitignore 対象を想定）

## 起動

```bash
# ビルド + 起動
cd experiments/jsperf/setup/step3
docker compose up -d --build

# コンテナへ接続
docker compose exec bench bash

# コンテナ内で uv 同期 (初回のみ)
cd /workspace
uv sync
```

## ライブラリを 1 つ試行する

コンテナ内で以下を実行:

```bash
uv run python experiments/jsperf/setup/step3/trial_library.py \
    --library lodash \
    --version ^4.17.21 \
    --binding _ \
    --url-pattern lodash
```

引数:

| 引数 | 内容 |
|---|---|
| `--library` | npm パッケージ名（例: `lodash`） |
| `--version` | npm バージョン指定（例: `^4.17.21`） |
| `--binding` | 挿入する require のバインド名（例: `_`） |
| `--url-pattern` | `meta.json.cdn_urls` に対する部分一致（case-insensitive）で試行対象を絞り込む |
| `--max-workers` | 並列数（デフォルト 35） |
| `--skip-npm-install` | 既に install 済みのとき利用 |

## 挙動

1. `npm install --save {library}@{version}` を `experiments/jsperf/setup/step3/` で実行
2. `outputs/jsperf/setup/step2/tags.jsonl` を読み込み、`node_success=false` の program を列挙
3. 各 program の `outputs/jsperf/setup/step1/<slug_id>/meta.json` を参照し、`cdn_urls` のいずれかが `--url-pattern` を含む場合を試行対象とする
4. 元 program の先頭に `const {binding} = require({library});` を挿入した新ファイルを
   `outputs/jsperf/setup/step3/trials/{library}/{slug_id}/program_{i}.js` に生成
5. `NODE_PATH=/workspace/experiments/jsperf/setup/step3/node_modules` の下で並列に node 実行
6. 結果を `outputs/jsperf/setup/step3/trials/{library}/results.jsonl` に、集計を `summary.json` に書き出す

## 出力

`outputs/jsperf/setup/step3/trials/<library>/`
- `results.jsonl`: 各 program の実行結果（`status`, `exit_code`, `error_type`, `stderr_head`, `elapsed`）
- `summary.json`: 集計（試行対象数、成功数、error_type 内訳、ベンチマーク単位の全成功/一部成功/全失敗数）
- `<slug_id>/program_<i>.js`: require 挿入済みの試行用 JS

## 試行ワークフロー例

```bash
# 1. lodash 試行
uv run python experiments/jsperf/setup/step3/trial_library.py --library lodash --version ^4.17.21 --binding _ --url-pattern lodash

# 2. underscore 試行
uv run python experiments/jsperf/setup/step3/trial_library.py --library underscore --version ^1.13.7 --binding _ --url-pattern underscore

# 3. moment 試行
uv run python experiments/jsperf/setup/step3/trial_library.py --library moment --version ^2.30.1 --binding moment --url-pattern moment
```

各試行の `summary.json` を見て、Node 成功に至った program 数と依然失敗数を比較する。 これを繰り返して `cdn_list_resolve.json` の候補を積み上げていく。

## 全 trial 完了後の集約

全ライブラリの trial を一通り走らせたら、結果を横断的に集約する:

```bash
uv run python experiments/jsperf/setup/step3/aggregate_trials.py
```

出力先: `outputs/jsperf/setup/step3/aggregate/`

- `program_success.jsonl`: program (`slug_id` + `test_idx`) 単位に、どのライブラリ trial で試行され、どのライブラリで成功したかを 1 行 1 レコードで記録
  - `trials_attempted`: 試行されたライブラリ集合（URL パターン一致で対象になったもの）
  - `trials_succeeded`: 成功したライブラリ集合（複数ありうる）
  - `resolved_in_step3`: step3 で 1 つ以上のライブラリで成功したか
- `library_effectiveness.json`: ライブラリ単位の集計
  - `programs_attempted` / `programs_succeeded` / `success_rate`
  - `programs_unique_win`: そのライブラリでしか成功しなかった program 数
  - `benchmarks_all_success` / `_partial_success` / `_all_failed`
- `benchmark_coverage.jsonl`: benchmark 単位の解決状況
  - `step2_success_count` / `step3_resolved_count` / `still_failing_count`
  - `all_resolved`: 全 program が step2 or step3 で成功したか（true なら Node 計測 tier 確定）
- `summary.json`: 全体サマリ (成功総数、library_hits_histogram など)

`program_success.jsonl` を見れば、任意の failed program がどのライブラリインポートで復活したかが完全に追跡できる。

## 注意

- `--url-pattern` は文字列部分一致。 `lodash` と `lodash.js` の両方にヒットさせたい場合は共通の `lodash` を渡す。
- 再実行時に `--skip-npm-install` を指定すると `npm install` をスキップして試行のみ再実行できる。
- `node_modules/` は永続化されるので、前の試行で入れたライブラリはそのまま残る。 完全に isolate したい場合は `rm -rf node_modules package-lock.json` して再度 install する。
