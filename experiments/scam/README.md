# experiments/scam — SCAM パターン抽出パイプライン

## 概要

JavaScript マイクロベンチマーク (slow/fast) の GumTree 差分から、低速コードパターンを自動抽出する実験パイプライン。`.agent/plans/2026-05-21-pattern-extraction-pipeline-design.md` に基づき、レビュー（`.agent/plans/review_scam_approach.md`）の指摘を反映した版。

ロジック本体は `src/hayalab/pattern/` に純粋関数として実装され、本ディレクトリの各スクリプトは I/O とパス決定、および並列化・多重化のみを担当する。`hayalab/` 側は単一処理のみを公開し、複数パターンに対する一括計算（並列・多重化）は experiments 側で組む方針。

## ディレクトリ構成

```
experiments/scam/
├── README.md                            ← 本ファイル
├── approach/                            ← パイプライン本体（連番スクリプト）
│   ├── 01_cutout.py                     ← Stage 1: AST 切り出し
│   ├── 02_abstract.py                   ← Stage 2: 抽象化（A0..A3）
│   ├── 03_detection.py                  ← Stage 3: 検出結果（マッチ MB id 集合）計算
│   ├── 04_aggregate.py                  ← Stage 4: 同値類集約
│   └── 05_score_select.py               ← Stage 5: サイズスコア + depth 選択
├── rq1_size_score_sensitivity.py        ← RQ1: w 感度分析
├── rq2_abstraction_observation.py       ← RQ2: 抽象化レベル観測量
└── rq3_pattern_comparison.py            ← RQ3: 既存・新規パターン比較
```

各スクリプトは独立して実行可能で、互いを `import` しない。中間結果はすべて `outputs/scam/approach/` 配下の JSON で受け渡す。

## 実行順序

### 前提: 入力データ

- 本番: `data/processed/MBDiff.json`
- テスト: `data/test_data/MBDiff_target.json` (`--test` フラグで指定)

スキーマ: `[{"id": int, "diff": GumDiff, ...}, ...]`

### Stage 1〜5（approach/ ステージチェーン）

#### Stage 1: `approach/01_cutout.py`

- **入力**: MBDiff JSON
- **出力**: `outputs/scam/approach/01_cutouts.json`
- **処理**: 全 MB について 4 種の depth (L1..L4) で AST 切り出しを行う
- **実行**: `uv run python experiments/scam/approach/01_cutout.py --test`
- **出力スキーマ**:
  ```json
  [{ "mb_id": int,
     "cutouts": { "1": [{Cutout}, ...], "2": [...], "3": [...], "4": [...] } }, ...]
  ```

#### Stage 2: `approach/02_abstract.py`

- **入力**: `01_cutouts.json` + MBDiff JSON (base_ast 参照)
- **出力**: `outputs/scam/approach/02_patterns.json`
- **処理**: 各 cutout × abst_level (0..3) で Pattern を生成
- **実行**: `uv run python experiments/scam/approach/02_abstract.py --test`
- **抽象化レベルの 2 軸定義**:
  | level | bits | literal_generalize | gap_tolerant | クローン型相当 |
  |---|---|---|---|---|
  | A0 | `0b00` | False（既存正規化のまま） | False（厳密 subtree） | Type-1 |
  | A1 | `0b01` | False | True（gap-tolerant 子マッチ） | Type-3 (構造のみ寛容) |
  | A2 | `0b10` | True（リテラル汎化＋識別子は prefix-only） | False | Type-2 |
  | A3 | `0b11` | True | True | Type-3 (Type-2 + 構造寛容) |
  - 軸1 `literal_generalize` = `abst_level >> 1`: リテラルを型クラス (NUM, STR, BOOL, NULL, REGEX) に置換。識別子は A2/A3 で PREFIX_* prefix-only 一致、A0/A1 で完全一致。
  - 軸2 `gap_tolerant` = `abst_level & 1`: 子マッチを「順序保存部分列埋め込み（追加のみ許容）」に切り替え。detect 側で動作する。
- **出力スキーマ**:
  ```json
  [{ "mb_id": int,
     "patterns": { "0": [{Pattern}, ...], "1": [...], "2": [...], "3": [...] } }, ...]
  ```

#### Stage 3: `approach/03_detection.py`

- **入力**: `02_patterns.json` + MBDiff JSON (dataset)
- **出力**: `outputs/scam/approach/03_detection_ids.json`
- **処理**: 各パターンに対してデータセット全体への検出結果（マッチした MB id 集合）を計算。パターン同一性判定用ハッシュ単位で重複排除しつつ、`hayalab.pattern.compute_detection` を 1 パターンずつ呼ぶ。`--workers N` で ProcessPoolExecutor による並列化が可能。
- **検出方式**: 正規表現プリフィルタは廃止し、AST 部分木マッチングのみで判定する。早期棄却用に「ノード型集合プリフィルタ」を導入（パターンが要求するノード型集合が target AST に存在しなければ即 False）。同一識別子整合性は AST マッチングの `theta` バインドで意味的に判定する。
- **抽象化レベルとマッチング**:
  - **識別子マッチ**: `abst_level >> 1` (literal_generalize) が True (A2/A3) なら `PREFIX_*` prefix-only 一致、False (A0/A1) なら `original_value` 完全一致。
  - **子マッチ**: `abst_level & 1` (gap_tolerant) が True (A1/A3) なら順序保存部分列埋め込み（パターン側の全子が target に含まれ、順序を保てば OK; target 側の追加子は無視）。False (A0/A2) なら厳密な zip 一致。
- **実行**:
  - 逐次: `uv run python experiments/scam/approach/03_detection.py --test`
  - 並列: `uv run python experiments/scam/approach/03_detection.py --workers 6`
- **出力スキーマ**: `{ "<パターンを示すハッシュ値>": [<mb_id>, ...], ... }`

#### Stage 4: `approach/04_aggregate.py`

- **入力**: `02_patterns.json` + `03_detection_ids.json`
- **出力**:
  - `outputs/scam/approach/04_equivalence_classes.json`: 同値類本体
  - `outputs/scam/approach/04_class_patterns.json`: 各 class に属するパターンの終端記号列・AST 詳細
- **処理**: 抽象化レベル別に検出結果ベースの同値類集約を行う。同値類本体は class_id・members・detect_id の 3 項目のみ。`members` は ClassMember (mb_id, signature, depth) のリストで、由来 MB とパターン同一性ハッシュの対応を保持する。代表パターン詳細は補助 JSON 経由で取得する設計（class_id ⇄ 抽象度内パターン群の対応は abst_level でキー分け）。
- **実行**: `uv run python experiments/scam/approach/04_aggregate.py --test`
- **同値類本体スキーマ**:
  ```json
  { "0": [{ "class_id": "...",
            "members": [{"mb_id": int, "signature": "...", "depth": int}, ...],
            "detect_id": [<mb_id>, ...] }, ...],
    "1": [...], "2": [...], "3": [...] }
  ```
- **クラスパターン詳細スキーマ**:
  ```json
  { "<abst_level>": {
      "<class_id>": {
        "patterns": [
          { "signature": "...", "mb_id": int, "depth": int, "abst_level": int,
            "terminal_tokens": "var VAR_1 = NUM ;",
            "ast_template": [...] },
          ...
        ]
      },
      ...
    },
    ... }
  ```
  `terminal_tokens` は終端記号列を半角空白で連結した文字列（is_terminal=True のノードのみを順に並べたもの。識別子は A0..A2 で元値、A3 で `PREFIX_*` 表現、抽象リテラルは `NUM` / `STR` / ... のラベルそのもの）。

#### Stage 5: `approach/05_score_select.py`

- **入力**: `01_cutouts.json`
- **出力**: `outputs/scam/approach/05_selections.json`
- **処理**: MB ごとのサイズスコア計算 + 最適 depth L* 選択
- **実行**: `uv run python experiments/scam/approach/05_score_select.py`
- **出力スキーマ**:
  ```json
  [{ "mb_id": int, "optimal_depth": int|null, "optimal_abst_level": null,
     "status": "selected"|"unrepresentable", "equivalence_class_id": null,
     "size_scores": { "1": {SizeScore}, ..., "4": {SizeScore} } }, ...]
  ```

### RQ スクリプト

approach/ の出力を読み込んで分析する。

#### RQ1: `rq1_size_score_sensitivity.py`

- **入力**: `outputs/scam/approach/01_cutouts.json`
- **出力**: `outputs/scam/rq1/rq1_sensitivity.csv`
- **処理**: w ∈ {0.0, 0.25, 0.5, 0.75, 1.0} で各 MB の L* を計算し、選択比率を集計
- **実行**: `uv run python experiments/scam/rq1_size_score_sensitivity.py`

#### RQ2: `rq2_abstraction_observation.py`

- **入力**: `outputs/scam/approach/04_equivalence_classes.json`
- **出力**: `outputs/scam/rq2/rq2_observation.csv` + `rq2_observation.json`
- **処理**: 抽象化レベル別の同値類総数・集約済み数・migration・最大検出結果サイズを算出
- **実行**: `uv run python experiments/scam/rq2_abstraction_observation.py`

#### RQ3: `rq3_pattern_comparison.py`

- **入力**: `04_equivalence_classes.json` + `05_selections.json` + MBDiff JSON + `data/baseline_patterns/*.json`
- **出力**: `outputs/scam/rq3/rq3_classes.json` + `rq3_summary.csv` + `pattern.json`
- **処理**: 同値類の検出結果と baseline パターンの検出結果を Jaccard で比較し、existing/new を分類
- **実行**: `uv run python experiments/scam/rq3_pattern_comparison.py --test --abst-level 2`

## 中間ファイルのスキーマ概要

| ファイル | 主キー | 一貫識別子 |
|---|---|---|
| `01_cutouts.json` | `mb_id` | `mb_id` (MBDiff の `id`)、`node_indices` (`base_ast.tree` のインデックス) |
| `02_patterns.json` | `mb_id` | `mb_id`、`depth`、`abst_level`、`signature`（パターン同一性判定用ハッシュ、内部キー） |
| `03_detection_ids.json` | パターン同一性ハッシュ | ハッシュ → 検出された MB id リストのマッピング専用 |
| `04_equivalence_classes.json` | `abst_level` → `class_id` | `class_id`（同値類識別ハッシュ、内部）+ `detect_id` (検出結果の MB id リスト) |
| `05_selections.json` | `mb_id` | `mb_id` |

`mb_id` は MBDiff の `id` フィールドそのもの。AST ノード識別子は `base_ast.tree` の配列インデックス (`ASTNode.parent` の整数値と同じ体系)。`signature` / `class_id` はハッシュ値のため可読性が低く、ファイル間紐付けの主キーとしては使わない（パターン同一性判定および同値類識別の内部キーとしてのみ使用）。

## 用語

| 表記 | 意味 |
|---|---|
| 検出結果 (`detect_id`) | 単一パターンを全 MB に対して `detect()` した結果としてマッチした MB id 集合 |
| パターン同一性判定用ハッシュ (`Pattern.signature`) | 抽象化済み AST テンプレートから決定論的に算出される 16 文字ハッシュ。同テンプレートのパターンは同ハッシュを持つ |
| 同値類識別ハッシュ (`EquivalenceClass.class_id`) | 同値類のメンバ signature 群から決定論的に算出される 16 文字ハッシュ |
| ClassMember | 同値類のメンバ要素 `(mb_id, signature, depth)`。同 signature が複数 MB から生成された場合に由来 MB を区別するため、メンバはこのタプルで重複排除する |
| 検出結果ベース同値判定 | Jaccard 閾値 τ で「2 つのパターンの検出結果」を比較し、近い/同一であれば同値類化する集約方式 |

## 検出方式と RQ2 の判断指標

### 検出方式の選択肢

`hayalab.pattern.detect(pattern, target_ast, prefilter=True)` は引数 `prefilter` で検出方式を切り替えられる。

| prefilter | 内容 | 用途 |
|---|---|---|
| `True`（既定） | ノード型集合プリフィルタで早期棄却 → AST 部分木マッチング | 通常運用。本番データでも実用速度 |
| `False` | プリフィルタなし → 全 target ノードに対してマッチング走査（フルマッチ） | プリフィルタの精度検証、デバッグ |

正規表現プリフィルタは廃止された。理由は、抽象化されたノード型（`Function`, `VariableDeclaration`, `NUM` 等）や同一識別子整合性を字面では正確に判定できないため。AST マッチングの `theta`（slot_id → 実値バインド）で意味的判定を行う。

### RQ2 の判断指標として残した観点（旧 flag の役割）

同値類集約後の各クラスを評価する際の観点として、以下のラベル化を考慮していた:

| 候補ラベル | 条件（イメージ） | 解釈 |
|---|---|---|
| `no_detection` | `len(detect_id) == 0` | パターンが自分自身すら検出できていない（実装バグ・誤抽象化の兆候） |
| `self_only` | `detect_id == {元 MB id}` | 由来 MB しか当たらず、汎化されていない |
| `member_only` | `detect_id == 全メンバの mb_id 集合` | パターン群の元 MB のみ正しく検出（厳密一致） |
| `extended` | `detect_id ⊃ メンバの mb_id 集合` | 元 MB に加えて他 MB も検出（パターンとして一般化に成功） |
| `over_abstracted` | `len(detect_id) / |D| > 閾値` | データセット全体の高比率を検出してしまっている（汎化しすぎ） |

これらは `len(detect_id)` と `members[i].mb_id` の集合から派生計算可能なので、`EquivalenceClass` 本体には保持せず、必要な分析時にその場で計算する設計とした（`flag` フィールドは削除済み）。RQ2 で抽象化レベル選択の判断に追加観点として用いる場合は、`AbstractionObservation` に類似観測量を追加する形で拡張する。

## 注意事項・既知の制限

- **依存方向**: `experiments → src/hayalab` のみ。`experiments/scam/` 内のファイルは互いに `import` しない。各スクリプトは独立実行が前提。
- **hayalab の API 設計**: 各処理は「1 入力 → 1 出力」の単一処理として公開し、並列化・多重化は experiments 側で組む。`compute_detection` も単一パターン × データセットに限定。
- **並列化**: Stage 3 (`03_detection.py`) は `--workers N` で ProcessPoolExecutor 経由の並列化に対応。ワーカー初期化時に MBDiff を 1 回ロードし、以降は共有データセットを参照する。
- **set フィールド**: Pydantic の `model_dump(mode="json")` は `set` を JSON 化できないため、`diff_node_indices` と `detect_id` は各スクリプトで `sorted(list(...))` 変換を明示的に行う。
- **中間 JSON サイズ**: 本番 (`MBDiff.json`、約 29809 件) では `02_patterns.json` が 4 depth × 4 abst_level × MB 数 ≈ 数十万 Pattern になり、数百 MB になりうる。必要なら gzip 圧縮を後付けで検討。
- **`baseline_patterns/`**: 既存研究のアンチパターンを `Pattern` 形式で格納するディレクトリ。空の場合は RQ3 で全てが `new` に分類される。
