# 粒度判定実験（granularity_analysis.py）設計まとめ

> 対象ファイル: `experiments/pattern/granularity_analysis.py`  
> 研究コンテキスト: `.agent/instructions/granularity-analysis.md`  
> 最終更新: 2026-05-08

---

## 1. 研究目的
OSSのJavaScriptコード変換パターン（slow→fast）のslow側の特徴を，  
変換差分を含む数十行程度のASTノード集合から**機械的に抽出・照合するための最適な切り出し粒度を判定する**．

**方針**: 先行研究のbeforeコード(`tmp/previous_sutudy_pattern.png`)に示す特徴を，機械的な検索で辿り着くことが目標．
- 直接，先行研究のbeforeコードは参照しない．
- 切り出す粒度の基準として，変更差分から作成したslow構造の振る舞いが理解可能かつ，他のプログラムも含めた中から特定できるものにする．

---

## 2. データ構造

| ファイル | 内容 |
|---|---|
| `data/processed/MBDiff.json` | 29,809件の実装対（`base_ast.code`, `base_ast.tree`, `base_actions` を含む）|
| `outputs/AST/scope_DIFF_BLOCK_targets.json` | ターゲット14IDの merged_diff（DIFF merged）ノード列 |
| `outputs/AST/scope_BROTHER_DIFF_targets.json` | ターゲット14IDの merged_brother（BROTHER_DIFF merged）ノード列 |
| `outputs/AST/scope_BLOCK_EXCLUDE_PARENT_targets.json` | ターゲット14IDの merged_exclude_block（BLOCK_EXCLUDE_PARENT merged）ノード列 |
| `outputs/AST/scope_BLOCK_INCLUDE_DIFF_targets.json` | ターゲット14IDの merged_include_block（BLOCK_INCLUDE merged）ノード列 |

- `MBDiff.json` は `hayalab.classes.gumtree.GumDiff` 型に対応
- 各ノード列は

```json
{
  "origin_index": index, // `hayalab.classes.gumtree.Gumdiff`におけるAST.treeのインデックス
  "begin": node.begin,
  "end": node.end,
  "label": node.label,
  "name": node.name,
  "value": node.value,
  "parent": node.parent,
}
```

型に対応したASTノードのリストを持つ．

---

## 3. 候補スコープの階層

包含関係: **DIFF ⊆ BROTHER_DIFF ⊆ BLOCK_EXCLUDE_PARENT ⊆ BLOCK_INCLUDE**

現在の実装では per_action スコープはコメントアウトされており，merged スコープのみを候補として列挙する．

| 名称 | 元データ | 内容 |
|---|---|---|
| `merged_diff` | `scope_DIFF_BLOCK_targets.json` | DIFF merged（全 per_action 統合） |
| `merged_brother` | `scope_BROTHER_DIFF_targets.json` | BROTHER_DIFF merged |
| `merged_exclude_block` | `scope_BLOCK_EXCLUDE_PARENT_targets.json` | BLOCK_EXCLUDE_PARENT merged |
| `merged_include_block` | `scope_BLOCK_INCLUDE_DIFF_targets.json` | BLOCK_INCLUDE merged |

---

## 4. 処理パイプライン

```
列挙（enumerate_candidates）
  ↓
重複除去（deduplicate）              ← origin_index が全て同じ候補を集約
  ↓
フィルタリング（filter_candidates）  ← 記号のみを含む候補を除外
  ↓
評価（evaluate_candidates）          ← AST軸・文字列軸でコーパス検索
  ↓
相対選択（select_scope）             ← ast_R=1 かつ ast_hits 最小を選ぶ
```

### 4.1 重複除去

リスト中の，`origin_index` が全て一致する候補を同一とみなし，ひとつだけ残す．  
→ per_action が1つしかない ID では `per_diff == merged_diff` となり一方のみが残る．

### 4.2 フィルタリング条件

**記号のみ候補**:
- ASTノードのリストに含まれる，label が "name: value" 形式の全てのノードを対象とする．
- 各粒度の対象ノードが「全て」以下のノードであった場合除外する．（適宜追加予定）
  - name：
    - 文字列： `string_fragment`, `escape_sequence`
    - 数字： `number`
  - value:
    - 汎用記号: `(`, `)`, `,`, `;`, `{`, `}`, `[`, `]`, `"`, `'`, `\"`
    - 演算子： `+`, `-`, `*`, `/`
    - キーワード: `var`, `let`, `const`
    - 抽象化変数: `VAR_*`, `FUNCTION_*`, `KEY_*`


---

## 5. 評価軸（☆☆☆要検討）

| 軸 | クエリ | コーパス側 | 意味 |
|---|---|---|---|
| **AST軸** | スコープの bigram set | `base_ast.tree` のトークン列（bigram AND 検索）| 構造的に類似したプログラムが何件あるか |
| **文字列軸** | 具体的終端トークンの正規表現 | `base_ast.code`（`re.search` マッチング）| テキストとして類似したプログラムが何件あるか |

各スコープの評価結果: `(ast_hits, str_hits, ast_R, str_R)`  
`R = 1 if target_id ∈ hits else 0`

---

## 6. トークン表現（`node_token()` 関数）

```python
# 構造ノード（name == value かつ非終端）  →  name のみ
# 終端ノード（identifier, property_identifier, number, string_fragment）  →  name:value
```

変数名は `VAR_N`，関数名は `FUNCTION_N` に抽象化済み（事前処理による）．

---

## 7. 文字列軸の正規表現生成（`build_str_query()`）

1. ノードから `label` が `"name: value"` 形式のもの（終端ノード）を出現順に取り出す
2. 以下を除外:
   - 抽象化変数: `VAR_*`, `FUNCTION_*`, `KEY_*`
   - 汎用記号: `.`, `(`, `)`, `,`, `;`, `{`, `}`, `[`, `]`, `:`, `=>`, `=`, `+`, `-`, `*`, `/`, `<`, `>`, `!`, `|`, `&`, `?`
   - 空白のみのトークン
3. 残ったトークン値を出現順に `.*` で繋いだ正規表現を生成

**設計方針**: property_identifier か否かのような型分類に依存せず，文字列レベルでslow処理の特徴か一般的な文字列かを判断する．

---

## 8. スコープ選択基準（`select_scope()`）（☆☆☆要検討）

```
1. ast_R=1 を満たす候補のみを viable とする
2. viable の中からast_hits が最小のものを選ぶ
3. ast_hits が同数の場合はノード数が少ない方（より小さいスコープ）を優先
4. str_hits は参考指標として記録する
```

---

## 9. 出力形式

`outputs/pattern/granularity_result_merged_only.json` に以下を書き出す:

```json
[
  {
    "id": 791,
    "selected_scope": "merged_diff",
    "ast_hits": 42,
    "str_hits": 17,
    "str_query": "reduce.*arrow_function",
    "nodes": [...],
    "all_candidates": [
      {
        "name": "merged_diff",
        "ast_hits": 120,
        "str_hits": 45,
        "ast_R": 1,
        "str_R": 1,
        "str_query": "...",
        "node_count": 5
      },
      ...
    ]
  },
  ...
]
```

---

## 10. 同族パターンの知見

コーパス全体での cross-match とは別に，ターゲット14ID 間での merged_diff bigram Jaccard 類似度:

| ペア | Jaccard | 共通特徴 |
|---|---|---|
| 791 vs 902 | 0.41 | reduce + arrow_function |
| 1206 vs 1306 | 0.43 | call_expression + identifier:String |
| 2512 vs 2919 | 0.39 | toString.call チェーン |

同族ペアの統合・扱いは粒度選択の**後フェーズ**で検討する．

---

## 11. 未検討・今後の課題

| 課題 | トリガー条件 |
|---|---|
| **差分軸の追加** (`base_actions` → 差分ノードのみ抽出してコーパス側を絞る) | AST軸だけでは区別できないケースが生じた時 |
| **同族パターンの統合** | 粒度選択確定後 |
| **出力形式の決定** | skeleton / YAML 制約仕様 / n-gram フィンガープリントから選択 |
| **ライブラリへの移行** | ロジックが確定次第 `src/hayalab/pattern/` へ移動 |

---

## 12. 関連ファイル

| パス | 役割 |
|---|---|
| `experiments/pattern/granularity_analysis.py` | 本実装 |
| `.agent/instructions/granularity-analysis.md` | セッション引き継ぎ用コンテキスト |
| `src/hayalab/pattern/` | ロジック確定後の移行先候補 |
| `outputs/pattern/granularity_result_merged_only.json` | 実行結果の出力先 |
