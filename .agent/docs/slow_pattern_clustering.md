# Slow Pattern Clustering — 仕様書

本書は **`experiments/scam/approach_temp/` 配下に独立した実験パイプラインを構築し、AST 類似度に基づく集約手法と抽象化レベルの組み合わせを結果ベースで観察する** ための設計書。

**研究変数は次の 2 軸**:

- **抽象化レベル**: A0（元の AST）→ A1 → A2 → A3 → A4 → A5（§3 で定義）。AST に対して単調に抽象化を強くする。
- **集約手法**: ハッシュ完全一致は基準値（ベースライン）として用いるのみで、本研究の主対象は **AST 類似度に基づく集約**（tree edit distance, tree inclusion, anti-unification など）。複数候補を §4 に列挙し、結果を比較する。

**観察対象**:

- 各 `(abst_level, method)` の組み合わせで、cutout 集合がどのようなクラスに集約されるか。
- 抽象化レベルを上げたときの集約変化（クラス数・サイズ分布・代表値の挙動）。
- 既存 10 パターン（Selakovic & Pradel ICSE 2016）との対応の良さ。

**実装上の方針（重要）**:

- 既存の `src/hayalab/pattern/` 配下の実装（`abstraction.py`, `integrate.py` 等）は **本実験では一切再利用しない**。すべてのコード（抽象化規則、集約手法、ランナー、可視化）を `experiments/scam/approach_temp/` 配下に新規実装する。これは「既存資産の後方互換を気にせず、設計を自由に変えながら結果を比較する」ための独立サンドボックスとする位置づけ。
- 入力は `data/processed/MBDiff.json`（または同等の小サンプル `data/processed/_sample.json`）から直接読む。cutout の切り出しも approach_temp 内で再実装し、`hayalab.gumtree` などの低レベル AST ユーティリティのみを参照する（差分計算自体は再利用してよい、再発明はしない）。
- 集約は **depth 独立**: 同じ MB id でも depth (Diff/Brother/ExParent/Parent) が違えば別 AST として扱う。重複排除しない。
- 実装計画書は **保留**。手法が定まった段階で再構築する（`.agent/plans/slow_pattern_clustering/PLAN.md` 参照）。

---

## 1. 設計思想と先行研究上の位置づけ

本実験はクローン検出・パターンマイニングの 2 軸を直交させる。

- **抽象化レベル軸（縦軸）**: Roy, Cordy, Koschke (SCP 2009) のクローン分類 Type-1〜4 の解像度を AST レベルで段階的に粗くしていく。A0 → A5 の 6 段階を §3 に定義。
- **集約手法軸（横軸）**: ハッシュ一致を超えた AST 類似度ベースの集約。clone detection・pattern mining・tree edit distance・anti-unification の文献群から候補を引く。§4 に候補を列挙し、結果を比較する。

| 抽象化レベル | 残るもの | クローン理論との対応 |
|---|---|---|
| A0 | 元 AST のすべての値・構造 | （比較対象なし） |
| A1 | + 識別子は prefix-only 一致（`VAR_N` 等の prefix のみ比較） | Type-2 弱。Baker (WCRE 1995), Roy & Cordy (ICPC 2008, NICAD) と同種 |
| A2 | + リテラル型クラス化 (`NUM`/`STR`/...) | Type-2 完全版 |
| A3 | + 関数系統一・variadic 緩和 | Type-3 寄り。Sajnani et al. (ICSE 2016, SourcererCC) と同方向 |
| A4 | + ユーザ識別子値とリテラル値を完全消去（AST 骨格 + メソッド名 + 演算子のみ） | Type-3 強。SourcererCC の token bag を「組込み API + 構造」だけに限定する発想 |
| A5 | + メソッド名と組込み識別子も消去（純粋な AST 骨格 + 演算子のみ） | Type-4 寄り。Sheneamer & Kalita (IJACSA 2016) survey の "semantic clone" 議論に対応 |

A0 → A5 は単調に抽象化が強くなる（A_{k+1} の同値空間は A_k の同値空間を粗化したもの）。
ノード単位の抽象化規則は §3 に詳述する。

### ハッシュ一致をベースラインとしたうえでの「AST を見る」集約

ハッシュ一致 (M0) は「同じ抽象化を施した木がバイト単位で一致する」ことを要求する**最も厳しい**集約で、これは基準値として併走させる。
本研究の主対象は次のような **AST 構造を直接見る** 集約で、複数候補を §4 に列挙して結果を比較する。

- **木編集距離（TED, APTED）**: 厳密距離に閾値を切る集約。
- **順序保存 tree inclusion**（Kilpeläinen & Mannila SICOMP 1995）: 部分木包含関係でクラスタを連結。
- **Anti-unification / LGG**（Plotkin 1970, Bulychev & Minea SYRCoSE 2008）: 共通骨格の大きさを類似度とし、共通骨格そのものをクラスタ代表値にする。

### Stage 横断の観察

クラスタリング自体は **同一抽象化レベル内** で行うが、レベルを上げた際にクラス集合がどう変化するかを別途観察する。

- **抽象化階段による自然な包含**: レベル k で別クラスだった 2 cutout がレベル k+1 で同一クラスに併合される現象。これが「クラス A ⊑ クラス B（B が A を抽象的に包含）」の最も単純な定義になる（Allamanis & Sutton FSE 2014, Mining Idioms の subsumption lattice に対応）。
- **同一 MB id × 異なる depth の cutout が同一クラスに合流するケース**: 「集約は depth 独立」というルールゆえ、これは集約結果として記録するだけで重複排除しない。観察対象として残す。

### マイクロベンチ特有の前提

本データセット (MBDiff) は以下の性質を持つ。集約手法・閾値を選ぶ際の前提条件として明示する。

- **小規模**: 1 cutout が通常 < 50 ノード。tree edit distance / anti-unification を全ペア計算しても現実的。
- **GumTree マッピング既存**: `matches` が与えられているため、`diff` 範囲（実際に変わった箇所）を明示できる。"パターンの core" は diff 内のノードで決まると仮定できる。
- **抽象化済み入力**: ユーザ定義識別子だけが `VAR_N`/`FUNCTION_N` に置換され、組込みメソッド名（`hasOwnProperty`, `substr` 等）は保持される。Selakovic & Pradel (ICSE 2016) の 10 パターンが組込み名に依存するため、この特性はマッチングを容易にする。

---

## 2. 入力データ　Cutout

入力は `outputs/scam/approach/01_cutouts.json`を利用する．

- `Diff`: diff 範囲そのもののノード集合
- `Brother`: 兄弟ノードまで含む範囲
- `ExParent`: 親ブロックを除いた周辺範囲
- `Parent`: 親ブロックを含む範囲

各 cutout は `Cutout = { id: int, depth: str, diff_node_indices: list[int], nodes: list[NodePayload] }` の形式となっている
`NodePayload = { origin_index, begin, end, label, name, value, parent }`。

### Cutout の独立性

集約は **depth 独立**: 同じ `mb_id` でも `depth` が違えば別 cutout として扱い、重複排除しない。
これにより 1 マイクロベンチマーク から 4 cutout が生成され、各 cutout が独立に各抽象化レベル下で集約対象となる。

### フィルタリング

各cutoutについて，処理内容がわからないものはフィルタリングで除外する．具体的には抽象化されているprefixおよび，`.`, `,`，`;`，`:`，`[`，`]`，`:`，`{`，`}`，`_`，`(`，`)`，`"`，`'`のみからなるcutoutは除外する．除外したものは記録する．

### Pattern（抽象化済み）

各 cutout に各抽象化レベル `Ak (k ∈ {0..5})` を適用すると、抽象化済み AST テンプレートを得る。これを `Pattern` と呼ぶ:

```
Pattern = {
    mb_id: int,
    depth: str,                          // Diff/Brother/ExParent/Parent
    abst_level: int,                     // 0..5
    ast_template: list[TemplateNode],    // 抽象化済みノード列
}
TemplateNode = {
    origin_index: int,
    name: str,                           // node type (例: call_expression)
    value: str | None,                   // 抽象化規則により null になる場合あり
    parent_relative: list[int],          // ローカル parent パス
    slot_id: int | None,                 // identifier slot（A1〜A3 のみ有効）
    is_terminal: bool,
    variadic: bool,                      // A3 以降で付与
}
```

`Pattern` は集約の入力単位となる。実装は `src/hayalab/classes/pattern.py` 等の既存型は **参照せず**、approach_temp 内で軽量な dataclass / dict として再定義する。

---

## 3. 抽象化レベル（A0〜A5）

各レベルは「AST のどの要素を消去 / 保持するか」のみを規定する。**集約手法は §4 で別途扱う**。
レベルは単調: `A_k で同じ AST テンプレートになる 2 cutout は A_{k+1} でも同じ AST テンプレートになる`。

### A0: 元 AST
- 抽象化を適用しない。すべてのノード `name` / `value` / `parent` をそのまま保持。

### A1: 識別子 prefix-only 一致 + リテラル具体値

- ユーザ識別子 (`VAR_N`, `FUNCTION_N`, `KEY_N`, `CLASS_N`) は **prefix** のみで等価判定（`VAR_1 ≡ VAR_2 ≡ VAR_*`、`FUNCTION_1 ≡ FUNCTION_*`）。
- 識別子の slot tracking（同一識別子の複数出現を結ぶ）は保持。
- リテラル値は具体値を保持。
- punctuation は除外。
- ノード `name` は保持。

### A2: + リテラル型クラス化

- A1 に加え、数値・文字列・真偽値・null・regex リテラルを型クラス (`NUM` / `STR` / `BOOL` / `NULL` / `REGEX`) に置換。

### A3: + 関数系統一・variadic 緩和

- A2 に加え、関数系ノード (`function`, `function_expression`, `function_declaration`, `arrow_function`, `generator_function`, `method_definition`, `class_static_block` 等の 7 種) を共通ラベル `FUNCTION_LIKE` に置換。
- `arguments` / `formal_parameters` のような可変長コンテナに `variadic: True` マーカを付与（集約側でこの子リストにのみ順序保存部分列マッチを許可する余地を作る）。

### A4: AST 骨格 + メソッド名のみ保持

A1〜A3 では識別子は prefix-only 一致だったが、A4 では prefix 比較すら不要にしてすべて同一視する。

| 要素 | A3 までの扱い | A4 での扱い |
|---|---|---|
| ユーザ識別子の `value`（`VAR_1`, `FUNCTION_2` 等） | prefix-only 一致 | **完全消去**（value を `null` または `IDENTIFIER` リテラルへ） |
| 識別子 slot tracking (`slot_id`) | 維持 | **無効化**（slot 同一性を要求しない） |
| 数値・文字列・真偽値・null・regex リテラル | A2 で型クラスに置換済み | **さらに統一して** `LITERAL` 単一クラスに置換 |
| `property_identifier.value`（メソッド名） | 具体値保持 | **保持**（A4 の本質） |
| 演算子 anonymous ノード（`==`, `===`, `%` 等） | 保持 | **保持** |
| キーワード anonymous ノード（`for`, `in`, `if` 等） | 保持 | **保持** |
| 組込み識別子値（`Object`, `Array`, `Math`, `String`, `toString` 等） | 保持 | **保持** |
| punctuation | 除外 | 除外 |
| `name`（ノード種別） | 保持 | **保持** |
| variadic マーカ | A3 で付与 | **保持** |

### A5: 純粋な AST 骨格（メソッド名も抽象化）

A4 で残していたメソッド名・組込み識別子値・演算子もすべて消去し、「AST のトポロジ」だけが残る最も抽象的なレベル。

| 要素 | A4 での扱い | A5 での扱い |
|---|---|---|
| `property_identifier.value` | 保持 | **消去**（`null` または `PROPERTY` リテラル） |
| 組込み識別子値（`Object`, `Array`, `String`, `toString` 等） | 保持 | **消去**（一般識別子と同じく `null` / `IDENTIFIER`） |
| `name`（ノード種別） | 保持 | **保持**（AST 骨格は維持） |
| 演算子 anonymous ノード | 保持 | **除外** |
| キーワード anonymous ノード | 保持 | **保持** |
| punctuation | 除外 | 除外 |

### 3.7 ノード単位の抽象化規則総括表

各レベルの抽象化規則を 1 表にまとめる。`✔` は保持、`✘` は消去、`→X` は X に置換、`pfx` は prefix-only 一致。

| 要素 | A0 (元) | A1 | A2 | A3 | A4 | A5 |
|---|---|---|---|---|---|---|
| ノード種別 `name` | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ |
| punctuation | ✘ | ✘ | ✘ | ✘ | ✘ | ✘ |
| 演算子・キーワード anonymous | ✔ | ✔ | ✔ | ✔ | ✔ | ✘ |
| ユーザ識別子 `value` (`VAR_N`) | 具体 | →pfx | →pfx | →pfx | →`VAR` | →`VAR` |
| 識別子 slot_id 同一性 | n/a | ✔ | ✔ | ✔ | ✘ | ✘ |
| 組込み識別子 `value` (`String`, `Object`...) | ✔ | ✔ | ✔ | ✔ | ✔ | →`IDENTIFIER` |
| `property_identifier.value` (メソッド名) | ✔ | ✔ | ✔ | ✔ | ✔ | →`PROPERTY` |
| リテラル値（具体） | ✔ | ✔ | →型クラス | →型クラス | →`LITERAL` | →`VAR` |
| 関数系 7 種 (`function`/`arrow_function` 等) | ✔ | ✔ | ✔ | →`FUNCTION_LIKE` | →`FUNCTION_LIKE` | →`FUNCTION_LIKE` |
| variadic マーカ | n/a | n/a | n/a | ✔ | ✔ | ✔ |

**単調性の不変条件**: 抽象化レベルは単調なので、A_k で抽象化が等しい 2 cutout は A_{k+1} でも抽象化が等しい。
これは集約手法に依存せず成り立つ性質で、ハッシュ一致 (M0) では「Stage k で同一クラスなら Stage k+1 でも同一クラス」と読み替えられる。
類似度ベースの集約 (M1〜M3, §4) では「Stage k で同一クラスならば Stage k+1 でも分離されない」という弱い形式で成り立つ
（k で同一なら同じ抽象化済み AST テンプレートを持ち、k+1 でも同じテンプレートになるため、いかなる類似度関数でも距離 0 になる）。

---

## 4. 集約手法（M0〜M3）

各抽象化レベルに対し、以下の集約手法を独立に適用する。本研究の主対象は **M1〜M3** で、M0 はベースライン。

### M0: ハッシュ完全一致（ベースライン）

抽象化後の `ast_template` を JSON 正規化 → SHA-256 でハッシュ化し、ハッシュ完全一致で集約。
最も厳格な集約で、Type-1 クローン検出に対応（Kamiya et al. TSE 2002, CCFinder）。

### M1: 順序保存 tree inclusion による単方向包含

クラスタリングを「**P が T の部分木として埋め込み可能 ⇒ P と T を同じクラスに**」というルールで連結成分を作る。

- アルゴリズム: Kilpeläinen & Mannila (SICOMP 1995) "Ordered and unordered tree inclusion" の順序保存版 `O(|P| · |T|)`。
- マッチング規則: ノード `name` は厳密一致。`value` は当該抽象化レベルで保持される範囲で厳密一致（A4/A5 で `null`/`IDENTIFIER`/`LITERAL`/`PROPERTY` になっているノードはワイルドカード扱い）。punctuation は除外、variadic 子は順序保存部分列マッチ。
- 集約: cutout のペア (A, B) について `A ⊑ B` または `B ⊑ A` のいずれかが成立すれば同じクラスに連結。union-find で連結成分を構築。
- 利点: 代表は「クラス内で最も具体的なメンバ」を取れば、他メンバはそれを包含する形で説明できる。

### M2: 双方向 tree inclusion による等価判定

M1 を厳しくした版。`A ⊑ B` **かつ** `B ⊑ A` が成立する場合のみ等価とみなす。

- ヒット集合 `H(P) = { cutout T | P ⊑ T }` をすべての cutout P について計算。
- `H(P1) == H(P2)` のとき P1 と P2 を等価クラスに入れる。
- これは Allamanis & Sutton (FSE 2014, Mining Idioms) の idiom subsumption lattice での「同層の等価」を AST に転用したもの。
- M1 と比較してより厳格、Type-3 強寄りの集約になる。

### M3: Anti-unification (LGG) ベースの貪欲併合

Plotkin (1970) の 1st-order anti-unification を計算し、共通骨格の大きさが閾値を超えるペアを併合する。

- 類似度: `sim(A, B) = |non_slot(LGG(A, B))| / (|A| + |B| − |LGG(A, B)|)`（Jaccard 風、§前回議論）。
- 閾値: `τ_sim` を 0.3〜0.7 で grid search。
- サイズ比ガード: `max(|A|, |B|) / min(|A|, |B|) > κ` のペアは除外。
- 非縮退条件: 累積 LGG の非 slot 比率が `ρ · |R_initial|` を下回る併合は拒否。
- 利点: クラス代表が anti-unification 結果としてそのまま出る（穴付き AST テンプレート）。
- 根拠: Bulychev & Minea (SYRCoSE 2008) の anti-unification ベースの duplicate code detection と同種。

### 各手法の比較で見たい性質

| 観点 | M0 | M1 | M2 | M3 |
|---|---|---|---|---|
| 集約の厳しさ | 最厳 | 緩 | 中 | 中 |
| 距離公理 | 自明満たす | 満たさない | 満たさない | 満たさない |
| 代表値の出力 | クラス内任意 | 最具体メンバ | 任意（代表性指標を別途定義） | LGG 結果 |
| 推移閉包 chaining | 起きない | 起きうる | 起きにくい | 制御可能（非縮退条件） |
| 計算量 | O(N) | O(N²·n²) | O(N²·n²) | O(N²·n) |
| 候補引用 | Kamiya 2002 | Kilpeläinen 1995 | Allamanis 2014 | Plotkin 1970, Bulychev 2008 |


---

## 5. 抽象化レベル横断の観察

§3 で各レベル内の抽象化を、§4 で各レベルで適用する集約手法をそれぞれ定義した。
本節は、抽象化レベルを上げていったときの集約結果の変化を **観察対象** として定義する。

### 5.1 集約の独立実施と集約軌跡

**集約は各抽象化レベルで全 cutout に対して独立に実施する**（前レベルのクラスを単位として再集約するのではない）。
すなわち、同じ cutout セットに A0・A1・...・A5 の抽象化をそれぞれ施し、各レベルで独立に集約アルゴリズムを適用する。
これにより、抽象度が上がった際に cutout が **異なるクラスへ移動する**・**別クラスに分裂する（単一クラスになる）** ケースがそのまま観察できる。

具体的には、cutout x に対して `c_k(x, method) = x が属するクラス ID at (Ak, method)` を計算し、
各 cutout に対して 6 段階のクラス ID 列 `(c_0, c_1, c_2, c_3, c_4, c_5)` を割り当てる。これを **集約軌跡** と呼ぶ。

全 cutout の集約軌跡を `trajectory.json` に保存する（§5.4 参照）。

**単調性の確認**: M0（ハッシュ完全一致）のみ、§3.7 の不変条件により `c_k(x) ≠ c_k(y)` ならば `c_{k+1}(x) ≠ c_{k+1}(y)` が保証される。M1〜M3 は類似度ベースの集約であるため、レベルを上げると **異なるクラスへの再配置** が起こりうる。これは仕様上許容される挙動であり、観察対象として記録する。

### 5.2 集約手法横断の比較

各レベルで M0/M1/M2/M3 を並べて回し、`C(level, method)` を比較する:

- クラス数の差: M0（最厳）→ M3（緩）の順に減少するはず。
- ground-truth purity の差（§6 参照）: どの手法が論文 10 パターンを最もきれいに分離するか。
- クラス内一致性: 同じクラスのメンバが他手法でも同じクラスにいるか（手法間のクラスタリング合意度を ARI で測る）。

### 5.3 同一 MB id × 異なる depth の cutout が同一クラスに合流するケース

cutout を `(mb_id, depth)` の組で識別し、同一 mb_id の 4 depth は基本的に独立に扱う。
だが集約の結果、同じ mb_id の cutout が同じクラスに合流するケースは頻繁に起きると予想される。

これは **重複排除しない** 方針で、集約結果として記録する。観察対象として次を `summary.json` に出力:

- クラス内の (mb_id, depth) 多様性: 同一 mb_id 重複の頻度ヒストグラム。
- depth 別の集約挙動: 各 depth (Diff/Brother/ExParent/Parent) が抽象化階段でどのタイミングで合流するか。
- depth プロファイル: クラスごとのメンバの depth 分布。1 つの depth のみで構成されるクラス vs 複数 depth を含むクラスの割合。

### 5.4 集約軌跡の Sankey 可視化

**目的**: 各 cutout が抽象化レベルを上がるにつれてどのクラスに束ねられるかを一覧する。

**形式**: 集約手法（M0〜M3）ごとに独立した Sankey 図を 4 枚生成する。

**Sankey 図の軸定義**:

- **横軸**: 抽象化レベル `A0 → A1 → A2 → A3 → A4 → A5`（各レベルが 1 ステージ）。
- **縦軸（各ステージ内）**: そのレベルで得られたクラス群（クラス ID ごとのノード）。クラスが縦方向に並ぶ。
- **フロー**: 各 cutout の移動パスを表す帯。帯の幅は 1（cutout 1 件 = 太さ 1）。同一クラスに束ねられた cutout 群は太い帯として描かれる。
- **色付け**: cutout ごとに色を固定するか、A0 時点のクラスを起点に色分けする（実装時に選択）。

**可視化の観察ポイント**:

- 同一クラスの cutout 群が次レベルでも同一クラスに合流するか（単調な束ね上がり）。
- 一部の cutout が次レベルで **別クラスへ分岐** するケース（クロス遷移）。
- 複数クラスが 1 つのクラスに **合流** するケース（クラス数減少の構造）。
- 最終レベル（A5）でほぼ全 cutout が 1〜2 クラスに収束するかどうか。

**入力データ**: `trajectory.json`（各 cutout の集約軌跡）

```jsonc
// trajectory.json の 1 エントリ（method 固定ごとに別ファイル、例: trajectory_M1.json）
{
  "cutout_id": "mb12_Diff",     // "{mb_id}_{depth}"
  "mb_id":     12,
  "depth":     "Diff",
  "trajectory": [
    {"level": 0, "class_id": "L0_M1_3a9f"},
    {"level": 1, "class_id": "L1_M1_3a9f"},
    {"level": 2, "class_id": "L2_M1_7c2e"},  // 別クラスへ移動した例
    {"level": 3, "class_id": "L3_M1_7c2e"},
    {"level": 4, "class_id": "L4_M1_1b5a"},  // さらに別クラスへ
    {"level": 5, "class_id": "L5_M1_1b5a"}
  ]
}
```

**実装**: `visualize_sankey.py`（approach_temp 内）。入力は `trajectory_{method}.json`、出力は `sankey_{method}.html`。
ライブラリは Plotly (`plotly.graph_objects.Sankey`) を想定するが、同等の静的図（`matplotlib-sankey` 等）でも可。

---

## 6. 代表値の出力形式

各クラスについて 3 形式で代表を出力する。`(abst_level, method)` のそれぞれで独立にクラス集合が得られるため、両方のタグを必ず付ける。

1. **AST テンプレート JSON** — 抽象化済みノード列。
   - M0/M1/M2 の場合: クラス内任意メンバの ast_template（M2 では「最小サイズメンバと最大サイズメンバ」を選ぶ）。
   - M3 (anti-unification) の場合: 累積 LGG 結果。穴は `slot_role: "wildcard"` で表現。
2. **可読プリティ文字列** — 抽象化レベルに応じたプレースホルダ付き擬似コード。
   - A1 までは `VAR_1.substr(0, 2)` のように識別子 prefix を維持。
   - A2 では `VAR_1.substr(NUM, NUM)`、A3 では関数系を `<FUNCTION_LIKE>`。
   - A4 では `<IDENTIFIER>.substr(<LITERAL>, <LITERAL>) !== <LITERAL>` のようにユーザ識別子・リテラルを抽象化。
   - A5 では `<IDENTIFIER>.<PROPERTY>(<LITERAL>, <LITERAL>) !== <LITERAL>` のようにメソッド名も抽象化。
3. **代表メンバの実コード** — クラス内で **最小サイズ**（ノード数最少）のメンバの `code[begin:end]` を選び、生サンプルとして添える。

クラス 1 件分の出力:

```jsonc
{
  "class_id":       "L4_M1_07f3a2b1",         // (abst_level, method) を prefix に持つ ID
  "abst_level":     4,                        // 0..5
  "method":         "M1",                     // M0..M3
  "size":           42,                       // メンバ数
  "members":        [{ "mb_id": 12, "depth": "Diff" }, ...],
  "depth_profile":  {"Diff": 18, "Brother": 12, "ExParent": 8, "Parent": 4},
  "representative_ast":     [<TemplateNode>, ...],
  "representative_string":  "<IDENTIFIER>.substr(<LITERAL>, <LITERAL>) !== <LITERAL>",
  "smallest_member_code":   "key.substr(0, 2) !== \"$$\"",
  "largest_member_code":    "~~"
  "incoming_classes": ["L3_M1_9bc1..."],   // (level-1, method) でこのクラスに合流してきた前レベルのクラス群
  "outgoing_class":   "L5_M1_5e2a...",     // (level+1, method) でこのクラスが属する先のクラス（level==5 のときは null）
                                             // ※ cutout 単位の遷移詳細は trajectory_{method}.json 参照（§5.4）
  "diff_overlap_ratio": 0.84                  // クラス代表ノードが各メンバの diff_node_indices と重なる平均割合
}
```

`diff_overlap_ratio` は「クラス代表のノードが、各メンバの `diff_node_indices` とどれくらい重なるか」の平均で、
**マイクロベンチ特有の追加指標**。1.0 に近いほど「diff の本体そのもの」、0 に近いほど「diff 周辺の文脈」を集約していることを意味する。

---

## 7. 評価方法

### 7.1 集約結果のメトリクス（手法 × レベル毎に記録）

各 `(abst_level, method)` の組み合わせで次を `summary.json` に記録する。

- クラス総数
- クラスサイズ分布（平均、中央値、最大、ヒストグラム）
- 集約率: `1 − (クラス数 / 全 cutout 数)`
- 単一要素クラス（集約されなかった）数とその depth 分布
- 各クラスに含まれる depth の分布（depth プロファイル）
- 同一 mb_id 重複頻度ヒストグラム
- 単調性違反件数: §3.7 の不変条件（同 method で level k → k+1 で必ず合流または不変）に反する遷移が 0 件であるべき。検出時はバグ。

### 7.2 ground-truth との照合（Selakovic & Pradel の 10 パターン）

`.agent/docs/slow_pattern_detection.md` で実装する **slow pattern detector** の検出結果を ground truth として用いる。

- **Purity**: クラス内で同一 pattern_id の MB が占める比率の重み付き平均。
- **NMI (Normalized Mutual Information)**: クラスタリングと 10 パターン ラベルの情報量一致度。
- **ARI (Adjusted Rand Index)**: ペア一致度の補正版。
- **Coverage**: 10 パターン中、**いずれかの (level, method)** で「単独クラスまたは過半数を占めるクラス」になったものの数（理想は 10）。
- **Best (level, method) profile**: 各 pattern_id について、Purity が最大化される `(level, method)` を記録（「このパターンは A3 × M1 で最もきれいに分離される」のような結論を得る）。

これらを A0..A5 × M0..M3 = **24 通り**で並べて出力し、**「どの抽象レベル × 集約手法でパターンが分離 / 統合されるか」** をヒートマップ等で可視化する。

### 7.3 集約手法間の合意度

同一抽象化レベルで M0/M1/M2/M3 の出力クラスタリングを互いに比較し、ARI / NMI で「手法間でどれくらい合意するか」を測る。
これは「ハッシュ一致 (M0) を緩めて何が変わったか」を直接見るための指標。


---

## 8. 既知の限界と研究的論点

- **Tree inclusion の計算量（M1/M2）**: 一般の unordered tree inclusion は NP 困難（Kilpeläinen & Mannila 1995）。本タスクでは順序保存版 (ordered inclusion) を採用し、`O(|P| · |T|)` 程度で済む。順序保存にすることで `arguments` の引数順や `binary_expression` の左右順を区別するが、これは性能パターンとして妥当な仮定。
- **A3 の variadic 緩和との競合**: variadic ノードに対しては部分列マッチングを許可するため、ordered inclusion の純粋形を逸脱する。実装時は variadic 子ノードだけ部分列許可、その他は厳密順序、というハイブリッドにする。
- **代表 AST の "穴" の表現**: A4/A5 で識別子値・メソッド名を消去するため、ast_template の `value` が `null` または定数文字列になる。これは tree inclusion 上で「任意の同種ノードにマッチ」を意味する wildcard と等価で、`slot_role: "wildcard"` を optional フィールドとして付与する。M3 (anti-unification) の slot も同じフィールドで表現できる。
- **マイクロベンチが論文 10 パターンを含まない可能性**: 仕様 `slow_pattern_detection.md` の Stage A/B の検出数で母数が分かる。10 パターンに該当しない大規模クラスは "未知パターン候補" として REPORT に別枠で記載する。
- **集約手法の閾値選定**: M3 の `τ_sim`, `κ`, `ρ` は ground-truth との対応で grid search する。M1/M2 は閾値を持たないが、tree inclusion の許容範囲（厳密順序 vs 部分列許可）が暗黙のパラメータになる。

---

## 9. 境界規約と実装配置

**本実験はすべて `experiments/scam/approach_temp/` 配下で完結する**。`src/hayalab/` 配下のコードは編集しない。

approach_temp 内の標準構成（抽象化レベル × 集約手法を 1 つの軸として走る構造）:

```
experiments/scam/approach_temp/
├── README.md
├── ast_node.py             # NodePayload / TemplateNode の dataclass 定義
├── abstract.py             # A0..A5 抽象化規則の適用
├── methods/
│   ├── __init__.py
│   ├── m0_hash.py          # M0: ハッシュ完全一致
│   ├── m1_inclusion.py     # M1: 単方向 tree inclusion
│   ├── m2_bi_inclusion.py  # M2: 双方向 tree inclusion
│   └── m3_antiunify.py     # M3: anti-unification
├── observe.py              # §5 集約軌跡・depth プロファイル生成（trajectory_{method}.json 出力）
├── evaluate.py             # §7 ground-truth 照合・Purity/NMI/ARI
├── export.py               # §6 代表値出力（classes_{level}_{method}.json）
├── visualize_sankey.py     # §5.4 Sankey 図生成（trajectory_{method}.json → sankey_{method}.html）
└── run.py                  # メインランナー（--levels A0..A5 --methods M0..M3 を指定）
```

`src/hayalab/` 配下のユーティリティで再利用するもの:

- `hayalab.gumtree` の差分計算（AST パース・GumTree 呼び出し）。これは外部ツール連携なので再実装しない。
- `hayalab.classes.gumtree.ASTNode` などの **入力 dataclass** は読み取りに使ってよい（型は参照するが、本実験用の `Pattern`/`TemplateNode` は別途定義する）。

**再利用しないもの**:

- `hayalab.pattern.abstraction.compute_signature`（本実験は独自実装）。
- `hayalab.pattern.integrate.integrate_features`（ハッシュ集約は本実験では M0 として別実装）。
- `hayalab.classes.pattern.Pattern`（dataclass の責務が違うため別定義）。

---

## 10. 参考文献（書誌情報の細部は引用時に再確認すること）

1. Roy, C. K., Cordy, J. R., Koschke, R. **"Comparison and evaluation of code clone detection techniques and tools: A qualitative approach"**. *Science of Computer Programming*, 2009.
2. Kamiya, T., Kusumoto, S., Inoue, K. **"CCFinder: A multilinguistic token-based code clone detection system for large scale source code"**. *IEEE Transactions on Software Engineering*, 2002.
3. Baker, B. S. **"On finding duplication and near-duplication in large software systems"**. *WCRE*, 1995.
4. Roy, C. K., Cordy, J. R. **"NICAD: Accurate detection of near-miss intentional clones using flexible pretty-printing and code normalization"**. *ICPC*, 2008.
5. Sajnani, H., Saini, V., Svajlenko, J., Roy, C. K., Lopes, C. V. **"SourcererCC: Scaling code clone detection to big-code"**. *ICSE*, 2016.
6. Baxter, I. D., Yahin, A., Moura, L., Sant'Anna, M., Bier, L. **"Clone detection using abstract syntax trees"**. *ICSM*, 1998.
7. Jiang, L., Misherghi, G., Su, Z., Glondu, S. **"DECKARD: Scalable and accurate tree-based detection of code clones"**. *ICSE*, 2007.
8. Falleri, J.-R., Morandat, F., Blanc, X., Martinez, M., Monperrus, M. **"Fine-grained and accurate source code differencing"**. *ASE*, 2014.
9. Pawlik, M., Augsten, N. **"Tree edit distance: Robust and memory-efficient"** (APTED). *Information Systems*, 2016.
10. Allamanis, M., Sutton, C. **"Mining idioms from source code"**. *FSE*, 2014.
11. Allamanis, M., Barr, E. T., Devanbu, P., Sutton, C. **"A survey of machine learning for big code and naturalness"**. *ACM Computing Surveys*, 2018.
12. Plotkin, G. D. **"A note on inductive generalization"**. *Machine Intelligence 5*, 1970.
13. Bulychev, P., Minea, M. **"Duplicate code detection using anti-unification"**. *SYRCoSE*, 2008.
14. Kilpeläinen, P., Mannila, H. **"Ordered and unordered tree inclusion"**. *SIAM Journal on Computing*, 1995.
15. Zaki, M. J. **"Efficiently mining frequent trees in a forest: Algorithms and applications"**. *IEEE Transactions on Knowledge and Data Engineering*, 2005.
16. Svajlenko, J., Islam, J. F., Keivanloo, I., Roy, C. K., Mia, M. M. **"Towards a big data curated benchmark of inter-project code clones"** (BigCloneBench). *ICSME*, 2014.
17. Bille, P. **"A survey on tree edit distance and related problems"**. *Theoretical Computer Science*, 2005.
18. Selakovic, M., Pradel, M. **"Performance issues and optimizations in JavaScript: An empirical study"**. *ICSE*, 2016. — 本研究の評価 ground-truth 出典。
19. Pradel, M., Sen, K. **"DeepBugs: A learning approach to name-based bug detection"**. *OOPSLA*, 2018. — ペアからのパターン学習の同類。
20. Sheneamer, A., Kalita, J. **"A survey of software clone detection techniques"**. *International Journal of Advanced Computer Science and Applications (IJACSA)*, 2016. — Type-4 semantic clone の議論。
21. White, M., Tufano, M., Vendome, C., Poshyvanyk, D. **"Deep learning code fragments for code clone detection"**. *ASE*, 2016. — 構造 only での近似クローン検出。

引用時は DBLP / Google Scholar で巻号・ページ・被引用数を再確認のこと。

---

## 11. 実装方針の最終確認

- **既存 `src/hayalab/pattern/` の実装は本実験では一切再利用しない**。すべて `experiments/scam/approach_temp/` 配下で新規実装する。これは境界規約 (`experiments → hayalab`) を一時的に逸脱する判断だが、設計を自由に変えて結果ベースで比較するためのサンドボックスとして許容する。手法が定まった段階で `src/hayalab/` に整理し直すかは別途判断。
- 既存 `hayalab.gumtree` の AST パース・GumTree 差分計算は再利用する（外部ツール連携のため）。
- A0..A5 × M0..M3 = 24 通りの集約結果を出すこと、`(abst_level, method)` でファイル名にタグを付けることを徹底する。
- 単調性違反は実装バグ。テストで担保する。
