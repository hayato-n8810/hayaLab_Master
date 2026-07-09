# Step 3: CDN → npm 一括解決 + require 挿入 + Node 実行

## 目的

`outputs/jsperf/setup/step2/tags.jsonl` で `node_success=false` となった program に対し、
`experiments/jsperf/setup/step3/cdn_list_resolve.json` を単一情報源として:

1. 対応する npm パッケージを列挙して `package.json` を自動生成
2. `npm install` で `experiments/jsperf/setup/step3/node_modules/` に一括インストール
3. 各 program の `meta.json.cdn_urls` から必要ライブラリを解決し、`require` を先頭に挿入
4. Node で並列実行
5. 結果を step1/step2 と同型の per-benchmark 出力 + JSONL/summary で保存

## 構成

- `Dockerfile`: Node 24 + uv Python の共存イメージ
- `docker-compose.yml`: リポジトリルートを `/workspace` にマウント
- `step3_inject.py`: 統合スクリプト (npm install + 挿入 + 実行 + 集計)
- `package.json`: `step3_inject.py` が自動生成する npm ワークスペース
- `node_modules/`: `npm install` で生成 (gitignore 対象)

## 入力

- `experiments/jsperf/setup/cdn_list_resolve.json`: URL → npm パッケージ対応表 (単一情報源)
  ```json
  {
    "version": 1,
    "libraries": [
      {"package": "lodash", "version": "^4.17.21", "binding": "_", "patterns": ["lodash"]},
      {"package": "jquery", "version": "^3.7.1", "binding": "$",
       "patterns": ["/ajax/libs/jquery/", "code.jquery.com/jquery-", "/npm/jquery@"]},
      ...
    ]
  }
  ```
- `outputs/jsperf/setup/step1/<slug_id>/meta.json` (`cdn_urls` フィールドを参照)
- `outputs/jsperf/setup/step1/<slug_id>/program_<i>.js`
- `outputs/jsperf/setup/step2/tags.jsonl`

## 起動

```bash
# ビルド + 起動
cd experiments/jsperf/setup/
docker compose up -d --build

# コンテナへ接続
docker compose exec bench bash

# コンテナ内 /workspace で uv 同期 (初回のみ)
cd /workspace
uv sync
```

## 実行

```bash
uv run python experiments/jsperf/setup/step3/step3_inject.py
```

| 引数 | 内容 |
|---|---|
| `--max-workers` | 並列数 (デフォルト 25) |
| `--skip-npm-install` | `package.json` 再生成と `npm install` をスキップ (既に install 済みのとき) |

## 挙動

1. `cdn_list_resolve.json` を読み込む
2. `--skip-npm-install` でない限り:
   - `experiments/jsperf/setup/step3/package.json` を resolve 情報から自動生成
   - `npm install` を実行
3. `step2/tags.jsonl` で `node_success=false` の program を列挙
4. 各 program について:
   - `step1/<slug_id>/meta.json.cdn_urls` を参照
   - resolve の `patterns` (case-insensitive 部分一致) で必要ライブラリ集合を決定
   - 該当ライブラリ 0 個ならスキップ
   - 該当ライブラリ全てを `const {binding} = require('{package}');` の形で先頭に注入
   - 挿入済みファイルを `outputs/jsperf/setup/step3/benchmark/<slug_id>/program_<i>.js` に生成
5. `NODE_PATH=/workspace/experiments/jsperf/setup/step3/node_modules` の下で並列実行
6. 結果集計を `results.jsonl`, `tags.jsonl`, `summary.json` に書き出し

## 出力

`outputs/jsperf/setup/step3/`

| ファイル | 内容 |
|---|---|
| `benchmark/<slug_id>/program_<i>.js` | require 挿入済み JS (step3 で実行された program のみ) |
| `results.jsonl` | step3 実行結果 (per program): `status`, `exit_code`, `error_type`, `stderr_head`, `elapsed`, `libraries`, `n_libraries` |
| `tags.jsonl` | 全 program のタグ: `node_success` (step2 の結果そのまま) と `npm_success` (step3 の npm 注入後に成功したか)。 Node 実行可能 = `node_success ∨ npm_success` |
| `summary.json` | 集計 (status 内訳、error_type 内訳、benchmark 単位、ライブラリ数別成功率、ライブラリ別 involvement) |

`package.json` は `experiments/jsperf/setup/step3/package.json` (単一) のみ

## バインド衝突の解決

resolver の並び順が優先順位。 同一 binding が複数ライブラリで衝突する場合 (例: `_` = lodash vs underscore、`$` = jquery vs zepto) は resolver で**先に列挙されたもの**を採用し、後続を捨てる。

`cdn_list_resolve.json` の先頭に置いたライブラリが優先されるので、優先度の高いライブラリを上に書く。
