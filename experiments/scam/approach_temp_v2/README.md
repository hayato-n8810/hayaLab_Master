# approach_temp_v2 — `docs/aggregate.md` M0/M1/M2/M3 比較実装

## 目的

`approach_temp/` に実装された **M3 LGG / M4 HAC-TED / M5 DBSCAN** に対し、
本実験は `docs/aggregate.md` で計画されている 4 手法

| 手法 | aggregate.md での位置づけ | 本ディレクトリでの実装 |
|---|---|---|
| **M0** Ordered Hash | クローン検出 Type-1 系の完全一致集約 | `methods/m0_ordered_hash.py` |
| **M1** Sequence Bigram | 隣接ノード bigram fingerprint（exact / Jaccard） | `methods/m1_seq_bigram.py` |
| **M2** N-gram | M1 と同じトークン化で n を任意化した n-gram fingerprint | `methods/m2_path_ngram.py` |
| **M3** Anti-Unification (LGG) | approach_temp と同等のアルゴリズム | `methods/m3_antiunify.py` |

を **`outputs/scam/approach/03_abstract/03_abstract_level{0,1,2,3}.json`** に対して走らせ、approach_temp と直接比較可能な形式でクラスタ結果を出力する．

## ディレクトリ構成

```
approach_temp_v2/
├── README.md                  ← 本書
├── ast_node.py                ← NodePayload / TemplateNode / Pattern / TreeNode dataclass
├── cluster.py                 ← UnionFind, class_id 生成, nodes_to_tree
├── loader.py                  ← 03_abstract_level{L}.json → list[Pattern]
├── observe.py                 ← クラスタ → classes_*.json, trajectory_*.json
├── run.py                     ← CLI エントリポイント
└── methods/
    ├── __init__.py
    ├── m0_ordered_hash.py     ← (name, value, parent_name) タプル列 SHA-256 完全一致
    ├── m1_seq_bigram.py       ← 隣接 bigram fingerprint (exact / Jaccard)
    ├── m2_path_ngram.py       ← parent_path 込み n-gram (exact / Jaccard)
    └── m3_antiunify.py        ← LGG 貪欲併合（approach_temp と同パラメータで等価）
```

## 入出力

### 入力

`outputs/scam/approach/03_abstract/03_abstract_level{0,1,2,3}.json`

各ファイルは次のスキーマを持つ:

```json
[
  {
    "id": <mb_id>,
    "cutouts": {
      "Diff":     {"diff_node_indices": [...], "nodes": [<TemplateNode dict>...]},
      "Brother":  {...},
      "ExParent": {...},
      "Parent":   {...}
    }
  },
  ...
]
```

`nodes` の各要素は `TemplateNode.from_dict` が受理する形式（`name`/`value`/`parent_relative` か `parent`/`slot_id`/`variadic`）．

### 出力

approach_temp と同じスキーマで `--output` 配下に出力する:

* `filtered_out.json` — `min_nodes` 未満のため除外された cutout 一覧
* `classes_A{level}_{method}.json` — 4 levels × N methods のクラス情報（class_id, members, depth_profile, representative_ast）
* `trajectory_{method}.json` — 各 cutout の L0..L3 軌跡
* `summary.json` — 実行メタデータ、各セルの n_classes と sizes

これにより `approach_temp/analyze_*.py` の集計スクリプトを再利用して比較分析が可能．

## 実行（参考；本実装では未実行）

```bash
# 全件
uv run python experiments/scam/approach_temp_v2/run.py \
    --input-dir outputs/scam/approach/03_abstract \
    --output outputs/scam/approach_temp_v2 \
    --levels 0 1 2 3 \
    --methods M0 M1 M2 M3

# 6000 件サンプリング（先頭 6000 mb_id を全 level で共有）
uv run python experiments/scam/approach_temp_v2/run.py \
    --input-dir outputs/scam/approach/03_abstract \
    --output outputs/scam/approach_temp_v2_smoke6000 \
    --levels 0 1 2 3 \
    --methods M0 M1 M2 M3 \
    --sample 6000 \
    --workers 40
```

主要オプション:

| オプション | デフォルト | 説明 |
|---|---|---|
| `--m1-mode` | `exact` | M1 の集約モード（`exact` / `jaccard`）|
| `--m1-tau-jaccard` | `0.7` | M1 jaccard モードの類似度閾値 |
| `--m1-include-parent-name` | `False` | M1 トークンに parent_name を追加 |
| `--m2-mode` | `exact` | M2 の集約モード |
| `--m2-n` | `2` | M2 の n-gram サイズ（2=bigram, 3=trigram）|
| `--m2-tau-jaccard` | `0.7` | M2 jaccard モードの閾値 |
| `--m3-tau-sim` | `0.5` | M3 LGG 類似度閾値（approach_temp と同じ） |
| `--m3-kappa` | `3.0` | M3 サイズ比上限 |
| `--m3-rho` | `0.5` | M3 非スロット率下限 |
| `--min-nodes` | `2` | cutout の最小ノード数 |
| `--sample` | `None` | 先頭 N 件の mb_id に絞る（approach_temp の `--sample` と同等）．L0 で確定した mb_id 集合を他レベルにも適用 |
| `--workers` | `1` | exact mode (M0 / M1 exact / M2 exact) の fingerprint 計算を並列化．mb_id 単位 chunk で結果不変．Jaccard と M3 は逐次のまま |

## approach_temp の手法との対応

| approach_temp 名称 | approach_temp_v2 で対応する手法 | 同等性 |
|---|---|---|
| M3 (LGG)        | **M3** (LGG)                                          | パラメータ同一なら同一クラスタを生成 |
| M4 (HAC-TED)    | （対応なし - 純粋ツリー編集距離は v2 には含めない）   | — |
| M5 (DBSCAN on M3 sim) | （対応なし - sim graph 共有が前提のため）       | — |
| —               | **M0** (Ordered Hash)                                 | クローン検出 Type-1 系完全一致集約 |
| —               | **M1** (Sequence Bigram)                              | bag-of-bigrams 順序付き fingerprint |
| —               | **M2** (Path-augmented N-gram)                        | 階層情報付き n-gram |

## M1 / M2 のトークン化規約

M1 と M2 は本研究で以下の共通トークン化規約を採用する．

1. **トークンは ``(name, value)`` の 2 要素タプル**．`parent_name` 等の補助情報は集約鍵に含めない．
2. **value は slot タイプのみに正規化**:
   - `$v0`, `$v1`, ... → `$v`
   - `$f0`, ... → `$f`
   - `$k0`, ... → `$k`
   - `$n0`, ... → `$n`
   - `$s0`, ... → `$s`
   - `$api` はそのまま（既に番号なし）
   - 具体値 (`identifier:String`, `property_identifier:substr` 等) はそのまま
3. **`variadic=True` の TemplateNode は集約鍵から除外**．L2 で導入される `function_like` / `var_decl_stmt` / `var_decl_kw` などの非終端は子要素 arity が揺らぐため、`aggregate.md` §3 M3 の "variadic ノードは子要素揺らぎを吸収する" を bigram/n-gram 系で実現する近似として、当該ノード自体を集約鍵から外す．**子サブツリーのトークンは含む**．

これにより：

- スロット番号の偶然差 (同 cutout 内での変数登場順) を吸収できる
- `function_like` の中身がわずかに違うだけで別クラスタに分散する現象を抑制できる
- M0 (ordered hash; name/value/parent_name の三要素＋slot 番号保持) との差異が明確になり、M0 = M1 縮退問題を解消する

M1 と M2 の違いは **n-gram の n のみ** とする（M1 = 2-gram, M2 = 任意 n; デフォルト 2）．`aggregate.md` 原案では M2 が path-augmented だったが、本実験では「同一トークン化で n を変えた感度比較」に再定義した．

## 関連研究準拠の推奨閾値

集約パラメータのデフォルト値は本研究の経験ではなく **関連研究で広く採用される値** に合わせる方針．

| パラメータ | 推奨値 | 文献根拠 |
|---|---:|---|
| `--min-nodes` | **2** | 1 ノードの cutout は構造情報を持たない（パターン抽出対象外） |
| `min_support`（クラスタ最小サイズ）<sup>※</sup> | **2** | Refazer (Rolim et al., ICSE 2017) — "need at least two instances to generalize"; Getafix (Bader et al., FSE 2019); LASE (Meng et al., ICSE 2013) も 2–3 を採用 |
| `--m1-tau-jaccard` / `--m2-tau-jaccard` | **0.7** | SourcererCC (Sajnani et al., ICSE 2016) — Type-2/Type-3 クローン検出標準値; NiCad (Roy & Cordy, ICPC 2008) の UPI 30% (≒ similarity 70%); Roy & Cordy 2009 survey の de facto 標準 |
| `--m3-tau-sim` | **0.5** | LASE (Meng et al., ICSE 2013) と approach_temp の経験値 — LGG 系は slot 化で値差を吸収するため lower threshold が適合 |
| 感度分析（jaccard） | **0.5 / 0.7 / 0.9** | 緩・標準・厳の 3 段階で表現クラスタの安定性を検証 |

<sup>※</sup> `min_support` は集約スクリプト側ではなく分析スクリプト (`analyze_pattern_representation.py --min-support`) でフィルタする．集約手法自体は |C|=1 のシングルトンも生成する（それを後段でフィルタする方針）．

**0.9 を中心値にしない理由**: 0.9 以上の Jaccard 閾値は **Type-1 クローン検出寄り**（ほぼ完全一致のみ集約）になり、本実装の `--m1-mode exact` / `--m2-mode exact` と縮退してしまう．Type-2/Type-3 のラベル差を許容する近傍集約には **0.7** が標準．

## 並列化の方針

| 手法 / モード | 並列化 | 結果不変保証 | 理由 |
|---|:---:|:---:|---|
| M0 ordered hash | ◯ | ◯ | Pattern → key が独立・決定的．mb_id 単位 chunk で並列化しバケット集約 |
| M1 exact | ◯ | ◯ | 同上．bigram fingerprint は Pattern 内で閉じる |
| M2 exact | ◯ | ◯ | 同上．path-hash の値は祖先 name のみで決まる |
| **M1 jaccard** | **◯** | **◯** | ペア Jaccard を chunk 並列化．chunks を `i_start` 順に結合 → candidates list が逐次経路と bit-identical |
| **M2 jaccard** | **◯** | **◯** | 同上 |
| **M3 LGG** | **◯** | **◯** | ペア sim 計算を chunk 並列化．chunk 結果を `i_start` 順に結合 → candidates list が逐次経路と bit-identical → greedy merge も同一順序 |

「`--workers N`（N ≥ 2）を指定しても、`N = 1` と同一の `class_id` / メンバー集合を生成する」ことが exact mode の設計契約．これは:

1. Pattern → key 関数 (`canonical_key`, `fingerprint_key`) が **副作用なし・入力のみ依存**
2. バケット集約 (`{key: [cutout_id]}`) が dict 結合のみで順序依存しない
3. 最終的な `class_id` は **canonical key の SHA-256** から生成されるため、key 計算順とは無関係

の 3 点で保証される．`parallel.py` の worker は `ProcessPoolExecutor` を使い、macOS/Windows の `spawn` start method でも正しく動作するよう **module-level 関数 + 明示 kwargs 引数**で picklability を確保している．

## 設計上の留意点

1. **集約鍵に punctuation は含まれない**: `03_abstract` 出力は既に punctuation 除外済みのため、M0/M1/M2 の鍵生成側で追加フィルタは不要．
2. **slot_id は集約鍵で「具体値ではない」マーカーとして機能**: M0/M1/M2 では `value` フィールドを鍵に含めるが、抽象化後の slot 値（`$v0` 等）は cutout 内で正規化されているため、同じ位置の slot 同士は鍵が一致する．
3. **M0/M1/M2 の代表 AST**: 同一クラス内のメンバは（exact mode の場合）構造が一致するので、メンバの先頭 cutout の AST をそのまま代表とする．LGG のような汎化テンプレートは生成しない．
4. **M3 の代表 AST**: `cluster_m3.last_representatives` に Union-Find ルートごとの LGG 木を保持しておき、classes_*.json では DFS で TemplateNode dict 列にシリアライズする．approach_temp との形式互換のため、`origin_index` は DFS 訪問順の合成インデックスを採用（元 cutout の origin_index ではない）．
5. **monotonicity check**: L0/L1/L2/L3 で同じクラスにいたメンバが下位レベルで割れていないか確認する．M0/M1/M2 は構造的に refinement なので原理的に違反 0 だが、M3 は貪欲 LGG のタイブレーク非決定性により少数発生し得る（approach_temp と同様）．
6. **計算量**: M0/M1/M2 の exact mode は $O(N \cdot n)$ で大規模対応容易．Jaccard mode と M3 は $O(N^2)$ なので、本ディレクトリは LSH/MinHash 等の高速化は含めない（aggregate.md §3 M1 で言及される LSH 併用は本実装の範囲外）．
7. **比較解析**: 出力 JSON のスキーマが approach_temp と同じなので、`experiments/scam/approach_temp/analyze_results.py`, `analyze_depth_distribution.py`, `analyze_detail.py` などをそのまま流用できる（`BASE` パスを `approach_temp_v2` に向けるだけ）．

## 比較研究での想定使い方

1. `--methods M3` を `--m3-tau-sim 0.5 --m3-kappa 3.0 --m3-rho 0.5` で実行して approach_temp の M3 と一致することを確認（baseline 校正）．
2. `--methods M0 M1 M2 M3` を実行して 4 手法 × 4 抽象度 = 16 セルの結果を取得．
3. approach_temp の `_analysis_summary.json` と本 v2 の同集計を merge して、aggregate.md 手法（M0/M1/M2）と approach_temp 手法（M4 HAC-TED, M5 DBSCAN）の双方を 1 つの比較表に展開する．
4. 特に **M0 → M1 → M2 → M3** の集約力勾配（aggregate.md §4「階層情報を使うほど集約は厳しくなる」が実データで成立するか）を観察し、approach_temp の M4 / M5 と比較する．

## 関連ドキュメント

* `docs/aggregate.md` — 本実験が実装する集約手法群の設計
* `docs/aggregation_design.md` — approach_temp の集約フレームワーク全体設計
* `docs/abstraction_design.md` — L0–L3 抽象化階層
* `docs/result_approach_tempM345.md` — approach_temp の M3/M4/M5 結果分析
* `docs/result_approach_temp345_detail.md` — approach_temp の M3/M4 詳細分析
