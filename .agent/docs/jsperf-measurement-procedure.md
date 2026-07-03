# JsPerf マイクロベンチマーク 実行時間計測 セットアップ手順

本ドキュメントは、収集済み JsPerf ベンチマークから **実行時間計測用プログラムを整形する**までの手順を規定する。 計測実行と統計判定（Step 6 以降で整形したハーネスを実際に走らせるフェーズ）は別ドキュメントで扱う。

## 目的

`data/processed/benchmarks_latest_revision.json` を入力として、収集済み JsPerf ベンチマークを実行環境ごとに振り分け、各テストを計測可能な形（ウォームアップと計測ループを含むハーネス付きプログラム）に整形する。

## 前提

- 入力: `data/processed/benchmarks_latest_revision.json`（23,055 ベンチマーク、`preparation_html` / `setup` / `teardown` / `tests[*]` を含む）
- 実行環境: **Node** または **Playwright（headless Chromium）** のいずれか
- 1 ベンチマーク = 1 環境で実行する
- Docker のベース Node バージョンは両環境で揃える（別途設定）

## 全体方針: 件数トラッキング

各ステップの入力・出力件数と、除外/振り分け件数をすべて JSONL / summary JSON に記録する。 パイプライン実行後に「どこで何件落ちたか」が完全に追跡できるようにする。

出力先: `outputs/jsperf/setup/stepN/`
- `summary.json`: そのステップの件数集計
- `results.jsonl`: 個別ベンチマーク or JS の処理結果（1 行 1 レコード）
- `excluded.jsonl`: 除外されたベンチマーク/JS と理由

---

## Step 1. inline `<script>` + setup + test + teardown を統合 → 実行 JS 作成

実装ファイル：`experiments/jsperf/setup/step1_integrate.py`

`benchmarks_latest_revision.json` を読み込み、各ベンチマークを以下のフィールドに分解する。

- `slug` / `revision` / `title` / `url`
- `preparation_html`: 生 HTML 文字列
- `setup`: JS 文字列
- `teardown`: JS 文字列
- `tests[]`: `{title, code}` のリスト

各ベンチマークについて、`preparation_html` からインライン `<script>` の中身を抽出し、`setup` の前に連結する。 その後、各 test に対して 1 つの実行 JS ファイルを生成する。
また、このとき、該当ベンチマークの `preparation_html` から外部 `<script src>` URL を抽出し、リストアップする。
CDN URL パターン（`cdnjs.cloudflare.com`, `ajax.googleapis.com`, `unpkg.com`, `code.jquery.com`, etc.）を列挙する。 このとき、文字列としてユニークなものを列挙すること。

### 変換ルール

各 test `test_i`（i は `tests[]` 配列のインデックス）について、以下の順序で 1 ファイルに統合する:

```
1. preparation_html 内のインライン <script>...</script> の中身
2. setup フィールドの中身
3. test_i.code
4. teardown フィールドの中身
```

このファイルを `program_<i>.js` として保存する。

外部 `<script src>` と DOM 要素は `preparation_html` から**削除せず**、別途 `page_html.html` として保持する。

### 生成される「残る HTML」

`preparation_html` からインライン `<script>` を除去したもの:
- 外部 `<script src>`
- DOM 要素（`<div>`, `<span>` 等）

これらは Step 4（Playwright 実行）で使用する。

### 各ベンチマークの `meta.json`

per-benchmark 情報を格納する:
- `slug`, `slug_id`, `revision`, `title`, `url`
- `test_count`: `tests[]` の長さ
- `cdn_urls`: このベンチマークが参照する外部 `<script src>` URL のリスト（ユニーク）
- `has_dom_elements`: `page_html.html` に DOM 要素が残っているか
- `has_inline_scripts`: 元の `preparation_html` に inline `<script>` が含まれていたか

### 報告する件数

- 入力ベンチマーク総数（＝ 23,055）
- 各カテゴリ内訳（`preparation_html` の構造別）
  - HTML なし
  - inline `<script>` のみ
  - `<script>` を除いた際に外部 `<script src>` のみ残る
  - `<script>` を完全に除いた際に HTML 要素が残る
- test 数の度数分布
- CDN の URL リスト

### 出力

`outputs/jsperf/setup/step1/`
- `summary.json`: 上記の件数集計
- `cdn_list.json`: リストアップしたユニークな CDN URL 文字列の集合
- `slug_id/program_<i>.js`: 統合済み実行 JS
- `slug_id/page_html.html`: インライン script を除いた HTML（Playwright 用）
- `slug_id/meta.json`: per-benchmark メタ情報

---

## Step 2. Node 実行（初回）

実装ファイル：`experiments/jsperf/setup/step2_node.py`

Step 1 で生成した各 `program_<i>.js` を Node で実行する。 HTML は参照せず、JS ファイルのみを実行する。

### 実行

- `node program_<i>.js` を並列実行（worker 数 = 35、`outputs/jsperf/node_check` と同じ）
- タイムアウトは設定しない
- エラーが発生した場合、種別に関わらず**もう一度だけ再実行**する（SyntaxError も含めて一律リトライ）
- exit code 0 → **Node 成功タグ**を付与
- 失敗（exit code ≠ 0、OOM）→ タグなし、エラー情報を記録

### 報告する件数

- 実行 JS 総数
- Node 成功数
- 失敗の error_type 内訳（ReferenceError, TypeError, SyntaxError, OutOfMemory 等）
- ベンチマーク単位で「全 JS 成功」の数、「一部成功」の数、「全失敗」の数

### 出力

`outputs/jsperf/setup/step2/`
- `results.jsonl`: 各 JS の実行結果（success/error_type/elapsed）
- `tags.jsonl`: 各 JS の付与タグ状態
- `summary.json`: 集計

---

## Step 2.5.（外部作業）CDN → npm 対応表の作成

Step 1 で生成した `cdn_list.json`（グローバル URL 集合）をもとに、**ユーザが手動で** URL → npm パッケージ名 の対応表を作成する:

- ファイル名: `outputs/jsperf/setup/step3/cdn_list_resolve.json`
- 構造: グローバル URL 集合と、それぞれの npm パッケージ名の対応
- マッピング不能な URL は対応表に含めない（後段 Step 4 の Playwright で処理）

このファイルは Step 3.1 の入力となる。

---

## Step 3.1. npm インポートの挿入

実装ファイル：`experiments/jsperf/setup/step3_npm.py`

**ベンチマーク単位で「全 JS に Node 成功タグが付いていない」ベンチマーク**を対象とする。

### 入力

- `cdn_list_resolve.json`: URL → npm パッケージ名 の対応表（Step 2.5 でユーザが作成）
- 各対象ベンチマークの `meta.json` に含まれる `cdn_urls`

### インポート挿入

各対象ベンチマークに対して:
1. `meta.json.cdn_urls` から `cdn_list_resolve.json` を参照して、解決できた npm パッケージのリストを得る
2. 該当ベンチマークの **全** `program_<i>.js`（Step 2 で成功していたものも含めて一律） の**先頭**に、`require` / `import` 文を挿入する

```js
const _ = require('lodash');
const $ = require('jquery');
// ... 元の統合済みコード
```

### 報告する件数

- 対象ベンチマーク数（Node 全成功でないもの）
- npm マッピング成功数（対応表に載っている URL 数）
- npm マッピング不能数（対応表に載っていない URL 数）
- インポート挿入を適用した JS 数

### 出力

`outputs/jsperf/setup/step3/`
- `slug_id/program_<i>.js`: インポート挿入済み JS（Step 1 の JS を上書きせず、この step 用に別途生成）
- `slug_id/package.json`: 該当ベンチマークで使う npm パッケージ
- `summary_npm.json`: 集計

---

## Step 3.2. Node 再実行

実装ファイル：`experiments/jsperf/setup/step3_node.py`

Step 3.1 でインポートを挿入した JS を Node で再実行する。 対象は Step 3.1 の対象ベンチマーク（全 JS Node 成功でないもの）に含まれる全 JS。

### Docker 環境

- `experiments/jsperf/setup/Dockerfile_step3` および `experiments/jsperf/setup/docker-compose_step3.yml` に整備する
- **`cdn_list_resolve.json` に登場する全 npm パッケージ**を単一 Docker にまとめて `npm install` した環境を **ユーザが手動で構築**する
- 全ベンチマークをこの単一 Docker 環境で実行する

### 実行

- Step 3.1 でインポートを挿入した JS を Node で実行（Step 2 と同じく worker 35 並列、タイムアウトなし、エラー時 1 回だけリトライ）
- 成功した JS に **Node 成功タグ**を付与（Step 2 で失敗していたが Step 3.2 で成功した JS が対象）

### 報告する件数

- 再実行対象 JS 数
- 追加で Node 成功タグが付いた JS 数
- 依然失敗の error_type 内訳
- ベンチマーク単位で「全 JS 成功に到達」の数、「なお一部/全失敗」の数

### 出力

`outputs/jsperf/setup/step3/`
- `results_node.jsonl`: 再実行結果
- `tags.jsonl`: タグ状態の更新
- `summary.json`: 集計

---

## Step 4. Playwright 実行

実装ファイル：`experiments/jsperf/setup/step4_playwright.py`

**ベンチマーク単位で「全 JS に Node 成功タグが付かなかった」ベンチマーク**を対象とする。 対象ベンチマークの JS は **Step 1 の状態**（npm インポートを挿入する前のもの）を使用する。 対象ベンチマーク内の **全 JS**（Step 2/3.2 で Node 成功しているものも含む）に対して実行する。

### 実行形式

対象ベンチマークの各 test について 1 つの `bench_<i>.html` を生成し、Playwright で個別にロードして実行する。 `bench_<i>.html` の構造:

```html
<!DOCTYPE html>
<html>
<head>
  <!-- page_html.html に含まれる外部 <script src> をここに配置 -->
</head>
<body>
  <!-- page_html.html に含まれる DOM 要素をここに配置 -->
  <script>
    // Step 1 の program_<i>.js の中身を IIFE で包んで inline 埋め込み
    (function() {
      // program_<i>.js の内容
    })();
  </script>
</body>
</html>
```

外部 `<script src>`、DOM 要素、実行 JS を **1 つの HTML に全部まとめる**方針とする。

### Docker 環境と HTTP サーバ

- `experiments/jsperf/setup/Dockerfile_step4` および `experiments/jsperf/setup/docker-compose_step4.yml` に整備する
- Docker 内に **ローカル HTTP サーバ**（Python の `http.server` に COOP/COEP ヘッダ追加）を立てる
- 以下のヘッダを配信する:
  - `Cross-Origin-Opener-Policy: same-origin`
  - `Cross-Origin-Embedder-Policy: require-corp`
- Playwright は `http://localhost:PORT/slug_id/bench_<i>.html` でロード（`file://` は使わない）
- これにより `crossOriginIsolated === true` となり、後段 Step 6 の `performance.now()` 高精度モードが利用可能

### 実行手順

- Playwright（Chromium）を起動
- 各 `bench_<i>.html` を `http://localhost:PORT/slug_id/bench_<i>.html` でロード
- ページ読み込み完了 → JS 実行 → 以下を捕捉し、どれで検出したかを **error_type** として記録:
  - `page.on('pageerror', ...)`: 未捕捉例外 → `error_type = "PageError"`
  - `page.on('console', msg => msg.type() === 'error' && ...)`: console.error 出力 → `error_type = "ConsoleError"`
  - ページロード失敗 → `error_type = "LoadFailed"`
- いずれも発生せず完了 → **Playwright 成功タグ**を付与

### 報告する件数

- Playwright 対象ベンチマーク数
- Playwright 対象 JS 総数
- Playwright 成功 JS 数
- 失敗の error_type 内訳（PageError / ConsoleError / LoadFailed 等）
- ベンチマーク単位で「Playwright で全 JS 成功」の数、「一部成功」の数、「全失敗」の数

### 出力

`outputs/jsperf/setup/step4/`
- `slug_id/bench_<i>.html`: 実行用 HTML（JS を inline 埋め込み）
- `results.jsonl`: 各 JS の実行結果
- `tags.jsonl`: Playwright 成功タグの付与状態
- `summary.json`: 集計

---

## Step 5. ベンチマーク単位の環境振り分け

実装ファイル：`experiments/jsperf/setup/step5_dispatch.py`

残存ベンチマークを、成功タグに基づいて計測環境に振り分ける。

### 振り分けルール

- **全 JS に Node 成功タグが付いている**ベンチマーク → **Node 計測**
  - 使用する JS: Step 3.1 のインポート挿入済み版（Step 3.1 対象外なら Step 1 版）
- **一つでも Playwright 成功タグが付いている JS を含む**ベンチマーク → **Playwright 計測**
  - 使用する JS: **Step 1 の状態**（インポートなし）に戻す
  - 実行形式: 1 test = 1 HTML（Step 4 と同じ形式で、外部 `<script src>` / DOM 要素 / 実行 JS / ハーネスを 1 つの HTML に統合）

### 除外条件

1. Step 2〜4 のいずれの成功タグも付かなかった JS を除外
2. 除外後、成功 JS が **2 個未満**のベンチマークも除外（ペアを作れないため）

### 報告する件数

- 入力ベンチマーク数（Step 4 完了時点で残っているもの）
- 除外 JS 数
- 除外ベンチマーク数（JS < 2）
- Node 計測に振り分けたベンチマーク数
- Playwright 計測に振り分けたベンチマーク数
- 残存ベンチマークの test 数ヒストグラム

### 出力

`outputs/jsperf/setup/step5/`
- `excluded_js.jsonl`: 除外された JS と理由
- `excluded_benchmarks.jsonl`: 除外されたベンチマークと理由
- `node_bench.jsonl`: Node 計測対象ベンチマーク一覧（パス付き）
- `playwright_bench.jsonl`: Playwright 計測対象ベンチマーク一覧（パス付き）
- `summary.json`: 集計

---

## Step 6. 実行時間計測のためのコード整形

実装ファイル：`experiments/jsperf/setup/step6_harness.py`

各 JS を、ウォームアップ・計測ループ・時間取得を含むハーネス付きプログラムに整形する。 K, N, M は後で決定する。

### 整形方針

- 1 反復ユニット = 統合済み `program_<i>.js` の 1 回実行（setup + test + teardown を含む）
- 1 バッチ = N 反復ユニット
- 1 計測ラウンド = 1 バッチの実行 + タイマ計測

パイプライン:
- ウォームアップ: `K_warmup = K` ラウンド実行、計測結果は破棄
- 本計測: `M_measure = M` ラウンド実行、各ラウンドの経過時間を記録

### 環境別の時間取得 API

- **Node**: `process.hrtime.bigint()`（ns 分解能）
- **Playwright**: `performance.now()` × 1e6（ns スケールに換算。 Step 4 と同じ `crossOriginIsolated` 環境で 5μs 精度を確保）

### ハーネスのテンプレート（Node）

```js
const N_BATCH = N;
const K_WARMUP = K;
const M_MEASURE = M;

// ライブラリのインストールがある場合はここに埋め込む

function _iteration_unit() {
  // program_<i>.js のライブラリインストール以外の中身をここに埋め込む
}

// warmup
for (let r = 0; r < K_WARMUP; r++) {
  for (let i = 0; i < N_BATCH; i++) _iteration_unit();
}

// measurement
const samples = [];
for (let r = 0; r < M_MEASURE; r++) {
  const t0 = process.hrtime.bigint();
  for (let i = 0; i < N_BATCH; i++) _iteration_unit();
  const t1 = process.hrtime.bigint();
  samples.push(Number(t1 - t0));
}

console.log(JSON.stringify({slug_id_, test_idx, samples}));
```

### ハーネスのテンプレート（Playwright）

`bench_<i>.measure.html` に上記と同等のスクリプトを埋め込み、`process.hrtime.bigint()` を `performance.now() * 1e6` に置換する。 結果は `window.__result` に格納し、Playwright 側の `page.evaluate(() => window.__result)` で取得する。

### 報告する件数

- 整形完了 JS 数（Node 環境／Playwright 環境それぞれ）

### 出力

`outputs/jsperf/setup/step6/`
- `slug_id/bench_<i>.measure.js`（Node 用）または `slug_id/bench_<i>.measure.html`（Playwright 用）
- `summary.json`: 集計
