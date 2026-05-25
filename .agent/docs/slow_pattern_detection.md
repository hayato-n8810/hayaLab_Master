# Slow Pattern Detection — 仕様書

## 目的

Selakovic & Pradel (2016) "Performance Issues and Optimizations in JavaScript: An Empirical Study" に示された **10 種類の低速パターン**（before 側のコード）を、`data/processed/MBDiff.json` の `base_ast`（slow 版）に対して **AST マッチング** により検出する。
あわせて、検出箇所が実際に「fast 版で書き換えられている」ペアに限定する **diff 連動フィルタ** を提供し、マイクロベンチマークが先行研究のパターンをどの程度含んでいるかを定量化する。

実装はしない。本文書はあくまで matcher と出力の仕様を定義する。実装計画は `.agent/plans/slow_pattern_detection/PLAN.md` を参照。

---

## 入力データ

### `data/processed/MBDiff.json` の構造

```
[
  {
    "id": <int>,
    "diff": {
      "matches":       [[base_idx, head_idx], ...],
      "base_ast":      { "code": <str>, "tree": [<ASTNode>...] },
      "base_actions":  [<GumTreeAction>, ...],
      "head_ast":      { "code": <str>, "tree": [<ASTNode>...] },
      "head_actions":  [<GumTreeAction>, ...]
    }
  },
  ...
]
```

### `ASTNode` のスキーマ

`hayalab.classes.gumtree.ASTNode` と同形。各ノードは次のフィールドを持つ。

- `begin`, `end`: ソース上の `[begin, end)` バイト位置。
- `label`: 表示用ラベル（`<name>: <value> [begin,end]` 形式）。マッチング判定には使わない。
- `name`: tree-sitter のノード種別（snake_case）。または anonymous ノードの場合は記号そのもの（例: `.`, `(`, `,`, `==`, `===`, `%`, `!==`）。
- `value`: 識別子・リテラル等の表層値。ノード種別と一致する場合（例: `program: program`）は冗長に同じ文字列。
- `parent`: 祖先ノードのインデックス列（根 → 直近の親の順）。`len(parent)` が深さ。

### `parent` 配列に基づく親子判定

- ノード `i` の直接の子ノード集合は次で定義される：

  ```
  direct_children(nodes, i) = [ j  for j > i
                                   if nodes[j].parent == nodes[i].parent + [i] ]
  ```

- 既存 `_build_ast_fragment` は depth と prefix のみで判定しているが、それは「兄弟の子も拾う」リスクがある。本仕様で追加するヘルパーは厳格に `parent == parent_of(i) + [i]` を要求する。
- 子は **ソース順** に並んでいる（tree-sitter の出力性質）。

### 抽象化の前提

`hayalab.abst` による抽象化は **ユーザ定義の変数名・関数名のみ** を対象とし、JavaScript 組込み・標準ライブラリ・jQuery のメソッド名（`String`, `hasOwnProperty`, `substr`, `charAt`, `replace`, `split`, `join`, `toString`, `call`, `reduce`, `forEach`, `map`, `filter`, `html`, `empty`, `slice`, `arguments`, `Array`, `Object`, `Math` 等）は **置換されない**。
したがって、これらの名称はマッチング条件にそのまま埋め込んでよい。

---

## tree-sitter ノードの実観測（`outputs/tmp/previous_ast.json` に基づく）

`tmp/js-treee-sitter-node-types.json` の `fields` 情報（`object`, `property`, `function`, `arguments`, `condition`, `body` 等）は **MBDiff の `tree` には保存されていない**。子はフラットに source 順で並ぶだけなので、field アクセス相当の操作は「ソース順の何番目の named child か」または「特定の name を持つ子をフィルタ」で再現する。

主要なノードの子構造（`outputs/tmp/previous_ast.json` の id_1〜id_10 で実測）：

- `call_expression` の直接の子 = `[<callee_expr>, arguments]`
- `member_expression` の直接の子 = `[<object_expr>, ".", property_identifier]`（`optional_chain` がある場合のみ間に挿入）
- `binary_expression` の直接の子 = `[<left_expr>, <op_anon>, <right_expr>]`（`op_anon.name` ∈ `{==, ===, !=, !==, %, +, -, *, /, <, >, <=, >=, &, |, &&, ||, ...}`）
- `arguments` の直接の子 = `["(", <arg1>, ",", <arg2>, ..., ")"]`
- `if_statement` の直接の子 = `["if", parenthesized_expression, <consequence>, ("else", <alternative>)?]`
- `parenthesized_expression` の直接の子 = `["(", <inner_expr>, ")"]`
- `for_in_statement` の直接の子 = `["for", "(", <kind_anon>, <left>, "in"|"of", <right>, ")", <body_stmt>]`
- `statement_block` の直接の子 = `["{", <stmt1>, <stmt2>, ..., "}"]`
- `string` の直接の子 = `["\"", (string_fragment | escape_sequence | html_character_reference)*, "\""]`
  - 空文字 `""` / `''` は `string_fragment` を含まない（子は引用符 2 つだけ）。
- `subscript_expression` の直接の子 = `[<object_expr>, "[", <index_expr>, "]"]`
- `array` の直接の子 = `["[", (<elem>, ",")*, "]"]`
- 関数式は MBDiff 上では `name == "function"`（grammar のバージョン差により `function_expression` で現れる場合あり）。アロー関数は `name == "arrow_function"`。

### 区切り文字（punctuation）ノード

次の `name` を持つ anonymous ノードは「飾り」として子集合から除外する：

```
{ ".", ",", ";", ":", "(", ")", "[", "]", "{", "}", "\"", "'", "`" }
```

ただし `binary_expression` の **演算子** や `for_in_statement` の `in`/`of`、`if`/`for`/`while` 等のキーワードは punctuation ではないため、別途必要に応じて参照する。

---

## 共有ヘルパー API（`src/hayalab/pattern/ast_nav.py` として追加予定）

すべて純関数。`code: str` を必要とするものは引数で受け取る。`hayalab.classes.gumtree.ASTNode` のリストを `nodes` とする。

```python
PUNCT = frozenset({".", ",", ";", ":", "(", ")", "[", "]", "{", "}", "\"", "'", "`"})

def direct_children(nodes, idx) -> list[int]:
    """node[idx] の直接の子インデックス（source 順、punctuation も含む全件）"""

def named_children(nodes, idx) -> list[int]:
    """direct_children から PUNCT を除いたもの"""

def find_first_child(nodes, idx, name: str | set[str]) -> int | None:
    """子のうち最初に name に一致するもの"""

def get_call_callee(nodes, call_idx) -> int | None:
    """call_expression の callee（最初の named child）"""

def get_call_arguments(nodes, call_idx) -> list[int]:
    """call_expression > arguments の named children（位置引数のインデックス列）"""

def get_member_object(nodes, member_idx) -> int | None:
    """member_expression の object（最初の named child）"""

def get_member_property_name(nodes, member_idx) -> str | None:
    """member_expression の property_identifier.value"""

def get_binary_operator(nodes, bin_idx) -> str | None:
    """binary_expression の演算子記号（== / === / % など）。
       direct_children の中で PUNCT に含まれず name in OPERATOR_SET のもの。"""

def get_binary_lhs(nodes, bin_idx) -> int | None:
    """left オペランド（最初の named child で operator 以外）"""

def get_binary_rhs(nodes, bin_idx) -> int | None:
    """right オペランド（最後の named child で operator 以外）"""

def get_if_condition_expr(nodes, if_idx) -> int | None:
    """if_statement の parenthesized_expression の中身式"""

def get_if_consequence(nodes, if_idx) -> int | None:
    """if_statement の本体 statement（statement_block 等）"""

def get_for_in_body(nodes, for_in_idx) -> int | None:
    """for_in_statement の body statement（最後の named child）"""

def first_named_statement(nodes, block_idx) -> int | None:
    """statement_block の最初の named child（最初の文）"""

def is_empty_string_literal(nodes, str_idx) -> bool:
    """string ノードに string_fragment / escape_sequence / html_character_reference を 1 つも含まないか"""

def is_number_literal(nodes, idx, value: str | set[str]) -> bool:
    """name == 'number' かつ value が一致"""

def is_identifier(nodes, idx, value: str | None = None) -> bool:
    """name == 'identifier' （value 指定時はそれにも一致）"""

def is_property_identifier(nodes, idx, value: str | None = None) -> bool:
    """name == 'property_identifier' （value 指定時はそれにも一致）"""

def walk_pre(nodes) -> Iterator[int]:
    """0..len(nodes) を順に返す（ソース pre-order に等しい）"""
```

`OPERATOR_SET` は仕様内で次のように定義する：

```
OPERATOR_SET = {
  "==", "===", "!=", "!==", "<", "<=", ">", ">=",
  "+", "-", "*", "/", "%", "**",
  "&", "|", "^", "<<", ">>", ">>>",
  "&&", "||", "??",
  "in", "instanceof"
}
```

---

## パターン別マッチング仕様

各パターンは以下の共通形式で定義する：

- **対象ノード**: マッチングの起点となる `name`
- **追加条件**: 起点ノードと、ヘルパー関数で取得する子・孫の条件
- **抽出結果**: `PatternMatch` レコード（後述）の構築方法
- **想定 false positive**

### Pattern 1: `for-in` + `hasOwnProperty`

- **対象ノード**: `name == "for_in_statement"`
- **追加条件**:
  1. `get_for_in_body(idx)` が `statement_block`（`name == "statement_block"`）
  2. その body の `first_named_statement` が `if_statement`
  3. その `if_statement` の `get_if_condition_expr` が `call_expression`
  4. その `call_expression` の callee が `member_expression` であり、`get_member_property_name == "hasOwnProperty"`
  5. （任意・信頼度向上のため）`member_expression.object` の `identifier.value` が、`for_in_statement` の right（被走査オブジェクト）と一致する。
- **抽出結果**: `pattern_id=1`、`confidence=high`（条件 5 を満たすとき）または `medium`
- **想定 FP**: for-in 内に偶然 `hasOwnProperty` 以外の hasOwnProperty 名 user-defined メソッドが存在するケース（抽象化対象外なので低リスク）

### Pattern 2: `substr(i, 1)` による 1 文字抽出

- **対象ノード**: `name == "call_expression"`
- **追加条件**:
  1. callee が `member_expression` で `get_member_property_name == "substr"`
  2. `get_call_arguments` の長さが 2
  3. `args[1]` が `is_number_literal(value="1")`
- **抽出結果**: `pattern_id=2`、`confidence=high`
- **想定 FP**: ほぼなし

### Pattern 3: `String(x)` による型変換

- **対象ノード**: `name == "call_expression"`
- **追加条件**:
  1. `get_call_callee` が `identifier` で `value == "String"`
  2. `get_call_arguments` の長さが 1
- **抽出結果**: `pattern_id=3`、`confidence=high`（抽象化が組込みを保護する前提下で）
- **想定 FP**: ユーザが自前で `String` という関数を再定義しているケース（極めて稀）

### Pattern 4: jQuery `html('')`

- **対象ノード**: `name == "call_expression"`
- **追加条件**:
  1. callee が `member_expression` で `get_member_property_name == "html"`
  2. `get_call_arguments` の長さが 1
  3. `args[0]` が `name == "string"` かつ `is_empty_string_literal == True`
- **抽出結果**: `pattern_id=4`、`confidence=high`
- **想定 FP**: jQuery でないオブジェクトの `.html("")`（識別不能だが構文的に同パターン）

### Pattern 5: `substr(0, N) ==|=== str` による先頭比較

- **対象ノード**: `name == "binary_expression"`
- **追加条件**:
  1. `get_binary_operator` ∈ `{"==", "===", "!=", "!=="}`
  2. lhs / rhs のいずれかが `call_expression`、その callee が `member_expression` で `property_identifier.value == "substr"`
  3. その `substr` の `arguments` が長さ 2、`args[0]` が `is_number_literal(value="0")`、`args[1]` が `name == "number"` で正の整数（`int(value) > 0`）
- **抽出結果**: `pattern_id=5`、`confidence=high`
- **想定 FP**: なし

### Pattern 6: `split(...).join(...)` チェーン

- **対象ノード**: `name == "call_expression"`
- **追加条件**:
  1. callee が `member_expression`、その `property_identifier.value == "join"`
  2. その `member_expression.object` が `call_expression`、さらにその callee が `member_expression` で `property_identifier.value == "split"`
- **抽出結果**: `pattern_id=6`、`confidence=high`
- **想定 FP**: `.split().join()` のチェーンを別の意図（区切り直し）で書いているケースを過剰検出。信頼度は high のまま保持し、レビュー時に diff 連動フィルタで除外する。

### Pattern 7: `toString.call(x) ==|=== "[object ...]"`

- **対象ノード**: `name == "binary_expression"`
- **追加条件**:
  1. `get_binary_operator` ∈ `{"==", "==="}`
  2. lhs / rhs のいずれかが `call_expression`、その callee が `member_expression`
     - `member_expression.object` が `identifier` で `value == "toString"`
     - `member_expression.property_identifier.value == "call"`
  3. もう一方が `name == "string"` で `string_fragment.value` が `"[object"` で始まる
- **抽出結果**: `pattern_id=7`、`confidence=medium`（toString が組込みか不明なため）
- **想定 FP**: ローカル変数 `toString` の `.call()`

### Pattern 8: `n % 2 ==|=== 0|1` による偶奇判定

- **対象ノード**: `name == "binary_expression"`
- **追加条件**:
  1. `get_binary_operator` ∈ `{"==", "==="}`
  2. lhs / rhs のいずれかが `name == "binary_expression"` で `get_binary_operator == "%"`、かつ rhs が `is_number_literal(value="2")`
  3. もう一方が `is_number_literal(value in {"0","1"})`
- **抽出結果**: `pattern_id=8`、`confidence=high`
- **想定 FP**: なし

### Pattern 9: 高階関数 (`reduce`/`forEach`/`map`/`filter`) + コールバック

- **対象ノード**: `name == "call_expression"`
- **追加条件**:
  1. callee が `member_expression`、`property_identifier.value` ∈ `{"reduce", "forEach", "map", "filter"}`
  2. `get_call_arguments` の中に `name` ∈ `{"function", "function_expression", "arrow_function"}` のノードを 1 つ以上含む
- **抽出結果**: `pattern_id=9`、`confidence=low`（単独では FP 過多）
- **想定 FP**: 大半のケース。**diff 連動フィルタ必須**（後述）。

### Pattern 10: 要素数 1 の非効率な `join`（`[].slice.call(...).join(...)`）

- **対象ノード**: `name == "call_expression"`
- **追加条件**:
  1. callee が `member_expression`、`property_identifier.value == "join"`
  2. その `member_expression.object` が `call_expression`
     - その内側 `call_expression` の callee が `member_expression`、`property_identifier.value == "call"`
     - さらにその `member_expression.object` が `member_expression` で `property_identifier.value == "slice"`
- **抽出結果**: `pattern_id=10`、`confidence=medium`（`[].slice.call` は他の用途もあるため）
- **想定 FP**: `Array.prototype.slice.call(arguments)` のような他用途

---

## 出力スキーマ

### `PatternMatch`（1 件のマッチ）

```jsonc
{
  "mb_id":         <int>,        // MBDiff レコードの id
  "side":          "base",       // 当面は base のみ。head 検出は将来拡張用フィールド。
  "pattern_id":    <int>,        // 1〜10
  "confidence":    "high" | "medium" | "low",
  "node_index":    <int>,        // 起点ノードの index
  "begin":         <int>,        // ソース上の開始位置
  "end":           <int>,        // ソース上の終了位置
  "snippet":       <str>,        // code[begin:end]（先頭 200 文字でクリップ）
  "diff_linked":   <bool>,       // 後述の diff 連動判定の結果
}
```

### 出力ファイル

```
outputs/tmp/previous_patterns/
├── summary.json              # 各 pattern_id ごとの (件数, 信頼度別件数, diff_linked 件数)
├── matches.jsonl             # 全 PatternMatch（1 行 1 件）
└── samples/
    └── pattern_<id>/
        ├── high.jsonl        # 信頼度別 + diff_linked のサンプル（最大 50 件）
        └── representative.md # 上位 3 件のコード断片と説明（人手レビュー用）
```

`hayalab` 側は I/O を行わず、`experiments/slow_pattern_detect/run.py` がこのレイアウトに書き出す（境界規約：`experiments → hayalab` のみ）。

---

## 検出パイプラインの 2 段構え

### Stage A: BEFORE-only 検出（母数把握）

`base_ast.tree` 全件にすべての matcher を適用。結果は `matches.jsonl` に `diff_linked=false` で記録される（初期値）。

### Stage B: diff 連動フィルタ（論文対応分の特定）

検出した起点ノードについて、`diff.base_actions` および `diff.matches` を参照して、以下のいずれかに該当するなら `diff_linked = true` とする。

1. **node_updated**: `base_actions` のうち、`tree.index` または `ancestors[*].index` が起点ノード `node_index` と一致するもの（= GumTree が当該ノードを update/delete/move として扱った）。
2. **subtree_modified**: `base_actions` のいずれかの `tree.index` が、起点ノードの `[begin, end]` 範囲内 `[begin, end)` に含まれる。
3. **mapped_to_different_kind**: `matches` を引いて起点ノードに対応する head 側ノードの `name` を取得し、それが「論文の after に対応する name」と一致する。
   - Pattern 1: head 側が `for_statement`（Object.keys ループ）
   - Pattern 2: head 側が `subscript_expression` または `member_expression`（`property_identifier.value == "charAt"`）
   - Pattern 3: head 側が `binary_expression`（`operator == "+"`、片側が `""` の string）
   - Pattern 4: head 側 callee が `member_expression`、`property_identifier.value == "empty"`
   - Pattern 5: head 側 callee が `member_expression`、`property_identifier.value` ∈ `{"charAt"}`
   - Pattern 6: head 側 callee が `member_expression`、`property_identifier.value == "replace"`
   - Pattern 7: head 側に `binary_expression` で `operator == "instanceof"`
   - Pattern 8: head 側に `binary_expression` で `operator == "&"`、rhs が `number "1"`
   - Pattern 9: head 側が `for_statement`
   - Pattern 10: head 側に「要素数で分岐する `if_statement` + 配列 1 要素時の直接 String 化」が出現（構造判定は困難なので、`if_statement` の存在をヒューリスティックとし `confidence` を 1 段下げる）

`diff_linked = false` のマッチは「マイクロベンチには BEFORE が存在するが fast 版で変更されていない」ケースであり、論文のパターンとは別文脈で書かれている可能性が高い。`matches.jsonl` には残すが `summary.json` の主要数値（"論文対応分"）は **Stage B 合格分** で集計する。

---

## 境界規約（再掲）

- `src/hayalab/pattern/` 配下のコードは **I/O 禁止**（ファイル読み書き、`print`、パス解決をしない）。
- `experiments/tmp/slow_pattern_detect/` がパス決定・ファイル書き出し・進捗ログを担う。
- すべての matcher は純関数として `list[ASTNode]` と `code: str | None` のみを受け取る。

---

## テスト戦略

1. **フィクスチャ**: `outputs/tmp/previous_ast.json` の id_1〜id_10 を `tests/pattern_detection/fixtures/` にコピーし、各パターンが「対応する id でちょうど 1 件マッチ」「他の id ではマッチしない」ことを確認する。
2. **negative fixtures**: BEFORE と AFTER の混同を防ぐため、各パターンの AFTER 形（`Object.keys(...).forEach`, `str[i]`, `'' + value`, `.empty()`, `.charAt(0)`, `.replace(/x/g, y)`, `instanceof`, `& 1`, 手書き `for`, 単一要素の直接 String 化）を AST 化したフィクスチャを `after_fixtures/` に置き、すべての matcher が 0 件であることを確認する。
3. **MBDiff サンプル**: `data/processed/_sample.json` の小規模サブセットを使い、Stage A 出力件数のリグレッションテストを置く。
4. **Stage B 単体テスト**: `base_actions` / `matches` のモックを使い、`diff_linked` 判定ロジック（3 ルール）の各分岐を網羅する。
5. **e2e ドライラン**: `MBDiff.json` 全件に対して実行し、各パターンの (Stage A 件数, Stage B 件数, 代表サンプル 3 件のコード断片) を `outputs/slow_patterns/summary.json` に記録。

---

## 既知の限界

- スコープ解析を行わないため `toString.call`（pattern 7）・`String`（pattern 3）の **所有者判別** はできない。
- tree-sitter の `function` / `function_expression` のラベル差異は grammar バージョン依存。matcher 側で両方を許容することで対処する。
- `[].slice.call(arguments)` の「実行時に要素 1 個」(pattern 10) は AST 単独では判定できないため、構造一致を以てパターンとみなす。
- マイクロベンチが論文 10 パターンを含まないケース（検出件数 0）は **結論そのもの** として `summary.json` に明示する。
