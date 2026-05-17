# granularity_comparison.py 設計・実装・検討まとめ（2026-05-08）

> 対象実装: `experiments/pattern/granularity_comparison.py`  
> 前段実装: `experiments/pattern/granularity_analysis.py`  
> 方針文書: `docs/granularity_final_direction_semantic_closure.md`

---

## 1. 位置づけ

`granularity_analysis.py` では3手法（baseline, score_b, score_c）を実装・比較した．
これらは「コーパス検索性能の最大化」または「スコープサイズとAST文脈の両立」を軸に設計されていた．

本スクリプト（`granularity_comparison.py`）は，方針を根本的に転換した**第4手法 `score_d`（semantic closure）**を加え，前3手法と並べて比較する．

### 方針転換の要点

| 旧方針（granularity_analysis.py） | 新方針（granularity_comparison.py） |
|---|---|
| コーパス中でターゲットIDを絞り込む能力を最大化 | diff を含む処理内容が意味的に閉じる最小単位を選ぶ |
| `ast_hits` の最小化・`ast_R=1` を主軸 | `ast_hits` / `str_hits` は補助指標として保持するのみ |
| 文脈完備性（sibling / block）で「大きくする重み」を定義 | 依存識別子の閉包度（dependency completeness）で意味的閉包を測る |

---

## 2. 研究背景

### 2.1 問題設定

OSSのJavaScriptコード変換パターン（slow→fast）について，slow側（変換前）の構文特徴を  
**変換差分から機械的に発見できる粒度**でASTノード集合として切り出したい．

- 先行研究のbeforeコードは直接参照しない
- GumTree差分ノードを出発点に，4種のスコープ（包含順に DIFF ⊆ BROTHER ⊆ EXCL ⊆ INCL）から最適な1つを選ぶ
- ターゲット：14件の代表的なコード変換パターン（ID: 222, 609, 791, 902, 1206, 1306, 1691, 2512, 2919, 6182, 8126, 14412, 21294, 23864）

### 2.2 `granularity_analysis.py` の3手法と限界

| 手法 | スコア式 | 最低条件 |
|---|---|---|
| baseline | ast_R=1 かつ ast_hits 最小 | なし |
| score_b | diff_ratio × sibling_completeness | str_R=1 |
| score_c | diff_ratio × block_completeness | str_R=1 |

`score_c` は `score_b` の `sibling_completeness`（diff直接親ベース）を `block_completeness`（スコープ境界ベース）に置き換えたもので，分母の独立性で改善した

これらの共通問題：「diff周辺の構造的な文脈が揃っているか」は測れるが，  
「diff が参照する識別子の意味がスコープ内で説明できるか」は測れていない．

---

## 3. 新手法の設計：semantic closure

### 3.1 粒度の再定義

> diff を含む処理内容が意味的に閉じる最小単位

検索性能の最大化ではなく，**semantic closure boundary detection** として粒度問題を定式化する．

### 3.2 `str_R` の位置づけ変更

旧方針では `str_hits` の大小をスコアリングに使うことを検討していた．  
新方針では `str_R` は「処理断片として実コード上に成立するか」の **Hard Constraint** として扱う．  
`str_hits` の大小はスコアリングに利用しない．

### 3.3 Hard Constraints

選択候補は以下をすべて満たす必要がある：

1. **全 diff ノードを含む**（`contains_all_diff = True`）
2. **処理断片として成立する**（`str_R = 1`）

### 3.4 最終選択

Hard Constraints を満たす候補のうち，

```
score_d = diff_ratio × dependency_completeness
```

が最大のものを選択する．

---

## 4. 実装内容

### 4.1 構成

`granularity_analysis.py` から共通関数・定数を `sys.path` 経由で import し，  
新規関数を追加する構成になっている．

**import している関数（再利用）**:

```
nodes_to_tokens, build_ast_index
enumerate_candidates, filter_candidates, deduplicate
evaluate_candidates
select_scope, select_scope_b, select_scope_c
diff_ratio, sibling_completeness, block_completeness
_get_diff_nodes, _collect_exclude_block_indices
_ABSTRACT_PREFIXES
```

**新規実装関数**:

| 関数 | 役割 |
|---|---|
| `_abstract_ids(nodes)` | ノードリストから `VAR_*`, `FUNCTION_*`, `KEY_*` の value 集合を返す |
| `dependency_completeness(diff_nodes, scope_nodes)` | diff が参照する抽象識別子のうち，scope の context 部分で説明可能な割合 |
| `contains_all_diff(scope_nodes, diff_nodes)` | scope が diff の全ノードを包含するか判定 |
| `select_scope_d(results, diff_nodes)` | Hard Constraints 下で score_d を最大化するスコープを選択 |

### 4.2 `dependency_completeness` の定義

```
used    = {v | v ∈ abstract_ids(diff_nodes)}
defined = {v | v ∈ abstract_ids(scope_nodes \ diff_nodes)}

dependency_completeness = |used ∩ defined| / |used|
                          （|used| = 0 の場合は 1.0）
```

- `used`：diff部分が参照する抽象識別子（= diff が「外」に依存しているもの）
- `defined`：scope 内の context 部分（diff 以外）に出現する抽象識別子
  - 厳密な「宣言文かどうか」の AST 解析は行わない（簡易実装）
  - context 部分に出現する = そのスコープが識別子の文脈を提供している，と解釈

**用語の対応**（ドキュメント `granularity_final_direction_semantic_closure.md` との対応）:

- `used_identifiers(diff)` → `used`
- `defined_identifiers(scope)` → `defined`
- 「定義」の判断：scope 内の diff 以外の部分への出現で代用（簡易版）

### 4.3 出力先

`outputs/pattern/granularity_semantic_closure.json`  
（`granularity_analysis.py` の `granularity_scoring_comparison.json` と分離）

出力の追加フィールド（候補ごと）:

| フィールド | 説明 |
|---|---|
| `contains_all_diff` | scope が diff の全ノードを包含するか（bool） |
| `dep_comp` | dependency_completeness の値 |
| `score_d` | diff_ratio × dep_comp |

---

## 5. 全14IDの結果

`str_R` は全スコープ・全IDで別途確認が必要なため，下表は `dep_comp`・`scr`・`score_d` のみ記載．

### 5.1 各ID・スコープ別の指標

| ID | スコープ | n | diff_ratio | dep_comp | scr | score_d |
|---|---|---:|---:|---:|---:|---:|
| **222** | DIFF | 38 | 1.000 | 0.000 | 0.333 | 0.000 |
| | BROTHER | 86 | 0.442 | 0.667 | 1.000 | **0.295** |
| | EXCL | 38 | 1.000 | 0.000 | 0.333 | 0.000 |
| | INCL | 87 | 0.437 | 0.667 | 1.000 | 0.291 |
| **609** | DIFF | 44 | 1.000 | 0.000 | 0.500 | 0.000 |
| | BROTHER | 46 | 0.957 | 0.000 | 0.500 | 0.000 |
| | EXCL | 49 | 0.898 | 0.000 | 0.500 | 0.000 |
| | INCL | 127 | 0.346 | 0.500 | 1.000 | **0.173** |
| **791** | DIFF | 29 | 1.000 | 0.000 | 0.667 | 0.000 |
| | BROTHER | 49 | 0.592 | 0.250 | 1.000 | 0.148 |
| | EXCL | 48 | 0.604 | 0.250 | 1.000 | **0.151** |
| | INCL | 50 | 0.580 | 0.250 | 1.000 | 0.145 |
| **902** | DIFF | 28 | 1.000 | 0.000 | 0.667 | 0.000 |
| | BROTHER | 70 | 0.400 | 0.250 | 1.000 | **0.100** |
| | EXCL | 28 | 1.000 | 0.000 | 0.667 | 0.000 |
| | INCL | 71 | 0.394 | 0.250 | 1.000 | 0.099 |
| **1206** | DIFF | 6 | 1.000 | 0.000 | 0.000 | 0.000 |
| | BROTHER | 8 | 0.750 | 1.000 | 0.000 | **0.750** |
| | EXCL | 52 | 0.115 | 1.000 | 0.000 | 0.115 |
| | INCL | 59 | 0.102 | 1.000 | 0.250 | 0.102 |
| **1306** | DIFF | 6 | 1.000 | 1.000 | 1.000 | **1.000** |
| | BROTHER | 8 | 0.750 | 1.000 | 0.000 | 0.750 |
| **1691** | DIFF | 39 | 1.000 | 0.000 | 0.750 | 0.000 |
| | BROTHER | 41 | 0.951 | 0.000 | 0.750 | 0.000 |
| | EXCL | 44 | 0.886 | 0.000 | 0.750 | 0.000 |
| | INCL | 52 | 0.750 | 0.250 | 0.800 | **0.188** |
| **2512** | DIFF–INCL | — | — | **0.000** | — | **0.000** |
| **2919** | DIFF–INCL | — | — | **0.000** | — | **0.000** |
| **6182** | DIFF | 2 | 1.000 | 1.000 | 1.000 | **1.000** |
| **8126** | DIFF | 27 | 1.000 | 0.000 | 0.000 | 0.000 |
| | INCL | 52 | 0.519 | 1.000 | 0.500 | **0.519** |
| **14412** | DIFF | 11 | 1.000 | 0.000 | 0.000 | 0.000 |
| | INCL | 36 | 0.306 | 1.000 | 0.500 | **0.306** |
| **21294** | DIFF | 25 | 1.000 | 1.000 | 1.000 | **1.000** |
| **23864** | DIFF | 3 | 1.000 | 1.000 | 1.000 | **1.000** |

太字は各IDでの score_d 最大値を示す．

### 5.2 select_scope_d の選択結果まとめ

| ID | 選択スコープ | score_d | 備考 |
|---|---|---:|---|
| 222 | BROTHER | 0.295 | EXCL が DIFF と同一のため BROTHER が最小で閉じる |
| 609 | INCL | 0.173 | BROTHER/EXCL では dep=0 のまま |
| 791 | EXCL | 0.151 | BROTHER と差小（0.003）|
| 902 | BROTHER | 0.100 | EXCL が DIFF と同一のため BROTHER が最小 |
| 1206 | BROTHER | 0.750 | BROTHER で dep=1.0，それ以上は diff_ratio が低下 |
| 1306 | DIFF | 1.000 | DIFF 段階で既に完全閉包 |
| 1691 | INCL | 0.188 | DIFF〜EXCL で dep=0，INCL で初めて dep>0 |
| 2512 | — | 0.000 | 全スコープで dep=0（FUNCTION_1 の宣言が scope 外） |
| 2919 | — | 0.000 | 同上（FUNCTION_1 のパターン） |
| 6182 | DIFF | 1.000 | DIFF 段階で完全閉包 |
| 8126 | INCL | 0.519 | DIFF〜EXCL で dep=0，INCL で dep=1.0 |
| 14412 | INCL | 0.306 | 同上 |
| 21294 | DIFF | 1.000 | DIFF 段階で完全閉包 |
| 23864 | DIFF | 1.000 | DIFF 段階で完全閉包 |

---

## 6. 検討内容

### 6.1 dep_comp と scr（scope_closure_ratio）の乖離

セッション中に `scope_closure_ratio` を別途計算し，`dep_comp` との乖離を確認した．

**scope_closure_ratio の定義**:
```
targets = {v ∈ scope_ids | full_tree での v の出現回数 > 1}
closed  = {v ∈ targets | v の全出現インデックスが scope_indices に含まれる}
scr     = |closed| / |targets|
```

すなわち「scope 内で利用されている識別子のうち，before コード全体で複数回登場し，かつその全出現が scope 内に収まっているものの割合」．

**2指標の意味の違い**:

| 指標 | 問い | 視点 |
|---|---|---|
| dep_comp | diff が参照する識別子を，scope の context 部分が説明できるか | diff → context（内向き） |
| scr | scope 内の識別子が scope の外に漏れていないか | scope → コード全体（外向き） |

**乖離事例（ID=1206）**:

- `dep_comp = 1.0`（BROTHER）: diff の `VAR_5` が BROTHER の context に出現 → diffの処理は説明できる
- `scr = 0.0`（BROTHER）: `VAR_5` の出現が BROTHER の外（for ループ側）にもあるため全出現が scope に収まらない

「diffを読んで意味が分かるか」と「scopeの外に識別子が漏れていないか」は別の問いである．

**ID=6182 でのスコープ拡張による scr 低下**:

- DIFF で scr=1.0 → BROTHER に拡張すると scr=0.0
- BROTHER に追加されたノードが持つ識別子の全出現が scope 外に及ぶため，拡張するほど scr が下がるケースがある

### 6.2 score_d=0 になる構造的限界ケース（ID=2512, 2919）

どのスコープに拡張しても dep_comp=0.0 のまま：

```js
var FUNCTION_1 = function () {};   // ← for ループの外で宣言
for (var VAR_2 = 0; VAR_2 < 10000; VAR_2++) {
  VAR_1 = Object.prototype.toString.call(FUNCTION_1) === "[object Function]";
  //                                    ↑ DIFF（FUNCTION_1 を参照）
}
```

DIFF〜INCL のいずれも `var FUNCTION_1 = ...` の宣言を含まない（for ループ外にあるため）．  
この場合 `select_scope_d` は `str_R=1 ∧ contains_all_diff` を満たす候補から  
score_d が全て 0 のまま選択することになる（タイブレークは diff_ratio 最大 = DIFF）．

**示唆**: 「スコープ境界より外側の識別子に依存する diff」は，  
ASTの近接性による拡張では意味的閉包に届かないという構造的限界がある．

### 6.3 dep_comp が 1.0 に届かないケース（ID=222, 791, 902）

VAR_4 のような for-in / for 文のループ変数は，ループ本体の中だけに出現し  
ループ外（context 部分）には宣言が存在しないため，dep_comp が 1.0 に達しない：

```js
for (var VAR_4 in VAR_1) {   // VAR_4 は DIFF 内にしか出現しない
  ...
}
```

この場合，`defined` に VAR_4 が入らないため used と defined の交差に含まれない．  
解釈としては「ループ変数は diff 内で自己完結している」ため意味的には問題ないが，  
現実装では dep_comp の分母に計上されてしまう．

**検討方向**: ループ変数（`for`/`for-in` の初期化子として宣言された識別子）を  
`used` から除外するか，別扱いにすることで 1.0 に近づく可能性がある．

### 6.4 `dep_comp` の「定義」の簡易性について

現実装では「context 部分への出現 = 定義」と扱っている．  
より厳密には `variable_declarator` の左辺や関数宣言の引数として出現するノードのみを  
「定義」と判断すべきだが，`parent` チェーンを辿る実装コストと対して得られる精度向上は未検証．

---

## 7. 今後の検討事項

| 課題 | 内容 |
|---|---|
| ループ変数の除外 | `for`/`for-in` の宣言識別子を `used` から除外して dep_comp の精度を上げる |
| `dep_comp` の「定義」の厳密化 | `variable_declarator` 左辺・関数引数への出現のみを `defined` に計上 |
| `scope_closure_ratio` の活用 | dep_comp と scr を組み合わせた複合スコアの検討 |
| 2512/2919 への対処 | score_d=0 のケースへのフォールバック戦略（例: str_R=1 かつ diff_ratio 最大） |
| granularity_comparison.py への scr 追加 | `scope_closure_ratio` を計算・記録する実装の追加 |

---

## 8. 関連ファイル

| パス | 役割 |
|---|---|
| `experiments/pattern/granularity_comparison.py` | 本実装（4手法比較のメインスクリプト）|
| `experiments/pattern/granularity_analysis.py` | 前段実装（3手法比較，共通関数の提供元）|
| `docs/granularity_final_direction_semantic_closure.md` | semantic closure 手法の設計方針文書 |
| `docs/2026-0508-discussion.md` | granularity_analysis.py の実装・議論まとめ |
| `docs/2026-0508-score-formula-analysis.md` | score_nab の問題分析・score_c の提案 |
| `outputs/pattern/granularity_semantic_closure.json` | 実行結果の出力先 |
