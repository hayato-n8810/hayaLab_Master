# 概要

JavaScriptマイクロベンチマーク（before→after実装対）を対象に，GumTree によるAST差分を起点として slow コード断片の特徴を機械的に抽出しパターン化するパイプラインを検討している．

**基本方針**：従来研究で示す slow コードパターンに対応するマイクロベンチマークから，先行研究パターンのコードを直接参照せず機械的に辿り着くこと

1. **粒度選択**：GumTree 差分を起点に「意味ある処理断片」を機械的に切り出す
2. **パターン集約**：切り出した断片の類似度を測り，クラスタリングで集約する

---

# 相談事項

- 手法の妥当性評価をどうするか・定量評価できるか
- ハイパーパラメータなど，人力で設定する値はどれだけ許される？（チェリーピックにならない？）
- 検出に至るまでのロードマップが見えなくなってきた
- ~~次何しようか．論文書く．．．？~~

---

## 1. 粒度選択

### 1.1 前提と方針

前提：**slow 側の差分要素は全て slow である特徴を含む**

方針：差分を含む最小の「処理内容と差分箇所が理解できる断片」をスコープとして機械的に選ぶ．

ここでの「処理内容と差分箇所が理解できる断片」とは，(1) ソースコード上に実際に存在する連続したトークン列として成立しており，(2) 差分ノードを全て包含する粒度のコード片を指す．

### 1.2 候補スコープの設計

差分ノードを起点に，包含関係 `merged_diff ⊆ merged_brother ⊆ merged_excl ⊆ merged_incl` を持つ4段階の候補スコープを定義する．

| スコープ名 | 内容 |
|---|---|
| `merged_diff` | GumTree差分ノードとその子孫のmerged集合 |
| `merged_brother` | 差分ノードの直接親の全子孫のmerged集合 |
| `merged_exclude_block` | スコープ境界ノード配下の兄弟+差分部分木（境界自身を除く）|
| `merged_include_block` | スコープ境界ノード配下の全子孫（境界自身を含む）|

包含関係: **DIFF ⊆ BROTHER_DIFF ⊆ BLOCK_EXCLUDE_PARENT ⊆ BLOCK_INCLUDE**

兄弟：AST上の親ノードが同じ

子孫：そのノードを親として含む全ノード

差分アクションが複数ある場合はアクションごとに切り出したうえで全アクション分をまとめたスコープを生成する．

### 1.3 スコープ切り出し（`scope_to_base.py`）

全29,809件の実装対について，GumTree が検出した差分アクションを起点に4種類のノード集合を切り出す．

- **diff**：差分ノードとその配下の全ノードを収集する
- **brother**：差分ノードを持つ直接親の全直接子孫を収集する
- **excl**：差分ノードを内包する最近傍の制御構造ブロックの直接子孫を，境界ノード自身を除いて収集する
- **incl**：同ブロックの直接子孫を境界ノード自身を含めて収集する

excl・incl で「最近傍の制御構造ブロック」を特定するため，境界とみなすノード型を以下のように定める．


<details>
<summary>スコープ境界ノード</summary>

```json

# スコープ境界とみなすノード名の集合
SCOPE_BOUNDARY: set[str] = {
    "program",  # トップレベルの全文（変数宣言・関数定義・式文など）
    # "statement_block",              # 粒度が大きい（他ノードを含有しすぎる）ので除外
    # ── ブロックレス可 制御構文 ─────────────────────────────
    "else_clause",  # else節の本体（statement_blockまたは単文）
    "if_statement",  # 条件部（parenthesized_expression）と then/else 本体
    "while_statement",  # 条件部（parenthesized_expression）とループ本体
    "do_statement",  # ループ本体と後置条件部（parenthesized_expression）
    "with_statement",  # with対象オブジェクトと本体
    "labeled_statement",  # ラベル付き文の本体
    "for_in_statement",  # ループ変数・イテラブル・本体（for-in / for-of）
    # ── switch ────────────────────────────────────────────
    "switch_case",  # case値（string/number）と各 case 節内の文群
    "switch_default",  # default 節内の文群
    "switch_body",  # switch全体のcase/default節リスト（{ }を含む）
    # ── for文（ヘッダー部と本体の両方を含む） ─────────────────
    "for_statement",  # 初期化・条件・更新（ヘッダー）とループ本体
    # ── 関数（アロー・式形式含む） ────────────────────────────
    "function",  # 関数宣言・関数式の引数リストと本体（statement_block）
    "arrow_function",  # 引数リスト・=>・本体（statement_blockまたは式）
    "function_declaration",  # 関数名・引数リスト・本体（statement_block）
    "function_expression",  # 無名/名前付き関数式の引数リスト・本体
    "generator_function_declaration",  # ジェネレータ関数名・*・引数リスト・本体
    "generator_function",  # ジェネレータ関数式の引数リスト・本体
    # ── 例外処理 ──────────────────────────────────────────
    "try_statement",  # try本体・catch節・finally節の全体
    "finally_clause",  # finally節の本体（statement_block）
    # ── クラス ────────────────────────────────────────────
    "class_body",  # クラス内のメソッド定義・フィールド定義の列
    "method_definition",  # メソッド名・引数リスト・本体（statement_block）
    "class_static_block",  # static { } ブロック内の文群
}

```

</details>

---

### 1.4 前処理（フィルタリング・重複除去）

スコアリング前に以下の前処理を適用する．

**記号・キーワードのみ候補の除去**

差分がカッコや演算子のみで構成されている場合，後述の照合が成立しないため除外する．以下を全て除いても有意な終端トークンが残らない候補を取り除く：

- `string_fragment`, `escape_sequence`, `number` に分類されるノード
- `VAR_*`, `FUNCTION_*`, `KEY_*` の抽象化変数
- 汎用記号・宣言キーワード（`(`, `)`, `,`, `;`, `{`, `}`, `var`, `let`, `const` 等）

**重複除去**

ノードの集合が完全一致する候補を統一する．包含の小さい順に処理することで，重複時は小さいスコープを残す．

### 1.5 スコアリングと選択

各実装対について，4種のスコープ候補を包含順（diff → brother → excl → incl）に並べ，前処理を経た後に以下の手順で最適な1つを選ぶ．

**照合確認**

スコープ内の全終端トークン値を空白相当の正規表現で連結し，元のソースコードに対してマッチするかを確認する．元コード上に処理断片として成立しない候補はこの時点で選択対象から外す．

**スコアリング**

照合を通過した候補に対して以下のスコアを計算し，最大値の候補を選択する．

```
diff_ratio           = |diff_nodes| / |scope_nodes|
sibling_completeness = diff直接親ごとに（scope に含まれる直接子 / 全直接子）を計算した平均
score                = 2 × diff_ratio × sibling_completeness
                       ─────────────────────────────────────
                           diff_ratio + sibling_completeness
```

`diff_ratio` は差分が密な小さいスコープを，`sibling_completeness` は差分周辺の兄弟ノードを揃えた大きいスコープをそれぞれ好む相反する圧力を持つ．調和平均により，両者がともに高い中間スコープが最大スコアを得る．

---

## 2. パターン集約

### 2.1 設計方針

粒度選択で決定したスコープ内の AST ノード集合を入力に，コード片間の距離を定義して階層クラスタリングで集約する．目的は，同一の slow パターンに対応する実装対を同一クラスタにまとめることである．

### 2.2 検討したアルゴリズム

コードクローン検出の既存手法5種と独自提案手法2種を比較した．

| アルゴリズム | 実装ファイル | 距離定義 | 特徴 |
|---|---|---|---|
| NiCad | `algo_nicad.py` | トークン列 Levenshtein 比率距離 | 順序保持・記号除去・識別子抽象化 |
| Deckard | `algo_deckard.py` | ノード型ヒストグラム Cosine 距離 | 順序非依存・型分布を表現 |
| SourcererCC | `algo_sourcerercc.py` | multiset Jaccard 距離 | 順序非依存・包含関係に寛容 |
| APTED | `algo_apted.py` | 厳密 Tree Edit Distance（最大サイズ正規化） | 木構造の違いを最も忠実に距離化 |
| path_context | `algo_path_context.py` | leaf-leaf パスの bag-of-paths Jaccard | 構造的近傍関係を反映 |
| 提案手法 1 | `algo_proposed.py` | 多特徴重み付き和（struct/method/keyword/literal） | 各軸の特性を混合 |
| 提案手法 2 | `algo_abstraction_hierarchy.py` | 抽象化レベル階層による距離 | 段階的な抽象化で等価判定 |

### 2.3 各アルゴリズムの詳細

#### 提案手法 1（多特徴重み付き和）

4軸の重み付き和として距離を定義する：

```
d(i,j) = 0.45 × d_struct + 0.30 × d_method + 0.15 × d_keyword + 0.10 × d_literal
```

- `d_struct`：正規化トークン列の Levenshtein 比率距離（NiCad と同形だが正規化粒度が異なる）
- `d_method`：`property_identifier` や組み込み識別子名の集合 Jaccard 距離
- `d_keyword`：JS キーワード（`for`/`while`/`return` 等）の集合 Jaccard 距離
- `d_literal`：数値・文字列リテラルの集合 Jaccard 距離

#### 提案手法 2（抽象化レベル階層）

段階的な抽象化レベル（L0〜L5）で類似度を測る：

| Level | 識別子タグ | リテラル | API/組み込み | 構造ノード名 | 相当クローン型 |
|---|---|---|---|---|---|
| L0 | `<VAR>/<FUNC>/<KEY>` | 値そのまま | 値そのまま | 名前そのまま | Type-1 |
| L1 | same | `<LIT>` | 値そのまま | 名前そのまま | Type-2 (lit-only) |
| L2 | `<TERM>` | `<TERM>` | 値そのまま | 名前そのまま | Type-2 (lit+id) |
| L3 | same | same | `<API>` | 名前そのまま | Type-3 (API抽象) |
| L4 | same | same | same | 正規化グループ名 | Type-3 (構造同型) |
| L5 | same | same | `<API>` | `<STRUCT>` | Type-4 (骨格のみ) |

距離計算にはコサイン類似度・Jaccard 距離などを閾値の設定も含めて複数検討した．

<details>
<summary>既存手法の詳細（NiCad / Deckard / SourcererCC / APTED / path_context）</summary>

#### NiCad（Levenshtein 比率距離）

Roy & Cordy (ICPC 2008) の手法に基づく．正規化されたトークン列を直列化して Levenshtein 距離で比較することで，順序を保持したまま差分を距離に変換する．

- 強み：トークンの並び順の違い（`a[i] = b[i]` vs `b[i] = a[i]`）を捕捉できる
- 弱み：包含関係（902⊂791，片方が片方のサブセット）では挿入コスト分の距離が出やすい
- 適した検出ケース：「1〜2トークンだけ違う」Type-2 クローン

#### Deckard（ノード型ヒストグラム + Cosine）

Jiang+ (ICSE 2007) の手法に基づく．各スコープを「ノード型の出現回数ベクトル」に潰してコサイン距離で比較する．

- 強み：`1206` vs `1306`（リテラル値だけ違い，構造が同一）で距離がほぼ 0 になる
- 弱み：順序情報を完全に捨てるため，同じノードの並び替えが区別できない
- 適した検出ケース：構造が同一でリテラルだけ異なる Type-2 クローン

#### SourcererCC（multiset Jaccard）

Sajnani+ (ICSE 2016) の手法に基づく．トークンを multiset として Jaccard 類似度を計算する．

- 強み：包含関係（`902 ⊂ 791`）に最も寛容（片方が他方を完全に含む場合 Jaccard = `|A|/|B|`）
- 弱み：出現順序の違いを区別しない
- 適した検出ケース：部分的に重複するコードフラグメントのクローン検出

#### APTED（厳密 Tree Edit Distance）

Pawlik & Augsten (VLDB 2015) による最適 TED アルゴリズム．木の挿入・削除・置換コストの最小和を計算し，最大サイズで正規化する．

- 強み：構造の違いを最も忠実に距離化する；全手法中「構造上の真の近さ」に最も近い
- 弱み：意味的に等価でも構造が異なる（`split().join()` vs `replaceAll()`）場合に距離が出る
- 計算量：O(n³) だが N=14, n≤49 程度なら問題なし

#### path_context（leaf-leaf パスの bag-of-paths Jaccard）

code2vec (Alon+ POPL 2019) の path-context 表現に基づく．2終端ノード間の最短木パスを文字列化して bag-of-paths を構成し，Jaccard 距離を計算する．

- 強み：「ループの中で呼ばれた reduce」vs「関数引数での reduce」といった構造的文脈を区別できる
- 弱み：全終端ペアを列挙するため特徴空間が n² オーダーになり，スコープが大きいほど不安定になりやすい
- 実装上の工夫：`MAX_LEAF_PAIRS=800` で等間隔サブサンプリングし決定的に制限

</details>

### 2.4 結果と考察

#### 評価設定

目視によって以下の理想ラベル（6クラスタ）を定義し，各アルゴリズムの k=6 クラスタリングとの一致度を Adjusted Rand Index（ARI）で測定した．

| クラスタ | ID | 共通パターン |
|---|---|---|
| A | 222 | for-in ループ |
| B | 609, 791, 902, 1691 | reduce（arrow / function 式） |
| C | 1206, 1306 | String() リテラル変換 |
| D | 2512, 2919 | toString.call による型判定 |
| E | 6182, 14412, 21294, 23864 | 文字列操作（substr / join 等） |
| F | 8126 | split + join によるトークン置換 |

評価は正規化バリアント（none / supertype / custom）× アルゴリズムの全組み合わせで実施した．

#### k=6 固定での ARI（上位6件）

| アルゴリズム / バリアント | ARI | A | B | C | D | E | F |
|---|---|---|---|---|---|---|---|
| **nicad / none** | **0.609** | 1.00 | 1.00 | 0.67 | 0.67 | 0.50 | 0.33 |
| **nicad / custom** | **0.609** | 1.00 | 1.00 | 0.67 | 0.67 | 0.50 | 0.33 |
| sourcerercc / custom | 0.552 | 0.50 | 1.00 | 0.67 | 1.00 | 0.25 | 0.50 |
| deckard / none | 0.549 | 1.00 | 0.80 | 1.00 | 0.67 | 0.50 | 0.33 |
| proposed / none | 0.442 | 1.00 | 0.75 | 0.40 | 0.67 | 0.50 | 0.33 |
| apted / none | 0.306 | 1.00 | 0.50 | 0.67 | 0.67 | 0.50 | 0.33 |

k=6 固定では **NiCad（正規化なし / custom）** が最高 ARI=0.609 で，クラスタ B（reduce 系）を完全に一致させることができた．提案手法1は k=6 では 0.442 で中位に留まった．

#### k 自由（k=2〜9 のうち最大 ARI）

| アルゴリズム / バリアント | 最適 k | 最大 ARI |
|---|---|---|
| proposed（全バリアント） | k=8 | 0.693 |
| sourcerercc（全バリアント） | k=9 | 0.693 |
| path_context（全バリアント） | k=9 | 0.693 |
| nicad / none, custom | k=6 | 0.609 |
| deckard / none | k=6 | 0.549 |

k を自由に選ぶと proposed / sourcerercc / path_context が並んで最高 ARI=0.693 に達するが，k=8〜9 を必要としており，クラスタ数が理想（6）より多い．

#### 既知同族ペアの距離

事前に類似が期待される3ペアについて，各アルゴリズムの結合高さ（値が小さいほど早く同じクラスタに統合される）を確認した：

| ペア | 共通特徴 | 最低結合高さ（手法） |
|---|---|---|
| 791 vs 902 | reduce 系（包含関係 902⊂791） | 0.025（deckard / supertype） |
| 1206 vs 1306 | String() 変換（リテラル値のみ異なる） | 0.000（抽象化階層系 B/C） |
| 2512 vs 2919 | toString.call 型判定 | 0.000（抽象化階層系 B/C） |

1206–1306（リテラルのみ相違）と 2512–2919（構造ほぼ同一）は，抽象化階層系が距離 0 を出す一方，791–902（包含関係）では deckard が最も早く結合する結果となった．手法ごとに「得意なパターン」が異なることが確認できる．

#### 考察

- **NiCad** は k=6 固定での ARI が最高で，k の設定が不要という意味で最も扱いやすい
- **提案手法1** は k を大きくすれば ARI は上がるが，重み係数 `(0.45, 0.30, 0.15, 0.10)` がハイパーパラメータとして残り，妥当性評価が困難
- **SourcererCC** は包含関係（D クラスタ）に強く，抽象化設定を調整する余地がある
- **抽象化階層系** は特定のペアを距離 0 で統合できる反面，全体の ARI は低い（クラスタ A や B が分離しにくい）

<details>
<summary>SourcererCC での抽象化試行結果（展開）</summary>

<img width="407" height="754" alt="Image" src="https://github.com/user-attachments/assets/b14c5e28-11ed-4147-b139-4a20ab996cd0" />

</details>

抽象化階層系については，残ってほしいクラスタ構造が維持されないケースが見られた（下図）．

<img width="757" height="439" alt="Image" src="https://github.com/user-attachments/assets/474b27de-e1a9-4847-9726-e4c0b59660f8" />

正規表現または AST パターンとして形式化できれば，コーパスへの検出クエリに直接持ち込めるため，この方向での整理が最も手っ取り早いと考えている．
