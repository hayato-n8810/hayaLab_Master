# 粒度判定セッション引き継ぎ

このファイルは `experiments/pattern/granularity_analysis.py` の実装・議論を行う際に
参照する研究コンテキストを記述する．

---

## 研究目的

OSSのJavaScriptコード変換パターン（before→after）のbefore側の特徴を，
変換差分を含む数十行程度のASTノード集合から**機械的に抽出・照合するための
最適な切り出し粒度を判定する**．

先行研究パターンのbeforeコードを直接参照せず，機械的に辿り着くことが目標．

---

## データファイル

| ファイル | 内容 |
|---|---|
| `data/processed/MBDiff.json` | 29809件の実装対（`base_ast.code`・`base_ast.tree`・`base_actions` を含む）|
| `outputs/AST/scope_DIFF_BLOCK_targets.json` | ターゲット14IDの s2（DIFF merged）ノード列 |
| `outputs/AST/scope_BROTHER_DIFF_target.json` | ターゲット14IDの brother（BROTHER_DIFF merged）ノード列 |
| `outputs/AST/scope_BLOCK_INCLUDE_DIFF_targets.json` | ターゲット14IDの s4（BLOCK_INCLUDE merged）ノード列 |

`MBDiff.json` は `classes/gumtree.py` の `GumDiff` 型に対応する．

---

## 候補スコープの列挙・集約・評価

### 列挙

以下の全スコープについて ASTNode リストを切り出す：

| 名称 | 元データ | 内容 |
|---|---|---|
| `s1_pa_N` | `scope_DIFF_BLOCK_targets.json` | DIFF per_action 各個 |
| `s2` | 同上 | DIFF merged（全 per_action 統合） |
| `br_pa_N` | `scope_BROTHER_DIFF_target.json` | BROTHER_DIFF per_action 各個 |
| `br` | 同上 | BROTHER_DIFF merged |
| `s3_pa_N` | `scope_BLOCK_INCLUDE_DIFF_targets.json` | BLOCK_INCLUDE per_action 各個 |
| `s4` | 同上 | BLOCK_INCLUDE merged |

包含関係（DIFF ⊆ BROTHER_DIFF ⊆ BLOCK_INCLUDE）があることは承知の上で，
per_action 粒度での細かな差異も捉えるために全て列挙する．

### フィルタリング

意味のある候補に絞るため，列挙後に以下を除外する：

- **記号のみ候補**: ノードが全て汎用記号（`.`, `(`, `)`, `,`, `;`, `{`, `}`, `[`, `]`, `=>`, `=` 等）で構成されているもの

### 重複除去（集約）

ASTNode リストが完全に同一（ノードの `origin_index` 列が一致）な候補は1つに集約する．
これにより，例えば per_action が1つしかない ID では `s1_pa_0 == s2` になり，どちらか一方だけが残る．

---

## 相対選択による粒度判定

固定閾値（V1/V2）ではなく，**同一IDの複数スコープをコーパス検索結果で相対比較**して粒度を選ぶ．

### 評価軸

各スコープについて，コーパス（MBDiff.json の全29809件）に対して2軸で検索しヒット数を記録する：

| 軸 | クエリ | コーパス側 | 意味 |
|---|---|---|---|
| **AST軸** | スコープの bigram set | `base_ast.tree` のトークン列（bigram AND 検索）| 構造的に類似したプログラムが何件あるか |
| **文字列軸** | 具体的終端トークンの正規表現 | `base_ast.code`（正規表現マッチング）| テキストとして類似したプログラムが何件あるか |

### 文字列軸の正規表現生成

「具体的終端トークンのワイルドカード正規表現」：

1. スコープのノードから終端ノード（`label` が `name: value` 形式）を順に取り出す
2. 以下を除外する：
   - 抽象化変数: `VAR_*`, `FUNCTION_*`, `KEY_*`
   - 汎用記号: `.`, `(`, `)`, `,`, `;`, `{`, `}`, `[`, `]`, `:`, `=>`, `=`, `+`, `-`, `*`, `/`, `<`, `>`, `!`, `|`, `&`, `?`
3. 残ったトークン値（例: `reduce`, `assign`, `split`, `"_"`, `String`, `65535`）を出現順に `.*` で繋いだ正規表現を生成
4. `base_ast.code` に対して `re.search` でマッチング

V2（property_identifier か否か）のような型分類に依存しない．値レベルで「具体的か汎用的か」を判断する．

### 選択基準

```
候補一覧: フィルタリング・重複除去後の全スコープ
各スコープの結果: (ast_hits, str_hits, ast_R, str_R)
  R = 1 if target_id ∈ hits else 0

選択:
  1. ast_R=1 を満たす候補の中で ast_hits が最小のものを選ぶ
  2. ast_hits が同数の場合はノード数が少ない方（より小さいスコープ）を選ぶ
  3. str_hits も参考指標として記録する（絞り込みの補助に使う）
```

差分軸（`base_actions` から差分ノードのみ抽出してコーパス側を絞る）は，上記で区別できないケースが生じた際に追加する．

---

## トークン表現（`node_token()` 関数）

```python
# 構造ノード（name == value かつ非終端）→ name のみ
# 終端ノード（identifier, property_identifier, number, string_fragment）→ name:value
```

変数名は全て `VAR_N`，関数名は `FUNCTION_N` に抽象化済み．

---

## 同族パターンの知見（s2 bigram Jaccard）

コーパス全体での Cross-match とは別に，ターゲット14ID 間での類似度：

| ペア | Jaccard | 共通特徴 |
|---|---|---|
| 791 vs 902 | 0.41 | reduce + arrow_function |
| 1206 vs 1306 | 0.43 | call_expression + identifier:String |
| 2512 vs 2919 | 0.39 | toString.call チェーン |

同族ペアの統合や扱いは，粒度選択の後フェーズで検討する．

---

## 未検討・今後の課題

- 差分軸（`base_actions` → 差分ノードのみ抽出）: ast_hits だけで区別できないケースが出次第追加
- 同族パターンの統合: 粒度選択確定後に検討
- 出力形式の決定: skeleton / YAML 制約仕様 / n-gram フィンガープリント

---

## 関連ファイル

- 実装: `experiments/pattern/granularity_analysis.py`
- ライブラリ候補置き場: `src/hayalab/pattern/`（ロジックが確定次第移行）
