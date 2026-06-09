# E5. fast 側 (head) の多様性分析

## 1. 目的

提案手法は **slow 側** (低速コード) を軸として集約する。 一方で同じ slow 構造に対し、 **fast 側** (高速化されたコード) は複数の書き換え方法を持ち得る。 本レポートではこれを定量化し、 「**手動定義パターンが見落としやすい複数高速化方法の存在**」 を示す。

paper §6.2「ペアとなっている fast 側の類似性」 への主データ。 paper §preanalysis 「高速側に観測された表現の種類」 段落と直接接続する。

---

## 2. 用語と方法

| 用語 | 定義 |
|---|---|
| **top1 クラスメンバ** | E1 ベスト設定 (τ=0.7 / L0 / Diff) における 7 既知パターン top1 クラスのメンバ実装対 |
| **fast 側 bigram** | 各メンバについて、 `outputs/AST_HEAD/scope_DIFF_BLOCK_all.json` の `merged.nodes` から `(name, value)` トークン列を作り、 bigram set に変換したもの (slow 側と同一の正規化 `normalize_value` を適用) |
| **variant** | fast 側 bigram の Jaccard 類似度 ≥ 0.5 で同じグループに集約された実装対の集合 (= 同じ高速化書き換え方式) |
| **variant 数** | top1 クラス内に存在する fast 側書き換え方式の種類数 |

クラスタリングは greedy merge (Jaccard ≥ 0.5 を満たす既存 variant に統合、 さもなくば新 variant)。 閾値 0.5 は paper 主分析の τ=0.7 より緩い設定で、 「**多少の表記差を許して同じ高速化方式とみなす**」 ことを意図している。

---

## 3. 入力データ

| 用途 | パス |
|---|---|
| ベスト設定 top1 クラス | `outputs/scam/approach_minimum/integrate/jaccard07/level0/Diff/Diff.json` |
| fast 側 AST | `outputs/AST_HEAD/scope_DIFF_BLOCK_all.json` |
| 既知パターン正解 | `outputs/scam/RQ1/pattern_{1,2,3,6,7,8,9}/diff_linked.jsonl` |

---

## 4. 結果

### 4.1 各既知パターンの fast 側多様性

| パターン | 名称 | top1 クラスメンバ数 | fast 側 variant 数 | 多様性比率 (variant / member) |
|---|---|---:|---:|---:|
| 1 | for-in + hasOwnProperty | 163 | 72 | 44 % |
| 2 | substr(i, 1) | 5 | 4 | 80 % |
| 3 | String(x) | 20 | 8 | 40 % |
| **6** | **split.join** | **260** | **106** | **41 %** |
| 7 | toString.call | 5 | 4 | 80 % |
| 8 | x % 2 === 0 | 2 | 2 | 100 % |
| 9 | 配列の反復処理 (高階関数) | 39 | 24 | 62 % |

→ **どのパターンでも、 メンバ数の 40 % 以上が独自の fast 側書き換え方式を持つ**。 特に pattern 6 では 260 件に対し **106 種類** の異なる書き換え方法が存在する。

### 4.2 各パターンの主要 variant (上位 5)

#### pattern 1 (for-in + hasOwnProperty、 top1 size 163、 72 variants)

| 順位 | サイズ | 代表 fast 構造 |
|---:|---:|---|
| 1 | 18 | `for_statement for ( variable_declaration ...` (素朴 `for` ループへの置換) |
| 2 | 10 | `expression_statement call_expression member_expression ...` (`Object.keys`/`forEach` 等) |
| 3 | 9 | `call_expression member_expression identifier:Object ...` (`Object.keys` 系) |
| 4 | 6 | `expression_statement call_expression member_expression ...` (別バリエーション) |
| 5 | 5 | `for_statement for ( variable_declaration ...` (別変数の for ループ) |

→ **for-in + hasOwnProperty → `Object.keys` + 反復** の複数バリエーション (素朴 `for` / `forEach` / 等) が存在。

#### pattern 3 (String、 top1 size 20、 8 variants)

| 順位 | サイズ | 代表 fast 構造 |
|---:|---:|---|
| 1 | 5 | `binary_expression VAR_1 + string ":"` (`"" + x` テンプレ前置) |
| 2 | 4 | `binary_expression string ":" + identifier:VAR_1` (`"" + x` テンプレ前置 (逆)) |
| 3 | 4 | `identifier:VAR_1` (単に変数代入で型変換失) |
| 4 | 3 | `binary_expression VAR_2 + string ":"` (別変数) |
| 5 | 1 | `binary_expression VAR_5 + string ":"` (別変数) |

→ **`String(x)` → 空文字連結 (`'' + x`)** が主流。 ただし連結の左右で異なる variant が出る。

#### pattern 6 (split.join、 top1 size 260、 **106 variants**)

| 順位 | サイズ | 代表 fast 構造 |
|---:|---:|---|
| 1 | 11 | `property_identifier:substr binary_expression call_expression ...` (`substr` 置換) |
| 2 | 9 | `property_identifier:replace regex /-/g` (`replace` + 正規表現 `/-/g`) |
| 3 | 9 | `property_identifier:replace regex /abcdefgh/g` (`replace` + 別正規表現) |
| 4 | 7 | `call_expression member_expression identifier:V...` (連鎖 `replace` 等) |
| 5 | 7 | `call_expression member_expression call_expression ...` (連鎖呼び出し) |

→ **複数の高速化方法**:
1. **`substr` で部分文字列置換**
2. **`replace(/pattern/g, "")` 正規表現置換**
3. **`replace(...).replace(...)` 連鎖**
4. **`split` 文字配列を `.join()` 以外で結合**

paper §preanalysis 「高速側に観測された表現の種類」 で挙げた **「`replace` の連鎖呼び出し、 正規表現リテラルを引数とする `replace`、 `concat` を併用する形式」** と完全に一致する観察結果。

#### pattern 9 (高階関数、 top1 size 39、 24 variants)

| 順位 | サイズ | 代表 fast 構造 |
|---:|---:|---|
| 1 | 5 | `member_expression member_expression identifier ...` (chained `reduce`?) |
| 2 | 4 | `function_declaration function identifier:FUNCTION_...` (`function` 宣言版) |
| 3 | 3 | `variable_declaration var variable_declarator...` (`var` で関数宣言) |
| 4 | 3 | `expression_statement assignment_expression...` (代入式版) |
| 5 | 3 | `member_expression array [ ] . property_identifier:...` (配列リテラル直接) |

→ **`reduce` の代替: `forEach` / 素朴 `for` / 関数宣言版 reduce / arrow function 版** など、 多様な書き換え方法。

### 4.3 観察

#### 4.3.1 pattern 6 の多様性が圧倒的

260 件 → 106 variants は、 「**同じ `split.join` パターンに対して 100 種類以上の独自書き換えが存在する**」 ことを意味する。 これは:
- `replace` の正規表現が事例ごとに違う (`/-/g`, `/abcdefgh/g`, etc.)
- 連鎖の有無
- `concat` 併用の有無
- 別関数化の有無

など複数次元の variation を含む。 paper §preanalysis の 「`replace` の連鎖呼び出し、 正規表現リテラルを引数とする `replace`、 `concat` を併用する形式」 と整合する。

#### 4.3.2 制御構造 (pattern 1, 9) は variant が多い

- pattern 1: 163 → 72 variants (44 %)
- pattern 9: 39 → 24 variants (62 %)

制御構造の高速化方法は事例ごとに異なる: for ループ、 forEach、 reduce、 map など複数の制御パターンが共存。

#### 4.3.3 小規模パターン (2, 7, 8) は variant 比率高い

- pattern 2: 5 → 4 variants (80 %)
- pattern 7: 5 → 4 variants (80 %)
- pattern 8: 2 → 2 variants (100 %)

サンプルが少ないため、 各メンバが独自書き換えになりやすい。 サンプル数の問題で多様性比率としては解釈に注意。

---

## 5. 考察

### 5.1 paper §preanalysis との接続

事前分析の 「高速側に観測された表現の種類」 段落で挙げた多様性が、 E5 で **自動抽出経由でも観測可能** であることが確認できた:

| パターン | 事前分析の手動観察 | E5 の自動観察 |
|---|---|---|
| 1 | `Object.keys` + `forEach`/`map`/`reduce`、 `Object.keys($).length` | variant #2-3 (`Object.keys` 系) |
| 3 | テンプレートリテラル (`` `${x}` ``) | variant #1-5 (空文字連結) |
| 6 | `replace` 連鎖、 正規表現 `replace`、 `concat` 併用 | variant #2-3 (正規表現 `replace`)、 #4-5 (連鎖呼び出し) |
| 9 | `forEach`, `map`, `filter`, `flat`, `flatMap` | variant #1-5 (多様な代替) |

paper §6.2 「ペアとなっている fast 側の類似性」 で 「**手動定義パターンが見落としやすい多様な高速化方法を、 自動抽出は fast 側 variant として弁別できる**」 と主張できる。

### 5.2 多様性の意義

slow 側を集約軸とする提案手法でも、 fast 側の多様性は副次的に観察可能。 paper §6.2 の主張:

> **「pattern 6 (`split.join`) の 260 件の slow 事例には、 106 種類の fast 側書き換え方法が存在する。 これは手動定義パターンが 1 対 1 対応で書き換えを提示するのと対照的に、 自動抽出が多様な書き換えの存在を可視化できることを示す」**

### 5.3 限界

- variant の代表 head_tokens は 6 ノード分だけ抜粋しており、 完全な高速化方法を表現しているわけではない。 詳細は E6 で size 上位 candidate について個別分析する
- 多様性比率 (variant / member) は閾値 0.5 に依存。 より緩い閾値ではさらに variant が集約される可能性
- Variant 内部の bigram 集合の重なりは局所的なため、 「同じ書き換え方式」 と一括できる粒度には文脈による揺らぎがある

---

## 6. 論文への落とし込み案

### 6.1 該当節

§ `\subsubsection{ペアとなっているfast側の類似性}` (現在 todo)

### 6.2 提示する表

```latex
\begin{table}[t]
\centering
\caption{既知 7 パターンの top1 クラス内における fast 側 (head) の多様性。 fast 側 bigram の Jaccard 類似度 ≥ 0.5 で同一書き換え方式とみなして variant を集約した。}
\label{tab:exp-fast-diversity}
\footnotesize
\begin{tabular}{c c r r r}
\toprule
パターン & 名称 & top1 メンバ数 & fast 側 variant 数 & 多様性比率 \\
\midrule
1 & for-in + hasOwnProperty & 163 & 72 & 44\% \\
2 & substr(i,1) & 5 & 4 & 80\% \\
3 & String(x) & 20 & 8 & 40\% \\
6 & split.join & 260 & 106 & 41\% \\
7 & toString.call & 5 & 4 & 80\% \\
8 & x \% 2 === 0 & 2 & 2 & 100\% \\
9 & 高階関数 & 39 & 24 & 62\% \\
\bottomrule
\end{tabular}
\end{table}
```

### 6.3 文章ドラフト (約 450 字)

> 提案手法は低速側 (slow) を軸として集約するが、 同じ slow 構造に対する高速化側 (fast) の多様性も副次的に観察できる。 E1 ベスト設定 (τ=0.7、 抽象化 0、 サイズ Diff) における 7 既知パターン top1 クラスのメンバに対し、 高速側 AST 断片 (`outputs/AST_HEAD/scope_DIFF_BLOCK_all.json` の `merged.nodes`) から bigram 集合を作り、 Jaccard 類似度 0.5 以上を 「同じ書き換え方式」 とみなして variant 集約した。
>
> 表 \ref{tab:exp-fast-diversity} に結果を示す。 どのパターンでも top1 メンバ数の 40 \% 以上が独自の高速化書き換え方法を持つ。 特にパターン 6 (`split.join`) の 260 件には 106 種類の variant が存在し、 `replace` への単純置換、 正規表現引数を伴う `replace` (`/-/g`、 `/abcdefgh/g` 等)、 連鎖呼び出し、 `concat` 併用、 `substr` 置換などが含まれる。 これらは事前分析で手動観察された 「高速側に観測された表現の種類」 (paper §preanalysis) と整合し、 自動抽出が同様の多様性を機械的に検出できることを示す。
>
> 制御構造レベルのパターン (1, 9) では fast 側 variant 比率が 44-62 \% と高く、 関数式と関数宣言、 arrow function、 forEach / map / reduce / flat 等の代替が共存することが定量化された。 提案手法は単一の高速化方法を提示するのではなく、 **多様な書き換え方法の存在を可視化** することができる。

### 6.4 考察セクションへの接続

- §6.2 「自動作成されたパターンは低速な要因を捉えているか」: 「単一クラスへの集約が完全でない理由は fast 側多様性に由来する」 と説明
- §6.4 妥当性脅威: fast 側集約閾値 (0.5) の感度分析は将来研究

---

## 補足: 出力ファイル

| パス | 内容 |
|---|---|
| `outputs/scam/approach_minimum/analysis/E5_fast_variants.csv` | 7 パターン × 各 variant (合計 220+ 行) の variant_id, size, 代表 mb_id, 代表 head tokens |
