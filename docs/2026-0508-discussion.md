# 粒度判定手法の設計議論と実装まとめ（2026-05-08）

> 対象実装: `experiments/pattern/granularity_analysis.py`  
> 参照コンテキスト: `.agent/instructions/granularity-analysis.md`

---

## 1. 研究目的

OSSのJavaScriptコード変換パターン（slow→fast の実装ペア）を対象に，slow側（変更前）の構文特徴を**コーパス検索によって機械的に発見できる粒度**でASTノード集合として切り出す手法を確立する．

**目標**: 先行研究が手動で特定した `before` パターンに，検索スコアの高いスコープ選択を通じて自動で辿り着けることを示す．

- 先行研究パターンのコードは直接参照しない
- 変換差分（GumTree の AST diff）を出発点に，コーパス29,809件の中で絞り込みが効くスコープを機械的に選ぶ
- ターゲットは14件の代表的なパターン（各IDがひとつの変換パターンに対応）

---

## 2. データ構造

### 2.1 コーパス

`data/processed/MBDiff.json`: 29,809件のslow/fast実装ペア．各エントリは以下を含む：

```
id            : プログラムID
diff.base_ast.code  : slow側のJavaScriptソースコード
diff.base_ast.tree  : slow側のASTノード列（GumTree形式，抽象化済み）
diff.base_actions   : slow側のGumTree差分アクション列
```

`base_ast.tree` の各ノード（`ASTNode`）の主要フィールド：

```json
{
  "origin_index": 42,
  "label": "identifier: VAR_0",
  "name":  "identifier",
  "value": "VAR_0",
  "parent": [0, 3, 12]
}
```

- `label` は `"name: value"` 形式の場合は終端ノード，構造ノードの場合は `name == value`
- `parent` は祖先ノードのインデックス列（末尾が直接親）
- 変数名・関数名は事前処理で `VAR_N` / `FUNCTION_N` / `KEY_N` に抽象化済み

### 2.2 スコープ事前計算結果

ターゲット14IDに対して4種のスコープを事前計算したJSON（`outputs/AST/`以下）：

| ファイル | スコープ名 | 内容 |
|---|---|---|
| `scope_DIFF_BLOCK_targets.json` | `merged_diff` | GumTree差分ノードとその子孫のmerged集合 |
| `scope_BROTHER_DIFF_targets.json` | `merged_brother` | 差分ノードの直接親の全子孫のmerged集合 |
| `scope_BLOCK_EXCLUDE_PARENT_targets.json` | `merged_exclude_block` | スコープ境界ノード配下の兄弟+差分部分木（境界自身を除く）|
| `scope_BLOCK_INCLUDE_DIFF_targets.json` | `merged_include_block` | スコープ境界ノード配下の全子孫（境界自身を含む）|

包含関係: **DIFF ⊆ BROTHER_DIFF ⊆ BLOCK_EXCLUDE_PARENT ⊆ BLOCK_INCLUDE**

---

## 3. 処理パイプライン概要

```
[1] スコープ候補列挙（enumerate_candidates）
      ↓  各スコープの merged ノードリストを候補化
[2] 重複除去（deduplicate）
      ↓  origin_index が全て同一の候補を1つに集約
[3] フィルタリング（filter_candidates）
      ↓  記号・キーワードのみで構成された候補を除外
[4] コーパス評価（evaluate_candidates）
      ↓  AST軸・文字列軸でコーパス検索し，hits数と R フラグを記録
[5] スコープ選択（3手法）
      baseline  / score_b / score_nab
```

---

## 4. 候補スコープの前処理

### 4.1 重複除去

per_action が1件しかない場合，`merged_diff == merged_brother` となるケースがある（いずれもノードが完全一致）．`origin_index` のfrozensetが同一の候補を同一とみなし，包含関係の小さいスコープ（先に列挙されたもの）を1件だけ残す．

### 4.2 フィルタリング（記号のみ候補の除外）

ASTノード中の全終端ノード（`label` が `"name: value"` 形式）が以下のみで構成されている場合，そのスコープ候補を除外する：

- `name` が `string_fragment`, `escape_sequence`, `number`
- `value` が `(`, `)`, `,`, `;`, `{`, `}`, `[`, `]`, `"`, `'`, `\"`
- `value` が演算子 `+`, `-`, `*`, `/`
- `value` が宣言キーワード `var`, `let`, `const`
- `value` が抽象化変数 `VAR_*`, `FUNCTION_*`, `KEY_*`

このフィルタにより，差分がカッコや演算子のみで意味のあるパターンを持たないケースを排除する．

---

## 5. コーパス評価軸

### 5.1 AST軸（bigram AND 検索）

**目的**: 構造的に類似したプログラムが何件あるかを計測する．

**方法**:
1. スコープのASTノード列をトークン列に変換する（`node_token()` 関数）
   - 構造ノード（`name == value` かつ終端名でない）→ `name` のみ（例: `call_expression`）
   - 終端ノード（`identifier`, `property_identifier` 等）→ `name:value`（例: `identifier:VAR_0`）
2. スコープのトークン列からbigram集合を取得する
3. コーパス全件の逆引きインデックス（bigram → ヒットID集合）に対してAND検索する

**指標**:
- `ast_hits`: コーパス中でそのスコープの全bigramを含む件数
- `ast_R`: ターゲットIDがヒット集合に含まれる場合1，そうでなければ0

### 5.2 文字列軸（全終端トークン・`\s*` 正規表現検索）

**目的**: テキストとして類似したプログラムが何件あるかを計測する．

**方法** (`build_str_query()` 関数):
1. スコープのノードから `label` が `"name: value"` 形式の全終端ノードのvalueを出現順に取り出す
2. 空白のみのvalueを除外する
3. 残ったvalue（`re.escape` 済み）を `\s*` で結合した正規表現を生成する
4. `base_ast.code` に対して `re.search(pattern, code, re.DOTALL)` でマッチングする

**`\s*` セパレータの理由**:  
JavaScriptコードでは，トークン間にスペース・タブ・改行・インデントが入るため，`\s*`（空白文字0個以上）が最も自然なセパレータとなる．`.*` は任意の文字列にマッチしすぎてノイズが増え，` ?`（スペース0〜1個）はコード中の記号・識別子を跨げないため不適切だった（後述の変遷参照）．

**指標**:
- `str_hits`: コーパス中で正規表現がマッチした件数
- `str_R`: ターゲットIDがマッチした場合1，そうでなければ0

---

## 6. スコアリング指標の設計

各スコープ候補について，以下の4つのコーパス非依存指標を計算する．

### 6.1 `diff_ratio`（`w_small`: 小さくする重み）

```
diff_ratio = len(diff_nodes) / len(scope_nodes)
```

- `diff_nodes`: そのIDの `merged_diff` のノードリスト（最小スコープ）
- `scope_nodes`: 評価対象スコープのノードリスト
- スコープが小さいほど（差分ノードが占める割合が大きいほど）1に近づく
- 大きいスコープを選ぶほど値が下がる

### 6.2 `sibling_completeness`（`w_lb`: 大きくする重み）

```
sibling_completeness = mean over diff_parents of:
    |{child of parent} ∩ scope_nodes| / |{child of parent}|
```

- 各差分ノードの直接親（`parent[-1]`）について，その親の全直接子のうちスコープに含まれる割合を求め，平均する
- 値が高い = diff周辺の兄弟ノードが揃っている = 文脈の完備性が高い
- 大きいスコープを選ぶほど値が上がる傾向がある

この2つは対立する：`diff_ratio`（小スコープ優先）と `sibling_completeness`（文脈完備性）を掛け合わせることで，**適切な大きさ** を選ぶ設計になっている．

### 6.3 `abstraction_density_detail`（`abstract_ratio`）

```
abstract_ratio = abstract_count / len(terminal_nodes_in_scope)
```

- 終端ノードのうち `VAR_*`, `FUNCTION_*`, `KEY_*` または `_FILTER_EXCLUDED_VALUES` に含まれるものを「汎用トークン」と定義
- 終端ノードがない場合は `(0, 1.0)` を返す
- **重要な設計判断**: この計算は **候補スコープごとに** 行う．`diff_nodes` に固定してしまうと全候補で同じ定数値になり，スコープ間の差異が生まれない（後述の問題と修正を参照）

---

## 7. 3手法の仕様

### 7.1 baseline（コーパス依存・参照手法）

```
viable = [r for r in results if r["ast_R"] == 1]
selected = min(viable, key=(ast_hits, len(nodes)))
```

- AST bigram AND 検索でターゲットIDが復元できる（`ast_R=1`）最小ヒット数のスコープを選ぶ
- 同率なら小さいスコープ優先
- 完全なコーパス依存：スコープが「コーパス全体で最も絞り込める」かを基準とする
- ターゲットIDが復元できない場合（全候補で `ast_R=0`）は `None`

### 7.2 score_b

```
score_b = diff_ratio * sibling_completeness
viable  = [r for r in results if r["str_R"] == 1]
selected = max(viable, key=score_b)
```

- **最低条件**: `str_R=1`（全終端トークンの `\s*` クエリでターゲットIDが復元できること）
- コーパス非依存のスコアリング（`diff_ratio` と `sibling_completeness` はコーパスを使わない）
- `str_R=1` という最低条件のみコーパスに依存する
- **設計思想**: スコープはコンパクトであるべき（`diff_ratio`）が，同時に diff周辺の文脈が揃っている（`sibling_completeness`）スコープを選ぶ

### 7.3 score_nab（案B×A の統合）

```
score_nab = (ws * (1 - abs_ratio) + (1 - ws) * abs_ratio) * sibling_completeness
    where ws       = diff_ratio(scope)
          abs_ratio = abstraction_density_detail(scope_nodes)[1]
viable    = [r for r in results if r["str_R"] == 1]
selected  = max(viable, key=score_nab)
```

- **最低条件**: `str_R=1`（score_b と同様）
- **abs_ratio が低い（スコープが具体的）**: `ws*(1-abs_ratio)` の寄与が大きく，小スコープが有利
- **abs_ratio が高い（スコープが汎用的）**: `(1-ws)*abs_ratio` の寄与が大きく，大スコープが有利
- さらに `sibling_completeness` で文脈の完備性を全体に重み付け
- **設計思想**: スコープ内の抽象化度が高い（識別子が `VAR_*` 等で置き換えられている）場合，それは個別性が薄いため，より大きい文脈を取ることで絞り込み能力を補う

---

## 8. 設計の変遷と問題解決の記録

### 8.1 abstract_ratio を diff_nodes に固定すると定数になる問題

**問題**: 案Aのアイデアを組み込む際，`abstraction_density(diff_nodes)` を計算すると，`diff_nodes` は全候補で共通のため `abstract_ratio` が全候補で同じ定数になる．これではスコープ間でスコアの差が生まれない．

**解決**: `abstract_ratio` を **評価対象スコープのノードリスト** で計算する（`abstraction_density_detail(r["nodes"])`）．スコープが大きくなるほど，差分以外のノード（変数宣言，汎用記号等）が増え `abstract_ratio` が変化するため，候補間で異なる値をとる．

### 8.2 文字列軸の正規表現セパレータの変遷

| セパレータ | 試みた理由 | 問題点 |
|---|---|---|
| `.*`（任意文字列） | 最も柔軟 | ノイズが多く `str_hits` が過大になる |
| `[ ]?`（スペース0〜1個） | トークン間の空白を許容する意図 | コードには記号・識別子がトークン間に挿入されるため，実質ほぼマッチしない |
| `\s*`（空白文字0個以上） | 改行・インデント・スペースを全て許容 | 採用：最も自然かつ実用的 |

また「抽象化変数 `VAR_*` 等の除外あり版」と「全終端トークン使用版」の比較も行ったが，除外した場合はターゲット特有のトークンが失われてほぼ検索不能になるため，**全終端トークン使用（除外なし）** に統一した．

### 8.3 廃止した手法

以下の手法は実装・検討したが，最終的に廃止した：

| 手法名 | 廃止理由 |
|---|---|
| `select_scope_a`（abstraction densityのみ） | diff_nodes 固定で全候補同値になる問題 |
| `select_scope_ab`（score_b + 案Aの固定abs_ratio） | 同上の問題を引き継ぐ |
| `select_scope_b_abs`（score_b + 差分外ノードの具体性） | 設計が複雑な割に改善が不明瞭 |
| `select_scope_ctx`（文脈ノードの抽象化密度） | score_nab に統合・整理 |
| `build_str_query_raw`（除外フィルタなし版） | `build_str_query` 本体が除外なしに統一されたため不要 |
| `str_R_raw`（除外フィルタなし版の別指標） | 同上 |

---

## 9. 出力形式

`outputs/pattern/granularity_scoring_comparison.json` に保存：

```json
[
  {
    "id": 791,
    "all_candidates": [
      {
        "name": "merged_diff",
        "ast_hits": 320,
        "str_hits": 18,
        "ast_R": 1,
        "str_R": 1,
        "str_query": "reduce\\s*VAR_0\\s*VAR_1",
        "node_count": 8,
        "abstract_count": 3,
        "abstract_ratio": 0.375,
        "w_small": 1.0,
        "w_large_b": 0.667,
        "score_b": 0.667,
        "score_nab": 0.583
      },
      ...
    ],
    "baseline":  {"scope": "merged_diff",   "nodes": [...]},
    "score_b":   {"scope": "merged_brother", "nodes": [...]},
    "score_nab": {"scope": "merged_diff",   "nodes": [...]}
  },
  ...
]
```

`all_candidates` の各フィールド説明：

| フィールド | 説明 |
|---|---|
| `name` | スコープ名（`merged_diff`, `merged_brother`, `merged_exclude_block`, `merged_include_block`）|
| `ast_hits` | AST bigram AND 検索のコーパスヒット数 |
| `str_hits` | 文字列軸正規表現のコーパスヒット数 |
| `ast_R` | ターゲットIDがAST検索でヒットしたか（1/0）|
| `str_R` | ターゲットIDが文字列検索でヒットしたか（1/0）|
| `str_query` | 生成した正規表現クエリ |
| `node_count` | スコープのノード数 |
| `abstract_count` | スコープ内の汎用終端トークン数 |
| `abstract_ratio` | 汎用終端トークンの比率（終端ノード数に対する割合）|
| `w_small` | `diff_ratio`（差分ノードのスコープ内占有割合）|
| `w_large_b` | `sibling_completeness`（diff直接親の子の含有率平均）|
| `score_b` | `diff_ratio * sibling_completeness` |
| `score_nab` | `(ws*(1-abs_ratio) + (1-ws)*abs_ratio) * sibling_completeness` |

---

## 10. 関連ファイル

| パス | 役割 |
|---|---|
| `experiments/pattern/granularity_analysis.py` | 本実装（3手法比較のメインスクリプト）|
| `docs/granularity-analysis.md` | 初期設計まとめ（本ドキュメント作成前の古いバージョン）|
| `.agent/instructions/granularity-analysis.md` | セッション引き継ぎ用コンテキスト（研究目的・データ・評価軸の概要）|
| `src/hayalab/gumtree/extract.py` | スコープ切り出しAPI（`cut_scope_diff` 等）|
| `src/hayalab/gumtree/scan.py` | AST走査ユーティリティ（`find_scope_boundary_index` 等）|
| `outputs/pattern/granularity_scoring_comparison.json` | 実行結果の出力先 |
