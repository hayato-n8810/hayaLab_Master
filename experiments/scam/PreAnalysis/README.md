# Slow Pattern Detection — 実験ランナー

## RQ1：そもそもマイクロベンチマークに従来研究で示されるような低速コードパターンはslow側に存在するか

Selakovic & Pradel (2016) が定義した 10 種類の低速 JavaScript パターンを`data/processed/MBDiff.json` の `base_ast`（slow 版）に対して検出する。

ただし，fast側は見ないので従来研究のafterに向けた比較になっているかはわからない．一応，変更差分内に該当箇所が含まれているかは見ている

ルールを4項目（詳細は `experiments/scam/PreAnalysis/diff_link.py`）設定し，結果のsample配下のjsonlにおけるdiff_resonにパスした条件を示す．目視で見た限りclear_1_4が従来パターンを前後ともに示している完全パターンである

## 具体的な検出ロジックは .agent/docs/slow_pattern_detection.md を参照

**TODO**：
- fast側に対して従来研究afterか調べる

## 実行方法

### 全件処理

```bash
uv run python experiments/scam/PreAnalysis/run.py \
    --input data/processed/MBDiff.json \
    --output-dir outputs/tmp/slow_patterns \
    --patterns 1,2,3,4,5,6,7,8,9,10 \
    --limit 0
```

### サンプルドライラン（先頭 100 件）

```bash
uv run python experiments/scam/PreAnalysis/run.py \
    --input data/processed/_sample.json \
    --output-dir outputs/tmp/slow_patterns_sample \
    --limit 100
```

### Stage B 無効（Stage A のみ）

```bash
uv run python experiments/scam/PreAnalysis/run.py \
    --input data/processed/MBDiff.json \
    --output-dir outputs/tmp/slow_patterns_stagea \
    --no-stage-b
```

## 引数

| 引数 | デフォルト | 説明 |
|---|---|---|
| `--input` | （必須） | 入力 JSON ファイルのパス |
| `--output-dir` | `outputs/tmp/slow_patterns` | 出力ディレクトリ |
| `--patterns` | `1,2,3,4,5,6,7,8,9,10` | 処理対象のパターン番号（カンマ区切り） |
| `--limit` | `0`（全件） | 先頭 N 件のみ処理（デバッグ用） |
| `--no-stage-b` | （フラグ） | Stage B（diff 連動フィルタ）を無効化 |

## 出力ファイル

```
outputs/tmp/slow_patterns/
├── summary.json              # pattern_id ごとの件数・信頼度別件数・diff_linked 件数
├── matches.jsonl             # 全 PatternMatch（1 行 1 件）
└── samples/
    └── pattern_<1..10>/
        ├── high.jsonl        # 信頼度別サンプル（最大 50 件）
        ├── medium.jsonl
        ├── low.jsonl
        └── representative.md # 上位 3 件のコード断片
```

## フィクスチャビルダー

テスト用フィクスチャを生成する補助スクリプト:

```bash
uv run python experiments/scam/PreAnalysis/build_fixtures.py
```

`outputs/tmp/previous_ast.json` の id_1〜id_10 を、対応するフィクスチャ
ディレクトリに展開する（Phase 2 で `tests/scam/` 整備時に再構成予定）。

## アーキテクチャ

純粋ロジックは `src/hayalab/scam/` に集約済み:

- `hayalab.scam.ast_nav` — フラット AST ナビゲーションヘルパー（純関数群）
- `hayalab.scam.match.{base, p01..p10, apply}` — パターン別 matcher と部分木適用ロジック
- `hayalab.scam.diff_link` — Stage B diff 連動フィルタ (``is_base_covered``, ``apply_diff_link``)

experiments/scam/PreAnalysis/ 側:

- `run.py` — CLI・I/O・パス決定。 hayalab の単体処理を組み合わせて全 MBDiff レコードを処理

境界規約: 純粋ロジックは ``hayalab.scam.*`` に置き I/O を持たない。 並列化・パス決定・
ファイル書き出しは ``run.py`` のみが担当する（agent-instructions.md の Boundary Rules）。
