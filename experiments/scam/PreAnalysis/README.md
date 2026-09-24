# Slow Pattern Detection — 実験ランナー

## RQ1：そもそもマイクロベンチマークに従来研究で示されるような低速コードパターンは slow 側に存在するか

Selakovic & Pradel (2016) が定義した 10 種類の低速 JavaScript パターン（`target.md`）を、
`data/processed/MBDiff.json` の `base_ast`（slow 側）と `head_ast`（fast 側）の両方に対して
部分木マッチングで検出する。

`base_ast` にヒットし `head_ast` にヒットしなかったレコードは、slow → fast の書き換えで
当該パターンが解消されたことを意味する。

## 検出方式

パターンは `patterns/slow_patterns.json` に宣言的なノード制約の木として定義する。
マッチングロジックは `hayalab.scam.match.tree_pattern` にある。

### パターン定義 JSON の形式

```json
{
  "version": 1,
  "ignore_names": ["(", ")", "[", "]", "{", "}", ",", ";", ".", "\"", "'"],
  "patterns": [
    { "id": 2, "key": "...", "description": "...", "source": "...", "root": { /* ノード仕様 */ } }
  ]
}
```

ノード仕様のキー:

| キー | 意味 |
|---|---|
| `name` | ノード型。省略 or `"*"` で任意。配列で「いずれか」、`{"regex": "..."}` で正規表現 |
| `value` | ノード値。同上のシンタックス。**省略＝任意**（変数名を問わない） |
| `text` | `code[begin:end]` との照合 |
| `children` | 子ノード仕様の配列。省略＝子を問わない |
| `children_mode` | `"subsequence"`（既定）/ `"exact"` |
| `match` | `"child"`（既定、直下）/ `"descendant"`（任意の深さの子孫） |
| `optional` | `true` なら不在でもマッチ成立（`exact` では未対応） |
| `bind` | 捕捉名。同名 `bind` 同士は `code[begin:end]` の一致を要求（同一変数の照合） |

意味論:

- 既定の `subsequence` では、仕様に書いた子が「この順序で出現する」ことのみを要求する。
  記号トークン（`(`, `,`, `)` 等）は書く必要がない。
- `children_mode: "exact"` のときのみ `ignore_names` が効き、記号を除いた子リストが
  仕様と完全一致することを要求する（引数個数の厳密化に使う）。
- 演算子は `name` が演算子文字列そのものなので、`{"name": ["==", "==="]}` のように書けば制約になる。
- 空文字列リテラルはクォートのみを子に持つ `string` ノードなので、
  `{"name": "string", "children_mode": "exact", "children": []}` で表現できる。

## 実行方法

```bash
uv run python experiments/scam/PreAnalysis/run.py \
    --input data/processed/MBDiff.json \
    --output-dir outputs/scam/PreAnalysis \
    --patterns 1,2,3,4,5,6,7,8,9,10
```

## 引数

| 引数 | デフォルト | 説明 |
|---|---|---|
| `--input` | `data/processed/MBDiff.json` | 入力 JSON ファイルのパス |
| `--output-dir` | `outputs/scam/PreAnalysis` | 出力ディレクトリ |
| `--patterns` | `1,2,3,4,5,6,7,8,9,10` | 処理対象のパターン番号（カンマ区切り） |
| `--spec` | `patterns/slow_patterns.json` | パターン定義 JSON のパス |

## 出力ファイル

```
outputs/scam/PreAnalysis/
├── base_hits.jsonl        # base_ast にヒットした全件（head_hit フラグ付き）
├── base_only_hits.jsonl   # base_ast にヒットし head_ast にヒットしなかった件
└── summary.json           # パターン別の base_hit_count / base_only_hit_count
```

jsonl の 1 行は `mb_id`, `target_id`, `base_count`, `head_count`, `head_hit`,
`snippet`, `base_code`, `head_code`。同一 `(mb_id, target_id)` は 1 行に集約される。

## パターン定義の検証

`outputs/tmp/target_previous_ast.json` の参照 AST に対し、各パターンが自身にマッチし
他パターンに誤マッチしないことを確認する:

```bash
uv run python experiments/scam/PreAnalysis/validate_patterns.py
```

## アーキテクチャ

- `hayalab.scam.match.tree_pattern` — パターン仕様のロードと部分木マッチング（純粋ロジック）
- `hayalab.scam.match.base` — `PatternMatch` データモデル
- `run.py` — CLI・パス決定・ストリーミング読み込み・出力書き出し

境界規約: 純粋ロジックは `hayalab.scam.*` に置き I/O を持たない。パス決定とファイル書き出しは
`run.py` のみが担当する（AGENT.md の Boundary Rules）。
