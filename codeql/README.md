# codeQL

JavaScript マイクロベンチマーク由来の性能パターンに対応する CodeQL クエリを実行し，
検出結果（SARIF）とコードスニペット付き JSON を生成するためのツール群

---

## できること（概要）

- **GitHubリポジトリのCodeQL DB 作成**: 複数リポジトリを一括で DB 化
- **GitHubリポジトリへのクエリ実行**: `id_1.ql` から `id_6.ql` を全 DB に実行して SARIF を出力
- **マイクロベンチマークへのクエリ実行**: 1 つの DB に 6 クエリを実行して SARIF を出力
- **SARIF(CodeQLの出力形式)からJSONへの変換**: SARIF から該当コードスニペットを抽出したうえで，JSON 形式に整形

---

## ディレクトリ構成

```text
codeQL/
├── QL/
│   ├── pattern2query.jsonc    # パターンID（pattern参照）とクエリIDの対応表
│   └── query/                 # CodeQLクエリ本体（id_1.ql ... id_6.ql）
├── scripts/
│   ├── create_repoDB.py       # GitHubリポジトリ群のDB一括作成
│   ├── analyze_repo.py        # GitHubリポジトリ群のDBに対する一括解析
│   ├── analyze_MB.py          # microbenchmark DBに対する解析
│   └── sarif2json.py          # SARIF -> コード付きJSON変換
├── targets/
│   ├── github/
│   │   ├── repositories/      # 解析対象リポジトリ
│   │   └── codeql-dbs/        # 作成したCodeQL DB
│   └── microbenchmark/
│       ├── separate_slow/     # microbenchmark の slow 側コード群
│       └── codeql-db/         # microbenchmark のCodeQL DB
└── outputs/
    ├── github/
    │   ├── sarif/
    │   └── code/
    └── microbenchmark/
            ├── sarif/
            └── code/
```

---

## 依存関係

### ローカル実行で必要

- CodeQL CLI（`codeql` コマンド）
- Python 3.13+（`scripts/sarif2json.py` 実行に必要）
- Node.js / pnpm

### Docker 実行（推奨）

`codeQL/Dockerfile` には以下が含まれます。

- Python
- CodeQL CLI
- Node.js / pnpm
- `hayalab` のインストール環境

---

## 再現手順（Docker想定）

```bash
docker compose up -d
docker container exec -it bachelor_codeql bash
```

コンテナ内で以下を実行し，codeqlのクエリ実行を有効化:

```bash
cd /works/QL/query
codeql pack install
```

### データの準備

- **マイクロベンチマークについて**
  - `targets/microbenchmark/separate_slow` 配下に `pattern/data/MB_separate.json` のseparate-slowに当たるコード片をファイル化したものを配置（卒論を再現する場合はzip（反復処理を含むslowコード11,890件）を解凍）
  - CodeQL DBの作成は以下のコマンドを実行
    ```bash
    # 例（卒論再現）
    codeql database create /works/targets/microbenchmark/codeql-db \
        -s=/works/targets/microbenchmark/separate_slow \
        --no-run-unnecessary-builds \
        --language=javascript-typescript
    ```

- **GitHubリポジトリについて**
  - `targets/github/repositories` 配下にGitHubリポジトリをクローン
  - 対象リポジトリを全てクローン後，以下を実行すると `targets/github/codeql-dbs/{project_name}/` に一括でDBが作成される
    ```bash
    cd /works/scripts
    python3 create_repoDB.py
    ```

    参考）卒論を再現する場合は `targets/github/mb_scanner.db` に対象のリポジトリについての情報が記載されています．
    また，クローンデータはbrain-2サーバの以下のパスにあります(2025-03-18時点):
    - `/mnt/data1/tomoya-n/MB-Scanner/data/repositories`


### 解析フロー

### 1) GitHub リポジトリ群にクエリ実行

```bash
# 全プロジェクトに6つのクエリを実行
cd /works/scripts
python3 analyze_repo.py

# オプションで並列化可能
python3 analyze_repo.py -j {並列数}
```

- 入力: `/works/targets/github/codeql-dbs/{project}/`
- 出力: `/works/outputs/github/sarif/id_{1..6}/{project}.sarif`

### 2) microbenchmark DB にクエリ実行

```bash
python3 analyze_MB.py

# オプションでDBのパスを指定可能
# デフォルト DB パス: `/works/targets/microbenchmark/codeql-db`
python3 analyze_MB.py -j {DB_path}
```

- 入力: `/works/targets/microbenchmark/codeql-db`
- 出力: `/works/outputs/microbenchmark/sarif/id_{1..6}.sarif`

### 3) SARIF からコードスニペット抽出（JSON化）

#### デフォルト（GitHubリポジトリ群を一括処理）

```bash
python3 sarif2json.py
```

- 入力: `/works/outputs/github/sarif/**/*.sarif`
- 参照コード: `/works/targets/github/repositories/{project}/`
- 出力: `/works/outputs/github/code/id_{1..6}/{project}_code.json`

#### マイクロベンチマーク・単一 SARIF を処理する場合

```bash
python3 sarif2json.py \
	-f {sarif_file_path} \
	-t {target_project_root_path} \
	-o {output_path}.json

# 例：マイクロベンチマークの検出結果の変換
python3 sarif2json.py \
	-f /works/outputs/microbenchmark/sarif/id_3.sarif \
	-t /works/targets/microbenchmark/separate_slow \
	-o /works/outputs/microbenchmark/code/id_3_code.json
```

---

## クエリ一覧（`QL/query/id_*.ql`）

- `id_1.ql`: `for-in` 文
- `id_2.ql`: `forEach` 呼び出し
- `id_3.ql`: `for-in` + `if (...hasOwnProperty(...))`
- `id_4.ql`: `apply(...).map(...)` パターン
- `id_5.ql`: `JSON.parse(JSON.stringify(...))`
- `id_6.ql`: `for-of` 内での `push` 呼び出し

`QL/pattern2query.jsonc` に，パターン抽出側の `feature_id` とクエリ ID の対応メモがあります。

---

## 出力データ形式

### 出力: `outputs/*/sarif/*.sarif`

- CodeQL の標準 SARIF 形式
- 1 ファイルが 1 クエリ × 1 対象（DB またはプロジェクト）に対応

### 出力: `outputs/*/code/*_code.json`

- `metadata`
	- `sarif_path`
	- `repository_path`
	- `total_results`
	- `extraction_date`
- `results`（検出結果配列）
	- `id`
	- `file_path`
	- `start_line`, `end_line`
	- `start_column`, `end_column`
	- `message`, `severity`
	- `code_snippet`

---