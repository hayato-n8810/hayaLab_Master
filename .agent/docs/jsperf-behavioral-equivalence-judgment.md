# JsPerf マイクロベンチマーク 振る舞い同一性判定 手順

本ドキュメントは、Step 5 で計測環境へ振り分け済みのテストプログラム群について、**各マイクロベンチマーク内の全テストペアの振る舞い同一性（置換可能性）を判定する**手順を規定する。計測（実行時間計測）とは独立に、同一の振り分け・同一のプログラム実体を対象として並行実行できる。

## 目的

各マイクロベンチマーク内で記述されたテストプログラムについて、**そのベンチマークの記述と入力値における**振る舞いの同一性を判定する。判定は「片方のプログラムをもう片方に置き換えても問題ないか（置換可能性）」を観測的に確認するものであり、**あらゆる入力での意味的等価ではない**（単一入力＝そのベンチの setup が与える入力に対する観測的等価）。

各ペアの判定結果は **3 値**（等価 / 非等価 / 判定不能）で出力する。

## 前提・入力

- 入力プログラム: `experiments/jsperf/setup/step5_dispatch.py` の出力
  - Node 計測対象: `data/jsPerf/Node/origin/<slug_id>/program_<i>.js`（`dispatch_rule` が `node` は素版、`npm` は require 注入版）
  - Playwright 計測対象: `data/jsPerf/Playwright/origin/<slug_id>/(program_<i>.js, page_html.html)`
- 振り分けメタ: `outputs/jsperf/setup/step5/{node_bench.jsonl, playwright_bench.jsonl}`（`slug_id` / `env` / `dispatch_rule` / `tests` / `page_html`）
- **実行環境はディレクトリ（`Node` / `Playwright`）で確定**する。tags からの再導出は行わない。
- **teardown を含めた素の program をそのまま実行対象とする**（origin は inline + setup + test + teardown を統合済み）。teardown は全テスト共有のため、ペア相対比較には影響しない。

## 確定済み設計判断（以降の記述と矛盾する場合はこちらを優先）

- **対象・環境**: Step 5 の振り分け（`origin/` と `*_bench.jsonl`）をそのまま採用する。判定対象・環境・ペアは計測と一致する。
- **実行形式**: origin の program を **1 回だけ standalone 実行**する（Node は `node program.js`、Playwright は `page_html.html` を土台にした 1 test = 1 HTML）。計測ハーネス（warmup / 計測ループ / `new Function`）は用いない。
- **非決定性シム**: `Math.random` / `Date` / `Date.now` / `performance.now` 等を**同一シードの PRNG**（列として再現）で固定する。対の両プログラムに同一シードを与える。
- **変数チャネルは 3 ステップ構成**: (V1) 変数名抽出 → (V2) 格納値収集 → (V3) 比較。
- **変数名抽出は gumtree**（`hayalab.gumtree.gum_parse`、`gumtree parse -g js-treesitter-ng`、内部で prettier 整形）を用いる。
- **生存性（終了時に生きているか）は静的解析しない**。抽出した全変数名を実行後に読み取り、**スコープ外で参照できない名前は自然にスキップ**する。
- **直列化**: ラッパ型（Number / String / Boolean / Date）は `valueOf`、それ以外は正準シリアライザで比較する。
- **出力は 3 値**（等価 / 非等価 / 判定不能）。
- **チャネル**: 変数格納値 / 標準出力 / 完了状態 / DOM スナップショット（Playwright のみ）/ 式差分値（F3。`gum_diff` の差分が式に閉じるとき、位置を問わず適用）。
- **決定性セルフチェック**: 各プログラムを同一シードで 2 回実行し、記録が食い違えば当該プログラムを不安定として扱う。

## 全体方針: 件数トラッキング

各ステップの入力・出力・除外件数を JSONL / summary JSON に記録し、「どのペアがどの理由でどの判定になったか」を完全に追跡できるようにする。出力先は計測と同じ `outputs/jsperf/setup/stepN/` 規約に従う（step 番号は実装時に確定）。

- `programs.jsonl`: 1 行 1 プログラムの実行記録（変数格納値・完了状態・セルフチェック結果を含む）
- `pairs.jsonl`: 1 行 1 ペアの判定結果
- `summary.json`: 判定 3 値の件数集計、環境別内訳、判定不能の理由別内訳

---

## 非決定性シム

standalone 実行の前に、対象関数を同一シードの決定的 PRNG 由来へ差し替える。

- 対象: `Math.random`、`Date.now`、`Date`（コンストラクタ / `new Date()`）、`performance.now`。実行環境で利用可能なら `crypto.getRandomValues` / `crypto.randomUUID` も固定。ロケール / タイムゾーンは固定（例: `TZ=UTC`）。
- 対の両プログラムに**同一シード**を与える。乱数列は「そのベンチの入力の一部」とみなす。乱数消費数が異なりストリームがずれる場合は、置換不可の実差として扱う。

---

## 変数チャネルの 3 ステップ構成

### Step V1. 変数名抽出（gumtree）

- 各 program を `hayalab.gumtree.gum_parse` で解析する（`gumtree parse -g js-treesitter-ng`。内部で prettier 整形後に解析）。
- AST（`ASTNode(name, value, parent)` のフラット木）から**変数宣言の識別子を全て収集**する。
  - `variable_declarator` 配下の `identifier` を収集する。
  - 分割代入（`object_pattern` / `array_pattern`）は配下の束縛名を再帰的に収集する。
- **スコープ・生存性は判定しない**（宣言箇所を問わず名前を集める）。同名は重複除去する。
- `gum_parse` が `None`（prettier 失敗・parse 失敗）を返した program は、変数名抽出不能として当該ペアを**判定不能**に寄与させる。

### Step V2. 格納値収集（reader + 実行）

- 抽出した名前集合に対し、末尾リーダを program に追記する。リーダは各名前を **`try/catch` で個別に読み取り**、直列化する。
  - スコープ外で参照できない名前 → ReferenceError を捕捉して**スキップ**（生存性を考慮しない帰結）。
  - 読み取れたが直列化不能（循環・サイズ上限・getter throw 等）→ `<UNREADABLE>`。
- program 全体を `try/catch` で包み、**完了状態** `{completed | threw:型(+正規化メッセージ)}` を記録する。
- 標準出力を捕捉する。Playwright 判定 かつ 差分領域（test 本体）に DOM 変更がある場合のみ、実行後に `document.body` を正準化して記録する。
- 直列化された名前→値の対、完了状態、標準出力、（該当時）DOM を 1 プログラムの記録とする。

### Step V3. 比較

- ペアごとに、**両プログラムに共通する名前**の値を突き合わせる（片側のみの名前は比較しない）。
- 比較は下記チャネル横断の判定ロジックに従う。

### 直列化規則（正準シリアライザ）

型を明示的にタグ付けし、キーを整列し、再帰的に直列化する。

- プリミティブ: `num:<v>`（`-0`→`num:-0`、`NaN`→`num:NaN`）/ `str:<v>` / `bool:<v>` / `null` / `undef` / `bigint:<v>`
- ラッパ型（Number / String / Boolean）: `valueOf` のプリミティブをタグ付け。`Date`: `date:<epoch>`
- `Array` / TypedArray: `arr:[e0,e1,...]`（各要素を再帰）。TypedArray も同一タグへ正規化（数値列一致で同値）
- `Map`: `map:[k:v,...]`（エントリ整列）/ `Set`: `set:[e,...]`（要素整列）
- プレーンオブジェクト: own enumerable 文字列キーを整列し `obj:{k:v,...}`（Symbol キーは除外、getter は呼ばない）
- `RegExp`: `re:<source>/<flags>` / 関数: `fn` / 循環: WeakSet で検出し `<cycle>`
- 直列化不能・サイズ上限超過・読取不能: `<UNREADABLE>`

---

## その他のチャネル

| チャネル | 取得 | 比較 |
|---|---|---|
| 完了状態 | 全体を `try/catch` で包み `{completed \| threw:型(+正規化メッセージ)}` | 文字列一致 |
| 標準出力 | 実行中の stdout を捕捉（存在時のみ） | 文字列一致 |
| DOM スナップショット | Playwright 判定 かつ 差分領域に DOM 変更がある場合のみ、実行後の `document.body` を正準化 | 正準文字列一致 |
| 式差分値（F3） | `gum_diff` の差分が式の部分木に閉じ、式として評価できる場合、その式を `__record(EXPR)` で計装した評価値を直列化 | 直列化文字列一致 |

DOM 正準化: 要素ツリーをタグ名小文字・属性名昇順・テキストノードの空白正規化で直列化する。

### 式差分値（F3）の詳細

位置（末尾か否か）ではなく、**差分そのものが式に閉じているか**で適用を判定する。ペア単位の処理であり、`gum_diff(A, B)` の差分に依存するため Phase C で評価する。

1. `gum_diff(A, B)` で差分ノードを特定する（`find_scope_boundary_index` / `find_sibling_root_indices` で差分の所属スコープ・兄弟ルートを求める）。
2. 差分を包む**最小部分木の根**が式ノード（`binary_expression` / `call_expression` / `member_expression` / `ternary_expression` / `unary_expression` / `identifier` / `array` / `object` 等、あるいは `expression_statement` の式部分・`if_statement` の条件式など）に収まるかを判定する。統計・宣言・制御キーワードにまたがる差分は非該当。
3. 該当時、差分の式を**位置を問わずその場で** `__record(EXPR)` に包む（引数を評価して素通しで返すため透過的）。オフセットは prettier 整形後基準のため、**整形後ソースへ注入し整形後ソースを実行**する。
4. 両プログラムを実行し、記録した式値を正準シリアライザで比較する。

到達性: 差分が式に閉じていれば周辺の制御構造は両者同一のため、`__record` は両者で同じだけ評価される。式の評価値のみを記録するため、式が副作用を持つ場合（`arr.push(x)` の戻り値 length 等）は全副作用を捕捉しない。

---

## 手順

### Phase A — ベンチマークごとの準備

1. `step5/{node_bench.jsonl, playwright_bench.jsonl}` を読み、判定対象ベンチと env（Node / Playwright）を得る。
2. 各ベンチの `tests` から**全ペア**を列挙する。

### Phase B — プログラムごとの計装と実行

各 origin program（inline + setup + test + teardown）に対し以下を行う。

3. Step V1（変数名抽出）: `gum_parse` で変数名集合を得る（`None` は判定不能寄与）。
4. 計装: 非決定性シムを注入し、Step V2 のリーダ（変数読み取り・完了状態・標準出力・DOM）を追記する。
5. 決定性セルフチェック: **同一シードで 2 回実行**し、記録（変数値 / 完了状態 / 標準出力 / DOM）を照合する。食い違えば当該プログラムを**不安定**とマークする。一致すれば 1 回目の記録を採用する。
   - Node は `dispatch_rule` に対応する Node 環境（`npm` は node_modules 込み）で、Playwright は `page_html.html` を土台にした HTML 文脈で実行する。

### Phase C — ペアごとの判定（順に評価）

6. A または B が不安定 → **判定不能**。
7. いずれかの program が V1 で `None` → **判定不能**。
8. 完了状態を比較: 片方 throw・他方正常、または throw の型 / メッセージ相違 → **非等価**。両方が同型 throw → 一致した観測挙動とみなし次へ。
9. 各チャネル（共有名の変数格納値 / 標準出力 / DOM）を比較: いずれか不一致 → **非等価**。必要チャネルが読取 / 直列化不能 → **判定不能**。
10. 上記で決着しない場合、`gum_diff(A, B)` を計算し、差分が式に閉じていれば F3（式差分値）をペア単位で計装・実行して比較する: 不一致 → **非等価**。
11. 適用可能な全チャネルが一致 → **等価**。

### 判定ロジック早見表

| 状況 | 出力 | 理由コード |
|---|---|---|
| A / B が不安定（セルフチェック失敗） | 判定不能 | `unstable_program` |
| いずれかの program が変数名抽出不能（`gum_parse` None） | 判定不能 | `parse_failed` |
| 完了状態が相違（throw 差） | 非等価 | `completion_mismatch` |
| いずれかのチャネルが不一致 | 非等価 | `channel_mismatch:<name>` |
| 必要チャネルが読取 / 直列化不能 | 判定不能 | `unreadable` |
| 全チャネル一致（両方同型 throw を含む） | 等価 | `all_match` |

---

## 出力スキーマ

再現性のためキーは決定的順序で出力し、`pairs.jsonl` は `(slug_id, i, j)` でソートする。

`programs.jsonl`（1 行 1 プログラム）:

```json
{
  "slug_id": "00008", "test_idx": 1, "env": "node", "dispatch_rule": "node",
  "stable": true,
  "parsed": true,
  "completion": {"status": "completed", "error_type": null},
  "stdout": null,
  "variables": {"i": "num:99", "xs": "arr:[num:0,num:1]"},
  "dom": null
}
```

F3（式差分値）はペア単位の処理のため `programs.jsonl` には現れず、`pairs.jsonl` の `channels.expr` に結果を記録する。

`pairs.jsonl`（1 行 1 ペア）:

```json
{
  "slug_id": "00008", "i": 0, "j": 1, "env": "node",
  "verdict": "equivalent",
  "reason": "all_match",
  "channels": {"completion": "match", "stdout": "n/a", "variables": "match", "dom": "n/a", "expr": "n/a"}
}
```

`channels` の各値は `match` / `mismatch` / `partial` / `n/a` のいずれか。

---

## スコープ（本手順で意図的に受容する挙動）

以下は偽陽性（等価側）に倒れることを明示する。

- **生存性を静的解析しないことの帰結**: 実行後にスコープ外で参照できない名前（関数ローカルのみの変数等）はスキップされ、比較対象にならない。共有名がすべてスキップ / 一致となるペアは **等価** に分類される。
- **値を捨てる test 本体**: 生存変数に痕跡が残らない差分は、F3 が適用されない限り全チャネル空一致で **等価** に分類される。
- **単一シード = 入力 1 点**: 退化データや偶然の一致が残存しうる。乱数も入力も振れないベンチは特に単一点評価となる。
- **sloppy の暗黙グローバル**: 未宣言代入で生成されるグローバルは宣言ノードが無く V1 で抽出されないため、変数チャネルには現れない。
- **gumtree / prettier の失敗**: 解析不能な program を含むペアは判定不能となる。
- **teardown は共有**: origin に含めたまま実行するが、全テスト共有のためペア相対比較には影響しない。
