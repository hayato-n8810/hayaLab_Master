# E6. 新規パターン候補 30 件 — 全 16 cell × 30 = 480 candidate

## 1. 目的

事前分析で検証した既知 7 パターンに対応しない **新規パターン候補** を、 提案手法の集約結果から抽出し提示する。 paper §6.3.2 「得られた新規パターン」 への主データ。

**ユーザ意図**: サイズ depth ごとに対応できるパターン構造が異なり、 周辺文脈で意味が変わり得る。 そこで τ=0.7 / L0 / Diff の 1 cell だけでなく、 **全 16 cell** (τ ∈ {0.7, 0.9} × 抽象化 L ∈ {0, 1} × サイズ depth ∈ {Diff, Brother, ExParent, Parent}) で 30 件ずつ抽出し、 サイズ・抽象度別の比較を行う。

各 cell で:
1. 既知 7 パターンの top1 クラス集合 K (7 個) を除外
2. K 以外で size ≥ 10 のクラスを size 降順 30 件 candidate に選ぶ
3. 各 candidate に skeleton + mode_medoid 代表値 + fast 側 AST_HEAD サンプル を併記
4. AI 一次分類 (novel / variant / noise) を付与

---

## 2. 用語と判定基準

| 用語 | 意味 |
|---|---|
| **既知 top class 集合 K (cell ごと)** | 各 cell における 7 既知パターンの top1 クラス (合計 7 個、 cell によって異なる) |
| **candidate** | K を除外した上で、 size ≥ 10 のクラスを size 降順に並べた上位 30 件 |
| **AI 一次分類** | 以下のヒューリスティックによる自動分類: |
|  | - **noise**: skeleton が `*` または skeleton 位置別 support の最大値 < サイズの 20 % |
|  | - **variant**: mode_medoid の support ≥ サイズの 50 % (= 強い典型パターン) |
|  | - **novel**: 上記以外 (= 新規パターン候補) |

paper 採用時はユーザレビューで上書き想定。
support：代表値と完全一致するメンバーの数

---

## 3. 全 16 cell の AI 一次分類集計

| τ | L | depth | novel | variant | noise |
|---:|---:|---|---:|---:|---:|
| 0.7 | 0 | Diff | 17 | 12 | 1 |
| 0.7 | 0 | Brother | 17 | 6 | 7 |
| 0.7 | 0 | ExParent | 18 | 5 | 7 |
| 0.7 | 0 | **Parent** | **24** | 4 | 2 |
| 0.7 | 1 | Diff | 14 | 11 | 5 |
| 0.7 | 1 | Brother | 14 | 8 | 8 |
| 0.7 | 1 | ExParent | 13 | 7 | 10 |
| 0.7 | 1 | **Parent** | **23** | 7 | 0 |
| 0.9 | 0 | Diff | 4 | 24 | 2 |
| 0.9 | 0 | Brother | 6 | 24 | 0 |
| 0.9 | 0 | ExParent | 5 | 25 | 0 |
| 0.9 | 0 | Parent | 14 | 16 | 0 |
| 0.9 | 1 | Diff | 3 | 27 | 0 |
| 0.9 | 1 | Brother | 6 | 24 | 0 |
| 0.9 | 1 | ExParent | 10 | 20 | 0 |
| 0.9 | 1 | Parent | 16 | 14 | 0 |

### 観察

- **τ=0.7 系**: novel が 13-24 件と多い。 size 大の noise が Brother/ExParent で目立つ (擬似集約)
- **τ=0.9 系**: variant が 14-27 件と多い (純度高くイディオム中心)、 noise はほぼ消滅
- **Parent depth で novel が最大** (τ=0.7 で 23-24/30): 関数本体全体の構造を持つ新規パターンが多い
- **抽象化 L0 → L1 で noise が増える傾向** (Brother, ExParent): リテラル抽象化で異質事例が同型化

---

## 4. cell 別 top 5 candidate (τ=0.7、 4 depth × L0/L1 = 8 cell)

### 4.1 τ=0.7 / L0 / Diff (一律ベスト)

| # | クラス ID | サイズ | AI | skeleton | mode_medoid (strategy, support) |
|---:|---|---:|---|---|---|
| 1 | `L0_M2_bd5d5c65` | 1,031 | noise | `*` | `for var $v0 = 0 $v0 < $v1 length $v0 ++ $v2 push $v1 $v0` (medoid, 17) |
| 2 | `L0_M2_88161bda` | 307 | variant | `new Date *` | `new Date getTime` (mode, 186) |
| 3 | `L0_M2_5b9e2ca0` | 300 | variant | `+ new Date` | `+ new Date` (mode, 291) |
| 4 | `L0_M2_de637691` | 225 | **novel** | `$v0 *` | `$v0 = $v0 concat $v1` (medoid, 43) |
| 5 | `L0_M2_6691a745` | 224 | **novel** | `* $v0 *` | `var $v0 = $v0 push $v1 $v2 = $v0 join` (medoid, 5) |

### 4.2 τ=0.7 / L0 / Brother (兄弟まで)

| # | クラス ID | サイズ | AI | skeleton | mode_medoid (strategy, support) |
|---:|---|---:|---|---|---|
| 1 | `L0_M2_6d1cdc05` | 989 | novel | `var $v0 *` | `var $v0 = for var $v1 = 0 $v1 < 10000 $v1 ++ $v0 push $v1 var $v2 = for ...` (medoid, 1) |
| 2 | `L0_M2_c3abb8de` | 555 | noise | `*` | `+ new Date` (medoid, 166) |
| 3 | `L0_M2_86060283` | 130 | **novel** | `$v0 = * concat *` | `$v0 = $v0 concat $v1` (medoid, 47) |
| 4 | `L0_M2_e8c34c00` | 113 | variant | `$v0 < $v1 length` | `$v0 < $v1 length` (mode, 97) |
| 5 | `L0_M2_1da1e49e` | 100 | noise | `*` | `JSON parse JSON stringify $v0` (medoid, 27) |

### 4.3 τ=0.7 / L0 / ExParent (内側ブロックまで)

| # | クラス ID | サイズ | AI | skeleton | mode_medoid (strategy, support) |
|---:|---|---:|---|---|---|
| 1 | `L0_M2_f50b33d8` | 984 | noise | `*` | `for var $v0 = 0 $v0 < $v1 length $v0 ++ $v2 push $v1 $v0` (medoid, 6) |
| 2 | `L0_M2_b12838cc` | 247 | **novel** | `var $v0 = *` | `var $v0 = $v0 push $v1 $v2 = $v0 join` (medoid, 5) |
| 3 | `L0_M2_47c1c4e9` | 201 | noise | `*` | `new Date getTime` (medoid, 97) |
| 4 | `L0_M2_cd95ed71` | 172 | **novel** | `for var $v0 in $v1 *` | `for var $v0 in $v1 var $v2 = $v1 $v0` (medoid, 40) |
| 5 | `L0_M2_fc91fc79` | 166 | **novel** | `$v0 * function $v1 *` | `$v0 forEach function $v1` (medoid, 17) |

### 4.4 τ=0.7 / L0 / Parent (外側ブロックまで)

| # | クラス ID | サイズ | AI | skeleton | mode_medoid (strategy, support) |
|---:|---|---:|---|---|---|
| 1 | `L0_M2_3993549e` | 155 | variant | `var $v0 = *` | `var $v0 = + new Date` (mode, 80) |
| 2 | `L0_M2_2ee3ca25` | 153 | variant | `+ new Date` | `+ new Date` (mode, 151) |
| 3 | `L0_M2_bacc448d` | 138 | **novel** | `Math * - 1 Math * 0 Math * 1.5` | `Math tanh - 1 Math tanh 0 Math tanh 1.5` (medoid, 20) |
| 4 | `L0_M2_15c3a722` | 98 | variant | `var $v0 = new Date *` | `var $v0 = new Date getTime` (mode, 56) |
| 5 | `L0_M2_c85b0946` | 96 | **novel** | `var $f0 = function var $v0 = 1 $f0 apply $f0 $v0 $v0 *` | `var $f0 = function var $v0 = 1 $f0 apply $f0 $v0 $v0 $v0 $v0` (medoid, 12) |

### 4.5 τ=0.7 / L1 / Diff

| # | クラス ID | サイズ | AI | skeleton | mode_medoid (strategy, support) |
|---:|---|---:|---|---|---|
| 1 | `L1_M2_7b4a05ae` | 1,240 | noise | `*` | `for var $v0 = $n0 $v0 < $v1 length $v0 ++ $v2 push $v1 $v0` (medoid, 17) |
| 2 | `L1_M2_589a3467` | 964 | noise | `*` | `var $v0 = $v0 push $s0 var $v1 = $v0 join` (medoid, 29) |
| 3 | `L1_M2_88161bda` | 307 | variant | `new Date *` | `new Date getTime` (mode, 186) |
| 4 | `L1_M2_5b9e2ca0` | 300 | variant | `+ new Date` | `+ new Date` (mode, 291) |
| 5 | `L1_M2_8d1d824c` | 282 | **novel** | `$v0 *` | `$v0 = $v0 concat $v1` (medoid, 43) |

### 4.6 τ=0.7 / L1 / Brother

| # | クラス ID | サイズ | AI | skeleton | mode_medoid (strategy, support) |
|---:|---|---:|---|---|---|
| 1 | `L1_M2_c61f8e7d` | 780 | noise | `*` | `var $v0 = $s0 var $v1 = $v0 replace $r0 $r1 $r0 $s1` (medoid, 1) |
| 2 | `L1_M2_9ecde0c2` | 598 | noise | `*` | `$v0 = $s0 $s1 $s2 ...` (medoid, 1) |
| 3 | `L1_M2_07026714` | 558 | noise | `*` | `+ new Date` (medoid, 166) |
| 4 | `L1_M2_41f54ce1` | 179 | **novel** | `* $r0 *` | `$v0 replace $r0 $r1 $r0` (medoid, 44) |
| 5 | `L1_M2_6bda4f58` | 157 | **novel** | `var $v0 = *` | `var $v0 = $n0 $n1 $n2 ...` (medoid, 3) |

### 4.7 τ=0.7 / L1 / ExParent

| # | クラス ID | サイズ | AI | skeleton | mode_medoid (strategy, support) |
|---:|---|---:|---|---|---|
| 1 | `L1_M2_49259214` | 1,289 | noise | `*` | `for var $v0 = $n0 $v0 < $v1 length $v0 ++ $v2 push $v1 $v0` (medoid, 6) |
| 2 | `L1_M2_82fcbb4e` | 262 | noise | `*` | `$r0 $r1 $r0 test $v0` (medoid, 95) |
| 3 | `L1_M2_f2862d5d` | 203 | noise | `*` | `new Date getTime` (medoid, 97) |
| 4 | `L1_M2_81c0bf2a` | 178 | **novel** | `for var $v0 in $v1 *` | `for var $v0 in $v1 var $v2 = $v1 $v0` (medoid, 40) |
| 5 | `L1_M2_029a3d70` | 172 | **novel** | `$v0 * $v1 *` | `$v0 forEach function $v1` (medoid, 17) |

### 4.8 τ=0.7 / L1 / Parent

| # | クラス ID | サイズ | AI | skeleton | mode_medoid (strategy, support) |
|---:|---|---:|---|---|---|
| 1 | `L1_M2_096375ec` | 262 | **novel** | `* $f0 *` | `var $f0 = function $v0 this $v1 = $v0 $f0 prototype $f1 = function var $v2 = new $f0 ...` (medoid, 1) |
| 2 | `L1_M2_3e345cdd` | 236 | **novel** | `var $v0 = *` | `var $v0 = $s0 var $v1 = $s1 Math floor $v0 Math floor $v1` (medoid, 11) |
| 3 | `L1_M2_5ff4fe1b` | 183 | **novel** | `var $v0 = *` | `var $v0 = $n0 $n1 $n2 ... (大きな数値配列)` (medoid, 3) |
| 4 | `L1_M2_07a2a0bd` | 162 | **novel** | `var $v0 = *` | `var $v0 = $n0 $n1 $n2 ... $v0 forEach function` (medoid, 4) |
| 5 | `L1_M2_93649366` | 158 | variant | `var $v0 = *` | `var $v0 = + new Date` (mode, 80) |

---

## 5. cell 別 top 5 (τ=0.9、 補足セクション)

### 5.1 τ=0.9 / L0 / Diff (純粋分散)

| # | クラス ID | サイズ | AI | skeleton | mode_medoid (strategy, support) |
|---:|---|---:|---|---|---|
| 1 | `L0_M2_86cf3203` | 291 | variant | `+ new Date` | `+ new Date` (mode, 291) |
| 2 | `L0_M2_07ab15d6` | 177 | variant | `new Date getTime` | `new Date getTime` (mode, 177) |
| 3 | `L0_U1_42656a5a` | 172 | variant | `$v0` | `$v0` (mode, 172) |
| 4 | `L0_M2_81ec7bac` | 100 | variant | `$v0 length` | `$v0 length` (mode, 100) |
| 5 | `L0_M2_6aa540aa` | 91 | **novel** | `$v0 *` | `$v0 $v1` (medoid, 43) |

τ=0.9 では純粋クラスとして **典型イディオム** (`+ new Date`、 `new Date.getTime()`、 `$v.length`) が完全一致で抽出される。

### 5.2 τ=0.9 / L0 / Parent (純粋 + 文脈広)

| # | クラス ID | サイズ | AI | skeleton | mode_medoid (strategy, support) |
|---:|---|---:|---|---|---|
| 1 | `L0_M2_5a3ce5ee` | 151 | variant | `+ new Date` | `+ new Date` (mode, 151) |
| 2 | `L0_M2_4cfe9ddb` | 90 | variant | `new Date getTime` | `new Date getTime` (mode, 90) |
| 3 | `L0_M2_c838f829` | 81 | variant | `var $v0 = + new Date` | `var $v0 = + new Date` (mode, 80) |
| 4 | `L0_M2_e4f6fe61` | 75 | **novel** | `var $f0 = function var $v0 = 1 $f0 apply $f0 $v0 $v0 *` | (clipped) |
| 5 | — | — | — | — | — |

(全データは CSV を参照)

---

## 6. サイズ・抽象度別の新規パターン構造の比較

### 6.1 同じ意味のパターンが depth で異なる代表値に化ける例

#### 例 1: `$v.concat` 系 (配列連結)

| cell | 代表クラス | サイズ | mode_medoid | 解釈 |
|---|---|---:|---|---|
| τ=0.7 L0 Diff | `L0_M2_de637691` | 225 | `$v0 = $v0 concat $v1` | concat 文単独 |
| τ=0.7 L0 Brother | `L0_M2_86060283` | 130 | `$v0 = $v0 concat $v1` | concat (兄弟も同型) |
| τ=0.7 L1 Diff | `L1_M2_8d1d824c` | 282 | `$v0 = $v0 concat $v1` | リテラル抽象化で集約 |

→ concat 連結は **どの depth でも `$v = $v.concat($v)` という核心構造** が代表値になる。 サイズによる構造変化は少ない。

#### 例 2: `for-in` 反復 (素朴版、 pattern 1 とは別系統)

| cell | 代表クラス | サイズ | mode_medoid | 解釈 |
|---|---|---:|---|---|
| τ=0.7 L0 Diff | `L0_M2_f0ed05cf` | 174 | `for var $v0 in $v1 var $v2 = $v1 $v0` | hasOwnProperty なしの for-in 反復 |
| τ=0.7 L0 ExParent | `L0_M2_cd95ed71` | 172 | `for var $v0 in $v1 var $v2 = $v1 $v0` | 同上、 内側ブロック含む |
| τ=0.7 L1 ExParent | `L1_M2_81c0bf2a` | 178 | `for var $v0 in $v1 var $v2 = $v1 $v0` | 同上、 リテラル抽象化 |

→ 同じ for-in 反復が **Diff / ExParent / リテラル抽象化** で出現する。 サイズ depth による影響は ExParent でやや大きいサイズ (172 → 178) になる程度。

#### 例 3: `forEach` 呼び出し

| cell | 代表クラス | サイズ | mode_medoid | 解釈 |
|---|---|---:|---|---|
| τ=0.7 L0 Diff | `L0_M2_ddb94110` | 216 | `$v0 forEach function $v1` | forEach 呼び出し単独 |
| τ=0.7 L0 ExParent | `L0_M2_fc91fc79` | 166 | `$v0 forEach function $v1` | 内側ブロック含む |
| τ=0.7 L1 ExParent | `L1_M2_029a3d70` | 172 | `$v0 forEach function $v1` | リテラル抽象化版 |

→ `forEach` も同様。 「**`$v.forEach(function (...) { ... })`** はあるが、 ExParent ではブロック内側まで取り込んだ別クラスに集約。

### 6.2 depth で 「初めて見える」 新規パターン (Diff には無く、 Parent で出現)

#### Parent でしか見えない構造

| cell | 代表クラス | サイズ | mode_medoid | 解釈 |
|---|---|---:|---|---|
| τ=0.7 L0 Parent | `L0_M2_bacc448d` | 138 | `Math tanh - 1 Math tanh 0 Math tanh 1.5` | **数学関数の連続呼び出し** (Math.tanh 等) |
| τ=0.7 L0 Parent | `L0_M2_c85b0946` | 96 | `var $f0 = function var $v0 = 1 $f0 apply $f0 $v0 $v0` | **関数構築 + apply** (高階関数の応用) |
| τ=0.7 L1 Parent | `L1_M2_096375ec` | 262 | `var $f0 = function $v0 this $v1 = $v0 $f0 prototype $f1 = function var $v2 = new $f0` | **クロージャ + prototype + new** (オブジェクト指向構築) |
| τ=0.7 L1 Parent | `L1_M2_5ff4fe1b` | 183 | `var $v0 = $n0 $n1 $n2 ... (大きな数値配列)` | **大規模数値配列の構築** |

→ **Parent depth で初めて出現する** 「関数本体・オブジェクト構築・大規模配列構築」 の新規パターン。 これらは Diff/Brother/ExParent では見えない (文脈が短すぎる)。

### 6.3 Diff 特化の核心抽出

逆に Diff でしか見えない 「**最小単位の API イディオム**」:

| cell | 代表クラス | サイズ | mode_medoid | 解釈 |
|---|---|---:|---|---|
| τ=0.7 L0 Diff | `L0_M2_5b9e2ca0` | 300 | `+ new Date` (s=291) | `+new Date` イディオム単独 |
| τ=0.7 L0 Diff | `L0_M2_88161bda` | 307 | `new Date getTime` (s=186) | `new Date().getTime()` |
| τ=0.7 L0 Diff | `L0_M2_00b1c05a` | 79 | `JSON stringify $v0` | `JSON.stringify($v)` |

→ Diff では **「API 呼び出しのみ」** に焦点が当たり、 イディオム単独で抽出される。 これは 「**性能差要因として既知のイディオム集約**」 として効果的。

### 6.4 抽象化 L0 → L1 の影響

L1 (リテラル抽象化) で **文字列・数値・正規表現がスロット化** され、 同型化が進む:

| L | cell | 代表クラス | サイズ | mode_medoid |
|---|---|---|---:|---|
| 0 | τ=0.7 L0 Diff | `L0_M2_de637691` | 225 | `$v0 = $v0 concat $v1` |
| 1 | τ=0.7 L1 Diff | `L1_M2_8d1d824c` | 282 | `$v0 = $v0 concat $v1` (リテラル抽象化で +57 件) |

| L | cell | 代表クラス | サイズ | mode_medoid |
|---|---|---|---:|---|
| 0 | τ=0.7 L0 Brother | (skeleton 異なる) | — | — |
| 1 | τ=0.7 L1 Brother | `L1_M2_41f54ce1` | 179 | `$v0 replace $r0 $r1 $r0` (正規表現 `$r` 化) |

→ L1 では **正規表現リテラルが `$r` に抽象化** されて、 `replace($r, $r)` 系のパターンが新たに集約される。 これは L0 では別クラスに分散していた事例。

---

## 7. cell 横断観察と paper への含意

### 7.1 サイズ depth と pattern 構造の関係

| depth | 出現する新規パターンの性質 |
|---|---|
| **Diff** | **API イディオム単独** (`+new Date`、 `JSON.stringify($v)`、 `$v.concat($v)` 等)、 最小単位の書き換え |
| **Brother** | **比較構造を伴う表現** (`$v < $v.length`)、 メソッド連鎖 |
| **ExParent** | **メソッド呼び出し全体** (`forEach(function ...)`、 `for-in` 反復)、 内側ブロック構造 |
| **Parent** | **関数構築・オブジェクト指向構造・大規模配列構築**、 制御構造全体 |

→ **「サイズ depth を広げるほど、 より大きな構造単位の新規パターンが見える」**

### 7.2 τ と新規/イディオム比率の関係

| τ | 新規パターン (novel) | 典型イディオム (variant) | ノイズ (noise) |
|---|---:|---:|---:|
| 0.7 | 多い (13-24/30) | 少なめ (4-12/30) | 一定 (0-10/30) |
| 0.9 | 少ない (3-16/30) | 多い (14-27/30) | ほぼゼロ |

→ **τ=0.7 は「新規パターン発見」、 τ=0.9 は「典型イディオム純粋抽出」**

### 7.3 paper §6.3.1 「サイズ・抽象度の組合せ」 への接続

> 「**サイズ depth に応じて、 抽出される新規パターンの構造単位が変わる**: Diff では API イディオム単独 (`+new Date`、 `JSON.stringify` 等)、 Brother では比較構造、 ExParent では `forEach` などのメソッド呼び出し全体、 Parent では関数構築・オブジェクト構築・大規模データ構築のような関数本体レベルの構造が抽出される。 これは提案手法の **サイズ可変設計が、 異なる構造単位の新規パターンを段階的に提示できる** ことを示す」

### 7.4 paper §6.3.2 「得られた新規パターン」 で提示する候補

τ=0.7 / L0 を主軸に、 depth 別に代表的 novel candidate を選定:

| 提示順 | 候補クラス | depth | mode_medoid | カテゴリ |
|---:|---|---|---|---|
| 1 | `L0_M2_de637691` | Diff | `$v0 = $v0 concat $v1` | 配列操作 |
| 2 | `L0_M2_6691a745` | Diff | `var $v0 = $v0 push $v1 $v2 = $v0 join` | 配列操作 (push+join) |
| 3 | `L0_M2_ddb94110` | Diff | `$v0 forEach function $v1` | 高階関数 |
| 4 | `L0_M2_00b1c05a` | Diff (size 79) | `JSON stringify $v0` | API イディオム |
| 5 | `L0_M2_cd95ed71` | ExParent | `for var $v0 in $v1 var $v2 = $v1 $v0` | 素朴 for-in 反復 |
| 6 | `L0_M2_bacc448d` | Parent | `Math tanh - 1 Math tanh 0 Math tanh 1.5` | 数学関数連続呼び出し |
| 7 | `L0_M2_c85b0946` | Parent | `var $f0 = function var $v0 = 1 $f0 apply $f0 $v0 $v0` | 関数構築 + apply |
| 8 | `L1_M2_096375ec` | L1 Parent | `var $f0 = function ... prototype = ...new $f0` | クロージャ + prototype |

これら 8 件で **「サイズ・抽象度の組合せにより見える構造単位の幅」** を示す。

---

## 8. 論文への落とし込み案

### 8.1 該当節

- §6.3.1 「サイズ・抽象度の組合せとパターンの関係」: 本レポート §6 のサイズ別パターン構造の比較
- §6.3.2 「得られた新規パターン」: §7.4 の 8 件を中心に提示

### 8.2 提示する表 (cell 別 novel/variant/noise 集計)

```latex
\begin{table}[t]
\centering
\caption{全 16 設計組合せにおける新規パターン候補 30 件の AI 一次分類集計。 各 cell で 既知 7 パターンの top1 クラスを除外し size ≥ 10 の上位 30 件を抽出した。}
\label{tab:exp-novel-grid}
\footnotesize
\begin{tabular}{c c c r r r}
\toprule
τ & 抽象化 & サイズ & 新規 (novel) & 既知イディオム (variant) & ノイズ (noise) \\
\midrule
\multirow{4}{*}{0.7} & \multirow{4}{*}{0} & Diff & 17 & 12 & 1 \\
& & Brother & 17 & 6 & 7 \\
& & ExParent & 18 & 5 & 7 \\
& & Parent & \textbf{24} & 4 & 2 \\
\midrule
\multirow{4}{*}{0.7} & \multirow{4}{*}{1} & Diff & 14 & 11 & 5 \\
& & Brother & 14 & 8 & 8 \\
& & ExParent & 13 & 7 & 10 \\
& & Parent & \textbf{23} & 7 & 0 \\
\midrule
\multirow{4}{*}{0.9} & \multirow{4}{*}{0} & Diff & 4 & 24 & 2 \\
& & Brother & 6 & 24 & 0 \\
& & ExParent & 5 & 25 & 0 \\
& & Parent & 14 & 16 & 0 \\
\midrule
\multirow{4}{*}{0.9} & \multirow{4}{*}{1} & Diff & 3 & 27 & 0 \\
& & Brother & 6 & 24 & 0 \\
& & ExParent & 10 & 20 & 0 \\
& & Parent & 16 & 14 & 0 \\
\bottomrule
\end{tabular}
\end{table}
```

### 8.3 文章ドラフト (約 700 字)

> 既知 7 パターンに対応しない自動抽出クラスタから、 全 16 設計組合せそれぞれで上位 30 件 (合計 480 件) を新規パターン候補として抽出した。 表 \ref{tab:exp-novel-grid} に AI 一次分類の集計を示す。 τ=0.7 設定では新規候補 (novel) が 13-24 件と多く、 特にサイズ Parent (外側ブロック) では 23-24 件まで増加する。 一方 τ=0.9 設定では典型イディオム (variant) が 14-27 件と多く、 純度の高いクラスタが既知の高頻度書き換え方式 (`+new Date`、 `new Date.getTime()`、 `Math.floor` 等) を抽出する傾向にある。
>
> **サイズ depth による新規パターン構造の変化が顕著**である。 サイズ差分のみ (Diff) では API イディオム単独 (`$v.concat($v)`、 `JSON.stringify($v)`、 `$v.push($v); $s = $v.join()` 等) が抽出される。 サイズ兄弟まで (Brother) では比較構造 (`$v < $v.length`) や連鎖呼び出しが伴う表現が出現する。 サイズ内側ブロックまで (ExParent) では `forEach(function ...)` や `for-in` 反復のような **メソッド呼び出し全体** が抽出される。 サイズ外側ブロックまで (Parent) では関数構築 (`var $f = function ...; $f.apply(...)`)、 オブジェクト指向構築 (クロージャ + prototype)、 大規模数値配列構築のような **関数本体レベルの構造** が新たに見えるようになる。
>
> 抽象化レベルの効果は限定的だが、 L1 (リテラル抽象化) では正規表現リテラルがスロット化されるため `$v.replace($r, $s)` のような正規表現を伴う書き換えパターンが新たに集約される。
>
> これらの結果は、 提案手法の **サイズ可変設計が、 異なる構造単位の新規パターンを段階的に提示できる** ことを示す。 paper §6.3.2 では各サイズの代表的な novel 候補を提示する。

### 8.4 考察セクションへの接続

- §6.3.1 「サイズ・抽象度の組合せとパターンの関係」: 表 \ref{tab:exp-novel-grid} と §6 のパターン構造比較を直接引用
- §6.3.2 「得られた新規パターン」: §7.4 の 8 件を listing 形式で提示
- §6.4 妥当性脅威: noise クラスの存在 (τ=0.7 で 0-10 件)、 AI 一次分類の限界

---

## 9. Diff・Brother の top 20 詳細 (8 cell)

paper §6.3 で Diff と Brother サイズに注目した詳細分析を行うため、 4 (τ, L) × 2 (Diff, Brother) = 8 cell の top 20 candidate を以下に提示する。

### 9.1 τ=0.7 / L0 / Diff (top 20)

| # | クラス ID | size | AI | 既知 | skeleton | mode_medoid (strategy, support) |
|---:|---|---:|---|---:|---|---|
| 1 | `L0_M2_bd5d5c65` | 1,031 | noise | 0 | `*` | `for var $v0 = 0 $v0 < $v1 length $v0 ++ $v2 push $v1 $v0` (medoid, 17) |
| 2 | `L0_M2_88161bda` | 307 | variant | 0 | `new Date *` | `new Date getTime` (mode, 186) |
| 3 | `L0_M2_5b9e2ca0` | 300 | variant | 0 | `+ new Date` | `+ new Date` (mode, 291) |
| 4 | `L0_M2_de637691` | 225 | **novel** | 2 | `$v0 *` | `$v0 = $v0 concat $v1` (medoid, 43) |
| 5 | `L0_M2_6691a745` | 224 | **novel** | 1 | `* $v0 *` | `var $v0 = $v0 push $v1 $v2 = $v0 join` (medoid, 5) |
| 6 | `L0_M2_ddb94110` | 216 | **novel** | 0 | `$v0 * function $v1 *` | `$v0 forEach function $v1` (medoid, 15) |
| 7 | `L0_M2_f0ed05cf` | 174 | **novel** | 0 | `for var $v0 in $v1 *` | `for var $v0 in $v1 var $v2 = $v1 $v0` (medoid, 40) |
| 8 | `L0_U1_42656a5a` | 172 | variant | 0 | `$v0` | `$v0` (mode, 172) |
| 9 | `L0_M2_81ec7bac` | 100 | variant | 0 | `$v0 length` | `$v0 length` (mode, 100) |
| 10 | `L0_M2_4af26804` | 94 | **novel** | 0 | `* $v0 = *` | `var $v0 = $v1 join` (medoid, 7) |
| 11 | `L0_M2_6aa540aa` | 91 | **novel** | 0 | `$v0 *` | `$v0 $v1` (medoid, 43) |
| 12 | `L0_M2_8a0e5571` | 86 | **novel** | 0 | `$v0 $v1 *` | `$v0 $v1 join` (medoid, 13) |
| 13 | `L0_M2_1143a03c` | 82 | variant | 0 | `parseInt $v0` | `parseInt $v0` (mode, 48) |
| 14 | `L0_M2_1934bab3` | 81 | **novel** | 0 | `Object prototype toString call $v0 *` | `Object prototype toString call $v0 === [object Array]` (medoid, 14) |
| 15 | `L0_M2_00b1c05a` | 79 | **novel** | 1 | `JSON *` | `JSON stringify $v0` (medoid, 12) |
| 16 | `L0_M2_51c4c23b` | 78 | variant | 0 | `for var $v0 in $v1` | `for var $v0 in $v1` (mode, 67) |
| 17 | `L0_M2_33e4dbfa` | 76 | **novel** | 0 | `var $f0 = function *` | `var $f0 = function this $v0 = 0 ...` (medoid, 2) |
| 18 | `L0_M2_f9fc0a7e` | 70 | variant | 0 | `Math floor $v0` | `Math floor $v0` (mode, 39) |
| 19 | `L0_M2_8da5c857` | 68 | **novel** | 0 | `a b c *` | `a b c d e join` (medoid, 7) |
| 20 | `L0_M2_b66d9e0f` | 67 | **novel** | 0 | `function $f0 $v0 *` | `function $f0 $v0 return $v1 + $v0 $f0 $v2` (medoid, 1) |

→ **API イディオム単独** (`+new Date`、 `new Date.getTime()`、 `JSON.stringify`、 `parseInt`、 `Math.floor`、 `Object.prototype.toString.call` 等) と **配列操作** (`concat`、 `push.join`、 `forEach`、 `join`) が中心。 トークン数の少ない API パターンが Diff の特徴。

### 9.2 τ=0.7 / L0 / Brother (top 20)

| # | クラス ID | size | AI | 既知 | skeleton | mode_medoid (strategy, support) |
|---:|---|---:|---|---:|---|---|
| 1 | `L0_M2_6d1cdc05` | 989 | novel | 2 | `var $v0 *` | `var $v0 = for var $v1 = 0 $v1 < 10000 $v1 ++ $v0 push $v1 ...` (medoid, 1) |
| 2 | `L0_M2_c3abb8de` | 555 | noise | 0 | `*` | `+ new Date` (medoid, 166) |
| 3 | `L0_M2_86060283` | 130 | **novel** | 3 | `$v0 = * concat *` | `$v0 = $v0 concat $v1` (medoid, 47) |
| 4 | `L0_M2_e8c34c00` | 113 | variant | 0 | `$v0 < $v1 length` | `$v0 < $v1 length` (mode, 97) |
| 5 | `L0_M2_1da1e49e` | 100 | noise | 1 | `*` | `JSON parse JSON stringify $v0` (medoid, 27) |
| 6 | `L0_M2_0df08bc9` | 91 | **novel** | 0 | `Math * - 1 Math * 0 Math * 1.5` | `Math asinh - 1 Math asinh 0 Math asinh 1.5` (medoid, 11) |
| 7 | `L0_M2_259c3a3b` | 88 | **novel** | 0 | `var $v0 $v1 $v2 $v3 $v4 $v5 $v6 $v0 = test $v1 = test2 String p...` | (medoid, 8) |
| 8 | `L0_M2_f7f525fa` | 84 | **novel** | 0 | `$v0 = $v1 $v2 *` | `$v0 = $v0 $v1 join` (medoid, 6) |
| 9 | `L0_M2_293b385d` | 71 | noise | 0 | `*` | `$v0 = a b c d e join` (medoid, 6) |
| 10 | `L0_M2_de3d9551` | 64 | **novel** | 0 | `$v0 hasOwnProperty *` | `$v0 hasOwnProperty a` (medoid, 10) |
| 11 | `L0_M2_e96a06be` | 64 | noise | 0 | `*` | `Math floor $v0` (medoid, 25) |
| 12 | `L0_M2_0b9fe26d` | 62 | **novel** | 0 | `var $v0 = *` | `var $v0 = 1 2 3 4 5 6 7 8 9 var $v1 = 0 for var $v2 in $v0 ...` (medoid, 10) |
| 13 | `L0_M2_27eefb6b` | 58 | **novel** | 0 | `$v0 = new Array *` | `$v0 = new Array` (medoid, 16) |
| 14 | `L0_M2_c44d98c7` | 56 | **novel** | 0 | `Object prototype toString call $v0 === [object *` | `Object prototype toString call $v0 === [object Array]` (medoid, 17) |
| 15 | `L0_M2_46241f0d` | 55 | **novel** | 0 | `var $v0 = $v0 *` | `var $v0 = $v0 push 1 $v0 push 2 ... $v0 push N` (medoid, 5) |
| 16 | `L0_M2_c8df4c3b` | 53 | **novel** | 0 | `$v0 = new String *` | `$v0 = new String` (medoid, 3) |
| 17 | `L0_M2_c147956c` | 53 | **novel** | 0 | `var $v0 = variableValue $v1 $v2 = 1 $v3 = 2 $v4 = * $v5 = *` | (medoid, 5) |
| 18 | `L0_M2_b2e24c8a` | 50 | variant | 0 | `$v0 unshift` | `$v0 unshift` (mode, 50) |
| 19 | `L0_M2_8acb6d1a` | 49 | variant | 0 | `$v0 shift` | `$v0 shift` (mode, 49) |
| 20 | `L0_U1_41efc340` | 45 | variant | 0 | `$v0` | `$v0` (mode, 45) |

→ Brother では **比較構造** (`$v0 < $v1 length`)、 **メソッド連鎖** (`JSON.parse(JSON.stringify(...))`)、 **連続呼び出し** (`Math.asinh -1 0 1.5`、 `push 1 2 3 4 ...`)、 **構築構造** (`$v = new Array`、 `$v = new String`、 `var ... = $v0 + concat + $v1`) が顕著。 Diff では見えなかった 「**メソッドの前後関係**」 が現れる。

### 9.3 τ=0.7 / L1 / Diff (top 20)

| # | クラス ID | size | AI | 既知 | skeleton | mode_medoid (strategy, support) |
|---:|---|---:|---|---:|---|---|
| 1 | `L1_M2_7b4a05ae` | 1,240 | noise | 0 | `*` | `for var $v0 = $n0 $v0 < $v1 length $v0 ++ $v2 push $v1 $v0` (medoid, 17) |
| 2 | `L1_M2_589a3467` | 964 | noise | 5 | `*` | `var $v0 = $v0 push $s0 var $v1 = $v0 join` (medoid, 29) |
| 3 | `L1_M2_88161bda` | 307 | variant | 0 | `new Date *` | `new Date getTime` (mode, 186) |
| 4 | `L1_M2_5b9e2ca0` | 300 | variant | 0 | `+ new Date` | `+ new Date` (mode, 291) |
| 5 | `L1_M2_8d1d824c` | 282 | **novel** | 2 | `$v0 *` | `$v0 = $v0 concat $v1` (medoid, 43) |
| 6 | `L1_M2_f70c814b` | 252 | noise | 0 | `*` | `replace $r0 $r1 $r0 $r2` (medoid, 24) |
| 7 | `L1_U1_da201bdd` | 231 | variant | 0 | `$n0` | `$n0` (mode, 231) |
| 8 | `L1_M2_106be3d6` | 224 | **novel** | 0 | `$v0 * function *` | `$v0 forEach function $v1` (medoid, 15) |
| 9 | `L1_M2_1935af5b` | 220 | noise | 0 | `*` | `$v0 replace $r0 $r1 $r0 $s0` (medoid, 43) |
| 10 | `L1_M2_e69558e4` | 178 | **novel** | 0 | `var $v0 *` | `var $v0 = $n0` (medoid, 7) |
| 11 | `L1_M2_f0ed05cf` | 174 | **novel** | 0 | `for var $v0 in $v1 *` | `for var $v0 in $v1 var $v2 = $v1 $v0` (medoid, 40) |
| 12 | `L1_U1_42656a5a` | 172 | variant | 0 | `$v0` | `$v0` (mode, 172) |
| 13 | `L1_M2_30c7067a` | 158 | **novel** | 0 | `* $f0 *` | `var $f0 = function $v0 this $v1 = $v0 var $v2 = new $f0 $n0` (medoid, 4) |
| 14 | `L1_M2_d3a0a016` | 149 | variant | 0 | `$r0 $r1 $r0 test $v0` | `$r0 $r1 $r0 test $v0` (mode, 84) |
| 15 | `L1_M2_1cc0b257` | 139 | **novel** | 0 | `var $v0 = $r0 $r1 $r0 *` | `var $v0 = $r0 $r1 $r0 $v0 test $v1` (medoid, 9) |
| 16 | `L1_M2_94c8b3b1` | 109 | **novel** | 2 | `$v0 match $r0 $r1 $r0 *` | `$v0 match $r0 $r1 $r0` (medoid, 20) |
| 17 | `L1_M2_bd0a8c68` | 107 | variant | 0 | `$s0` | `$s0` (mode, 107) |
| 18 | `L1_M2_81ec7bac` | 100 | variant | 0 | `$v0 length` | `$v0 length` (mode, 100) |
| 19 | `L1_M2_d5ae4742` | 93 | variant | 0 | `$v0 hasOwnProperty $s0` | `$v0 hasOwnProperty $s0` (mode, 58) |
| 20 | `L1_M2_345f4655` | 92 | **novel** | 0 | `var $v0 = new RegExp *` | `var $v0 = new RegExp $s0 $s1 $v0` (medoid, 4) |

→ L1 リテラル抽象化により **正規表現を伴うパターン** (`$r0 test $v0`、 `$v0 match $r0 $r1`、 `$v0 replace $r0 $r1 $r0 $s0`、 `new RegExp $s0`) が新規に集約される。 数値リテラルや文字列もスロット化される。

### 9.4 τ=0.7 / L1 / Brother (top 20)

| # | クラス ID | size | AI | 既知 | skeleton | mode_medoid (strategy, support) |
|---:|---|---:|---|---:|---|---|
| 1 | `L1_M2_c61f8e7d` | 780 | noise | 10 | `*` | `var $v0 = $s0 var $v1 = $v0 replace $r0 $r1 $r0 $s1` (medoid, 1) |
| 2 | `L1_M2_9ecde0c2` | 598 | noise | 0 | `*` | `$v0 = $s0 $s1 $s2 ... join` (medoid, 1) |
| 3 | `L1_M2_07026714` | 558 | noise | 0 | `*` | `+ new Date` (medoid, 166) |
| 4 | `L1_M2_41f54ce1` | 179 | **novel** | 0 | `* $r0 *` | `$v0 replace $r0 $r1 $r0` (medoid, 44) |
| 5 | `L1_M2_6bda4f58` | 157 | **novel** | 0 | `var $v0 = *` | `var $v0 = $n0 $n1 ... (大規模数値列)` (medoid, 3) |
| 6 | `L1_M2_66108a34` | 136 | **novel** | 0 | `function $f0 *` | `function $f0 $v0 this $v1 = $v0 $f0 prototype $f1 = function` (medoid, 1) |
| 7 | `L1_M2_eea91864` | 133 | noise | 0 | `*` | `$r0 $r1 $r0 test $v0` (medoid, 39) |
| 8 | `L1_M2_76ca7b7b` | 115 | **novel** | 6 | `$v0 * $r0 *` | `$v0 match $r0 $r1 $r0` (medoid, 9) |
| 9 | `L1_M2_e8c34c00` | 113 | variant | 0 | `$v0 < $v1 length` | `$v0 < $v1 length` (mode, 97) |
| 10 | `L1_M2_06241be4` | 109 | **novel** | 0 | `var $v0 = *` | `var $v0 = $v0 $n0 = $n0 $v0 $n1 = $n2 ...` (medoid, 1) |
| 11 | `L1_M2_1da1e49e` | 100 | noise | 1 | `*` | `JSON parse JSON stringify $v0` (medoid, 27) |
| 12 | `L1_M2_f391b64d` | 91 | **novel** | 0 | `new RegExp *` | `new RegExp $s0 $s1 test` (medoid, 6) |
| 13 | `L1_U1_2f3a27f0` | 90 | variant | 0 | `$n0` | `$n0` (mode, 90) |
| 14 | `L1_M2_259c3a3b` | 88 | **novel** | 0 | `var $v0 $v1 $v2 $v3 $v4 $v5 $v6 $v0 = $s0 $v1 = $s1 String p...` | (medoid, 8) |
| 15 | `L1_M2_488ab43b` | 85 | variant | 0 | `$v0 = new String $s0` | `$v0 = new String $s0` (mode, 45) |
| 16 | `L1_M2_2b21135d` | 81 | **novel** | 0 | `var $v0 = *` | `var $v0 = $n0 $n1 ... $v0 forEach function` (medoid, 4) |
| 17 | `L1_M2_1f65a107` | 81 | variant | 0 | `$v0 hasOwnProperty $s0` | `$v0 hasOwnProperty $s0` (mode, 54) |
| 18 | `L1_U1_3a308305` | 77 | variant | 0 | `$s0` | `$s0` (mode, 77) |
| 19 | `L1_M2_8d24f351` | 70 | noise | 0 | `*` | `Math floor $v0` (medoid, 25) |
| 20 | `L1_M2_39677b82` | 63 | **novel** | 0 | `var $f0 = function *` | `var $f0 = function $v0 $v1 this $v2 = $v0 this $v3 = $v1 ...` (medoid, 1) |

→ L1 Brother では **正規表現 + 関数構築** が複合した新規パターンが顕著。 `replace($r, $s)` 連鎖、 オブジェクト指向構築 (`function ... prototype ... new`)、 大規模数値配列が含まれる。

### 9.5 τ=0.9 / L0 / Diff (top 20)

| # | クラス ID | size | AI | 既知 | skeleton | mode_medoid (strategy, support) |
|---:|---|---:|---|---:|---|---|
| 1 | `L0_M2_86cf3203` | 291 | variant | 0 | `+ new Date` | `+ new Date` (mode, 291) |
| 2 | `L0_M2_07ab15d6` | 177 | variant | 0 | `new Date getTime` | `new Date getTime` (mode, 177) |
| 3 | `L0_U1_42656a5a` | 172 | variant | 0 | `$v0` | `$v0` (mode, 172) |
| 4 | `L0_M2_81ec7bac` | 100 | variant | 0 | `$v0 length` | `$v0 length` (mode, 100) |
| 5 | `L0_M2_6aa540aa` | 91 | **novel** | 0 | `$v0 *` | `$v0 $v1` (medoid, 43) |
| 6 | `L0_M2_bcce8e0c` | 65 | variant | 0 | `for var $v0 in $v1` | `for var $v0 in $v1` (mode, 65) |
| 7 | `L0_U1_be4e182d` | 62 | variant | 0 | `$f0` | `$f0` (mode, 62) |
| 8 | `L0_M2_40aab7e7` | 58 | variant | 0 | `for var $v0 in $v1 var $v2 = $v1 *` | `for var $v0 in $v1 var $v2 = $v1 $v0` (mode, 37) |
| 9 | `L0_U1_94c3289b` | 50 | variant | 0 | `unshift` | `unshift` (mode, 50) |
| 10 | `L0_U1_dd11eb0c` | 49 | variant | 0 | `search` | `search` (mode, 49) |
| 11 | `L0_M2_a1b5c7b8` | 48 | variant | 0 | `parseInt $v0` | `parseInt $v0` (mode, 48) |
| 12 | `L0_U1_ca9caac1` | 47 | variant | 0 | `shift` | `shift` (mode, 47) |
| 13 | `L0_M2_3548a6d7` | 43 | variant | 0 | `for var $v0 in $v1 $v1 $v0` | `for var $v0 in $v1 $v1 $v0` (mode, 34) |
| 14 | `L0_M2_5bf8416b` | 42 | variant | 0 | `for var $v0 in $v1 $v2 += $v1 $v0` | `for var $v0 in $v1 $v2 += $v1 $v0` (mode, 40) |
| 15 | `L0_M2_4af6204b` | 41 | **novel** | 0 | `$v0 $v1 $v2 *` | `$v0 $v1 join` (medoid, 10) |
| 16 | `L0_U1_62ac79aa` | 40 | variant | 0 | `$f0` | `$f0` (mode, 40) |
| 17 | `L0_M2_a3c53c76` | 39 | variant | 0 | `Math floor $v0` | `Math floor $v0` (mode, 39) |
| 18 | `L0_U1_7b419d33` | 39 | variant | 0 | `parseInt` | `parseInt` (mode, 39) |
| 19 | `L0_M2_1649c165` | 38 | variant | 0 | `new $f0` | `new $f0` (mode, 38) |
| 20 | `L0_M2_8e222dfa` | 37 | variant | 0 | `... $v0 ... $v1` | `... $v0 ... $v1` (mode, 30) |

→ τ=0.9 / Diff では **典型イディオムが純粋クラスとして抽出** (`+new Date` 291件全員一致、 `new Date.getTime()` 177件全員一致、 `parseInt`、 `Math.floor`、 `unshift`、 `shift`、 `search`)。 U1 クラスも多く出現 (`$v0`, `$f0`, `unshift`, `parseInt`, `search`, `shift` 等の単独トークン)。

### 9.6 τ=0.9 / L0 / Brother (top 20)

| # | クラス ID | size | AI | 既知 | skeleton | mode_medoid (strategy, support) |
|---:|---|---:|---|---:|---|---|
| 1 | `L0_M2_03b780e3` | 178 | variant | 0 | `new Date getTime` | `new Date getTime` (mode, 178) |
| 2 | `L0_M2_11a85746` | 164 | variant | 0 | `+ new Date` | `+ new Date` (mode, 164) |
| 3 | `L0_M2_d029e2b9` | 113 | variant | 0 | `$v0 = + new Date` | `$v0 = + new Date` (mode, 113) |
| 4 | `L0_M2_38298615` | 95 | variant | 0 | `$v0 < $v1 length` | `$v0 < $v1 length` (mode, 95) |
| 5 | `L0_M2_0e53bea3` | 59 | **novel** | 0 | `$v0 = $v1 $v2 *` | `$v0 = $v0 $v1 join` (medoid, 4) |
| 6 | `L0_M2_b2e24c8a` | 50 | variant | 0 | `$v0 unshift` | `$v0 unshift` (mode, 50) |
| 7 | `L0_M2_8acb6d1a` | 49 | variant | 0 | `$v0 shift` | `$v0 shift` (mode, 49) |
| 8 | `L0_M2_de33b925` | 46 | **novel** | 0 | `var $v0 $v1 $v2 $v3 $v4 $v5 $v6 $v0 = test $v1 = test2 String p...` | (medoid, 8) |
| 9 | `L0_U1_41efc340` | 45 | variant | 0 | `$v0` | `$v0` (mode, 45) |
| 10 | `L0_M2_6cd8ae80` | 38 | variant | 0 | `$v0 search` | `$v0 search` (mode, 38) |
| 11 | `L0_M2_6fc26387` | 36 | variant | 0 | `$v0 split length < 2` | `$v0 split length < 2` (mode, 36) |
| 12 | `L0_M2_1a41b730` | 35 | variant | 0 | `Number new Date` | `Number new Date` (mode, 35) |
| 13 | `L0_M2_5299c16e` | 33 | variant | 0 | `$v0 = $v0 concat $v1` | `$v0 = $v0 concat $v1` (mode, 33) |
| 14 | `L0_M2_b50159fd` | 32 | variant | 0 | `$v0 map` | `$v0 map` (mode, 32) |
| 15 | `L0_M2_c305e2ed` | 31 | variant | 0 | `$v0 $f0` | `$v0 $f0` (mode, 31) |
| 16 | `L0_M2_dcf4fd17` | 31 | variant | 0 | `Math hypot 3 4 5 Math hypot - 3 - 4 - 5 Math hypot 1.5 4.5 5` | (mode, 31) |
| 17 | `L0_M2_6284fc40` | 30 | variant | 0 | `$v0 $v1` | `$v0 $v1` (mode, 20) |
| 18 | `L0_M2_b1bea028` | 30 | variant | 0 | `$v0 constructor toString === Array constructor toString` | (mode, 30) |
| 19 | `L0_M2_bee5718d` | 29 | **novel** | 0 | `$f0 apply $f0 $v0 $v0 $v0 *` | `$f0 apply $f0 $v0 $v0 $v0 $v0` (medoid, 6) |
| 20 | `L0_M2_eb742522` | 27 | variant | 0 | `JSON parse JSON stringify $v0` | `JSON parse JSON stringify $v0` (mode, 27) |

→ τ=0.9 Brother では **典型イディオム + 比較構造** (`$v < $v.length`)、 **`Number new Date`** や **`constructor toString === Array.constructor.toString`** など型判定の別形イディオムが顕著。 `Math.hypot 3 4 5` のような数学関数の連続呼び出しが完全一致で抽出される。

### 9.7 τ=0.9 / L1 / Diff (top 20)

| # | クラス ID | size | AI | 既知 | skeleton | mode_medoid (strategy, support) |
|---:|---|---:|---|---:|---|---|
| 1 | `L1_M2_86cf3203` | 291 | variant | 0 | `+ new Date` | `+ new Date` (mode, 291) |
| 2 | `L1_U1_da201bdd` | 231 | variant | 0 | `$n0` | `$n0` (mode, 231) |
| 3 | `L1_M2_07ab15d6` | 177 | variant | 0 | `new Date getTime` | `new Date getTime` (mode, 177) |
| 4 | `L1_U1_42656a5a` | 172 | variant | 0 | `$v0` | `$v0` (mode, 172) |
| 5 | `L1_M2_ea420b81` | 158 | **novel** | 0 | `$s0 $s1 $s2 *` | `$s0 $s1 join $s2` (medoid, 3) |
| 6 | `L1_M2_bd0a8c68` | 107 | variant | 0 | `$s0` | `$s0` (mode, 107) |
| 7 | `L1_M2_81ec7bac` | 100 | variant | 0 | `$v0 length` | `$v0 length` (mode, 100) |
| 8 | `L1_M2_6aa540aa` | 91 | **novel** | 0 | `$v0 *` | `$v0 $v1` (medoid, 43) |
| 9 | `L1_U1_d69ec650` | 82 | variant | 0 | `$s0` | `$s0` (mode, 82) |
| 10 | `L1_M2_ef8a4552` | 81 | variant | 0 | `$r0 $r1 $r0 test $v0` | `$r0 $r1 $r0 test $v0` (mode, 81) |
| 11 | `L1_M2_bcce8e0c` | 65 | variant | 0 | `for var $v0 in $v1` | `for var $v0 in $v1` (mode, 65) |
| 12 | `L1_U1_be4e182d` | 62 | variant | 0 | `$f0` | `$f0` (mode, 62) |
| 13 | `L1_M2_40aab7e7` | 58 | variant | 0 | `for var $v0 in $v1 var $v2 = $v1 *` | (mode, 37) |
| 14 | `L1_M2_a032a8af` | 58 | variant | 0 | `$v0 hasOwnProperty $s0` | `$v0 hasOwnProperty $s0` (mode, 58) |
| 15 | `L1_M2_90808fd9` | 54 | variant | 0 | `$v0 replace $r0 $r1 $r0 $s0` | `$v0 replace $r0 $r1 $r0 $s0` (mode, 43) |
| 16 | `L1_U1_94c3289b` | 50 | variant | 0 | `unshift` | `unshift` (mode, 50) |
| 17 | `L1_M2_f7ace801` | 49 | variant | 0 | `for var $v0 = $n0 $v0 < $n1 $v0 ++` | (mode, 46) |
| 18 | `L1_U1_dd11eb0c` | 49 | variant | 0 | `search` | `search` (mode, 49) |
| 19 | `L1_M2_a1b5c7b8` | 48 | variant | 0 | `parseInt $v0` | `parseInt $v0` (mode, 48) |
| 20 | `L1_M2_da550a5b` | 47 | variant | 0 | `new String $s0` | `new String $s0` (mode, 47) |

→ L1 で **正規表現 + 文字列リテラル抽象化** により、 `replace $r0 $r1 $r0 $s0` や `new String $s0` のような書き換えパターンが純粋クラスとして抽出される。 U1 クラス (`$s0`, `$n0`, `$v0`, `$f0`、 メソッド名単独) が複数 top に出現。

### 9.8 τ=0.9 / L1 / Brother (top 20)

| # | クラス ID | size | AI | 既知 | skeleton | mode_medoid (strategy, support) |
|---:|---|---:|---|---:|---|---|
| 1 | `L1_M2_03b780e3` | 178 | variant | 0 | `new Date getTime` | `new Date getTime` (mode, 178) |
| 2 | `L1_M2_11a85746` | 164 | variant | 0 | `+ new Date` | `+ new Date` (mode, 164) |
| 3 | `L1_M2_7cbb3685` | 132 | **novel** | 0 | `$v0 = $s0 *` | `$v0 = $s0 $s1 $s2 ... join` (medoid, 1) |
| 4 | `L1_M2_95e3b730` | 118 | **novel** | 0 | `var $v0 = * $v1 = $n0 $v1 < $n1 $v1 ++ $v0 push *` | (medoid, 1) |
| 5 | `L1_M2_d029e2b9` | 113 | variant | 0 | `$v0 = + new Date` | `$v0 = + new Date` (mode, 113) |
| 6 | `L1_M2_38298615` | 95 | variant | 0 | `$v0 < $v1 length` | `$v0 < $v1 length` (mode, 95) |
| 7 | `L1_U1_2f3a27f0` | 90 | variant | 0 | `$n0` | `$n0` (mode, 90) |
| 8 | `L1_U1_3a308305` | 77 | variant | 0 | `$s0` | `$s0` (mode, 77) |
| 9 | `L1_M2_0e53bea3` | 59 | **novel** | 0 | `$v0 = $v1 $v2 $v3 *` | `$v0 = $v0 $v1 join` (medoid, 4) |
| 10 | `L1_M2_9142b0b6` | 54 | variant | 0 | `for var $v0 = $n0 $v0 < $n1 $v0 ++` | (mode, 43) |
| 11 | `L1_M2_9e6f9cda` | 54 | variant | 0 | `$v0 hasOwnProperty $s0` | `$v0 hasOwnProperty $s0` (mode, 54) |
| 12 | `L1_M2_f5da5ecb` | 54 | variant | 0 | `$s0` | `$s0` (mode, 54) |
| 13 | `L1_M2_b2e24c8a` | 50 | variant | 0 | `$v0 unshift` | `$v0 unshift` (mode, 50) |
| 14 | `L1_M2_8acb6d1a` | 49 | variant | 0 | `$v0 shift` | `$v0 shift` (mode, 49) |
| 15 | `L1_M2_de33b925` | 46 | **novel** | 0 | `var $v0 $v1 $v2 $v3 $v4 $v5 $v6 $v0 = $s0 $v1 = $s1 String p...` | (medoid, 8) |
| 16 | `L1_M2_b9f9b722` | 45 | variant | 0 | `$v0 = new String $s0` | `$v0 = new String $s0` (mode, 45) |
| 17 | `L1_M2_11d69e4a` | 45 | **novel** | 0 | `$s0 *` | `$s0 $s1` (medoid, 13) |
| 18 | `L1_U1_41efc340` | 45 | variant | 0 | `$v0` | `$v0` (mode, 45) |
| 19 | `L1_M2_ce8576a0` | 44 | variant | 0 | `$v0 replace $r0 $r1 $r0` | `$v0 replace $r0 $r1 $r0` (mode, 44) |
| 20 | `L1_M2_6cd8ae80` | 38 | variant | 0 | `$v0 search` | `$v0 search` (mode, 38) |

→ τ=0.9 L1 Brother では **多数のリテラル文字列を含む書き換え** (`var $v0 = $s0 var $v1 = $s1 String p...`)、 **for ループ + push** の典型構造、 そして **`new String($s)`** や **`hasOwnProperty($s)`** のような API + リテラルの組合せが純粋に抽出される。

---

## 10. Diff vs Brother 横断比較のまとめ

### 10.1 size 最大クラスの比較 (τ=0.7 系)

| cell | size 最大 クラス | AI | 代表 mode_medoid |
|---|---|---|---|
| τ=0.7 L0 Diff | `L0_M2_bd5d5c65` (1,031) | **noise** | for ループ |
| τ=0.7 L0 Brother | `L0_M2_6d1cdc05` (989) | **novel** | for ループ複数連結 |
| τ=0.7 L1 Diff | `L1_M2_7b4a05ae` (1,240) | **noise** | for ループ + push |
| τ=0.7 L1 Brother | `L1_M2_c61f8e7d` (780) | **noise** | replace 系 (multi) |

→ τ=0.7 では **Diff の size 最大は noise が多い** (skeleton=`*` で多様性)。 Brother では novel か別の noise だが、 性質はやや異なる。

### 10.2 Diff の novel カテゴリ vs Brother の novel カテゴリ

| カテゴリ | Diff で顕著 | Brother で顕著 |
|---|---|---|
| API 単独イディオム | `+new Date`、 `new Date.getTime()`、 `JSON.stringify`、 `parseInt`、 `Math.floor` | (Diff よりは弱い、 Brother は文脈を伴う) |
| 配列操作 | `$v.concat($v)`、 `$v.push().join()`、 `$v.forEach(function)` | `$v < $v.length` 比較を含む、 `$v.push(1).push(2)...` 連続 |
| 制御構造 | `for var $v in $v ...` (素朴 for-in 反復) | for ループ複数連結、 `Math.asinh` 連続呼び出し |
| 構築構造 | (Diff では稀) | `new Array`、 `new String`、 関数構築 + `apply` |
| 型判定 | `Object.prototype.toString.call($v) === [object Array]` | `$v.constructor.toString === Array.constructor.toString` 等の別形 |

→ **Brother は Diff より 「比較構造」 「連続呼び出し」 「構築構造」 が見える**。 Diff は最小単位の API イディオムを抽出する。

### 10.3 τ=0.9 系の傾向 (Diff・Brother 共通)

- τ=0.9 はどちらの depth でも variant 中心。 noise はほぼ消滅
- Diff: `+new Date` (291件)、 `new Date.getTime()` (177件) のような **大規模純粋イディオム**
- Brother: `$v < $v.length` (95件)、 `Number new Date` (35件) のような **構文付き純粋イディオム**

### 10.4 paper §6.3 への含意

> 「**サイズ depth に応じて、 同じデータセットから異なる粒度・性質の新規パターンが抽出される**: Diff では `+new Date` や `JSON.stringify` のような最小単位 API イディオム、 Brother では `$v < $v.length` のような比較構造や `new Array` のような構築構造、 `Object.prototype.toString.call($v) === [object T]` のような型判定の別形が見える」

paper §6.3.2 「得られた新規パターン」 では、 Diff と Brother それぞれの代表的 novel 候補を表で対比提示することで、 サイズ可変設計の有効性を示せる。

---

## 補足: 出力ファイル

| パス | 内容 |
|---|---|
| `outputs/scam/approach_minimum/analysis/E6_novel_candidates.csv` | 全 16 cell × 30 = **480 行** |
| `outputs/scam/approach_minimum/analysis/E6_novel_representatives.json` | 詳細 (skeleton 完全版、 mode_medoid 完全版、 fast 側 AST サンプル 3 件、 全 mb_id) |
