# hayalab ライブラリ

JavaScriptマイクロベンチマークのAST差分解析とパターン抽出を行うPythonライブラリ

## 概要

hayalabは、JavaScriptコードのマイクロベンチマーク（slow/fast実装対）に対してGumTreeを用いたAST差分解析を行い、パフォーマンス差異に関連する特徴パターンを抽出・統合するためのツールキットです。

## インストール

```bash
# プロジェクトルートから
pip install -e .
```

## モジュール構成

### `hayalab.gumtree` - GumTree関連処理

#### `gumtree_command`
GumTreeコマンドのPythonラッパー

```python
import hayalab

# JavaScriptコードをGumTreeでパース
ast = hayalab.gum_parse(js_code)

# 2つのASTの差分を抽出
diff = hayalab.gum_diff(slow_ast, fast_ast)
```

**主要な関数:**
- `gum_parse(code: str) -> AST`: JavaScriptコードをASTに変換
- `gum_diff(src_ast: AST, dst_ast: AST) -> GumDiff`: 2つのAST間の差分を抽出

#### `diff_block`
gumtreeにおける差分から意味のあるコードブロックを抽出

```python
from hayalab.gumtree.diff_block import cut_diff_blocks

# 差分ブロックを抽出（インデックスでソート済み）
diff_blocks = cut_diff_blocks(
    ast=slow_ast,
    actions=diff.actions,
    target_actions=["update-node", "insert-tree"]  # 特定のアクションのみ対象
)
```

**主要な関数:**
- `cut_diff_blocks(ast, actions, target_actions=None) -> list[ASTNode]`: 差分ノードを抽出・統合
- `base_diff_blocks(ast, actions) -> list[dict]`: 差分ブロックを個別に取得
- `head_diff_blocks(ast, actions) -> list[dict]`: 差分のルートノードのみ取得

**パラメータ:**
- `target_actions`: 対象とする差分操作（例: `["insert-tree", "delete-tree", "update-node"]`）
  - `None`の場合は全ての操作を対象

#### `feature_extractor`
差分ブロックから階層構造を保持した特徴パターンを抽出

```python
from hayalab.gumtree.feature_extractor import DiffFeatureExtractor

# デフォルトの抽出器で初期化
extractor = DiffFeatureExtractor()

# カスタム抽出器を追加
from hayalab.gumtree.extractors import ForStatementExtractor
extractor.add_extractor(ForStatementExtractor())

# 特徴抽出
feature = extractor.extract_features(diff_block)
pattern_dict = feature.to_dict()
```

**主要なクラス:**
- `DiffFeatureExtractor`: 特徴抽出のメインクラス
  - `extract_features(diff_block: list[ASTNode]) -> FeatureNode`: 特徴を抽出

#### `extractors` - 構文別特徴抽出器

各JavaScript構文に対応した特徴抽出器を提供

**利用可能な抽出器:**
- `ForStatementExtractor`: `for`文の特徴抽出
- `ForInStatementExtractor`: `for...in`文の特徴抽出
- `WhileStatementExtractor`: `while`文の特徴抽出
- `IfStatementExtractor`: `if`文の特徴抽出
- `PropertyIdentifierExtractor`: プロパティアクセスの特徴抽出
- `NewExpressionExtractor`: `new`式の特徴抽出

**カスタム抽出器の作成:**

```python
from hayalab.gumtree.extractors import FeatureExtractor, ExtractionContext
from hayalab.classes.feature import FeatureNode, NodePosition

class MyCustomExtractor(FeatureExtractor):
    def can_extract(self, node: ASTNode) -> bool:
        """このノードを処理できるか判定"""
        return node.type == "MyCustomType"
    
    def extract(self, context: ExtractionContext, parent_feature: FeatureNode) -> bool:
        """特徴を抽出して親ノードに追加"""
        # 処理ロジックを実装
        return True  # 処理した場合はTrue
```

### `hayalab.pattern` - パターン統合

同一の特徴パターンを持つデータをグループ化

```python
from hayalab.pattern.integrate import integrate_patterns

# 複数のマイクロベンチマークの特徴データ
data = [
    {"id": 1, "feature": [{"type": "diff_root", ...}]},
    {"id": 2, "feature": [{"type": "diff_root", ...}]},
    {"id": 3, "feature": [{"type": "diff_root", ...}]},
]

# 同一パターンを統合
integrated = integrate_patterns(data)
# => [
#     {
#         "feature": [...],
#         "origin_num": 2,
#         "ids": [1, 3]
#     },
#     ...
# ]
```

**主要な関数:**
- `integrate_patterns(data: list[dict]) -> list[dict]`: 特徴パターンを統合
  - 入力: `{"id": int, "feature": list[dict]}`のリスト
  - 出力: `{"feature": list[dict], "origin_num": int, "ids": list[int]}`のリスト（`origin_num`で降順ソート）

### `hayalab.abst` - コード抽象化

JavaScriptコードの抽象化処理

```python
from hayalab.abst.abst import abst

# JavaScriptコードを抽象化
abstracted_code = abst(js_code)
```

**主要な関数:**
- `abst(code: str) -> str`: JavaScriptコードを抽象化

### `hayalab.classes` - データクラス

#### `Feature`
特徴ノードのデータクラス（Pydanticモデル）

```python
from hayalab.classes.feature import FeatureNode, NodePosition

feature = FeatureNode(
    feature_type="for_statement",
    position=NodePosition.ROOT,
    depth=1,
    order=0,
    value="optional_value",
    children=[]
)
```

**主要なクラス:**
- `FeatureNode`: 特徴ノードを表現
  - `feature_type`: ノードの種類
  - `position`: ノードの位置（ROOT, BODY, TEST, UPDATE等）
  - `depth`: 深さ
  - `order`: 兄弟ノード内での順序
  - `value`: オプション値
  - `children`: 子ノードのリスト

#### `GumTree`
GumTreeのAST/差分データクラス（Pydanticモデル）

```python
from hayalab.classes.gumtree import AST, ASTNode, GumDiff, GumAction

# ASTノードのアクセス
node = ast.tree[0]
print(node.type)      # ノードタイプ
print(node.label)     # ラベル
print(node.parent)    # 親ノードのインデックスリスト
print(node.begin)     # 開始位置
print(node.end)       # 終了位置
```

### `hayalab.utils` - ユーティリティ

#### `utils.file`
ファイルIO操作

```python
import hayalab

# JSONファイルの読み書き
data = hayalab.read_json("path/to/file.json")
hayalab.write_json("path/to/output.json", data)

# テキストファイルの読み書き
text = hayalab.read_file("path/to/file.")
hayalab.write_file("path/to/output.", text)
```

**主要な関数:**
- `read_json(filepath: str) -> dict | list`: JSONファイル読み込み
- `write_json(filepath: str, data: dict | list)`: JSONファイル書き込み
- `read_file(filepath: str) -> str`: ファイル読み込み
- `write_file(filepath: str, text: str)`: ファイル書き込み

#### `utils.ast`
Babel AST関連操作

```python
import hayalab

# JavaScriptコードをBabel ASTに変換
babel_ast = hayalab.babel_parse(js_code)
```

**主要な関数:**
- `babel_parse(code: str) -> dict`: JavaScriptコードをBabel ASTに変換

### `hayalab.config` - 設定

プロジェクトパスの定義

```python
import hayalab

print(hayalab.ROOT)        # プロジェクトルート
print(hayalab.DATA)        # dataディレクトリ
print(hayalab.RAW)         # data/raw
print(hayalab.PROCESSED)   # data/processed
print(hayalab.OUTPUT)      # output
print(hayalab.EXPERIMENTS) # experiments
```

## 使用例

### 完全なワークフロー例

```python
import hayalab
from hayalab.gumtree.feature_extractor import DiffFeatureExtractor
from hayalab.pattern.integrate import integrate_patterns

# 1. マイクロベンチマークデータの読み込み
mb_data = hayalab.read_json(f"{hayalab.DATA}/raw/codes.json")

results = []
for item in mb_data:
    # 2. AST解析
    slow_ast = hayalab.gum_parse(item["slow"])
    fast_ast = hayalab.gum_parse(item["fast"])
    
    # 3. 差分抽出
    diff = hayalab.gum_diff(slow_ast, fast_ast)
    
    if diff is None:
        continue
    
    # 4. 差分ブロック抽出
    diff_block = hayalab.cut_diff_blocks(slow_ast, diff.actions)
    
    # 5. 特徴抽出
    extractor = DiffFeatureExtractor()
    feature = extractor.extract_features(diff_block)
    
    results.append({
        "id": item["id"],
        "feature": feature.to_dict()
    })

# 6. パターン統合
integrated = integrate_patterns(results)

# 7. 結果保存
hayalab.write_json(f"{hayalab.OUTPUT}/patterns.json", integrated)
```

## 開発ガイド

### 新しい特徴抽出器の追加

1. `hayalab.gumtree.extractors`ディレクトリに新しいファイルを作成
2. `FeatureExtractor`を継承したクラスを実装
3. `can_extract()`と`extract()`メソッドを実装
4. `__init__.py`でエクスポート

### テスト

```bash
# テストスクリプトの実行
uv run python ./experiments/MB_diff/slow_pattern_test.py
```

## ライセンス

プロジェクトルートの[LICENSE](../../LICENSE)を参照してください。
