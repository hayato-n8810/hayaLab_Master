# hayaLab
研究の痕跡

### 主要機能

- **AST差分解析**: GumTreeを使用したJavaScriptコードの構造的差分抽出
- **差分ブロック抽出**: 検出された差分操作から意味のあるコードブロックを切り出し
- **特徴抽出**: 差分ブロックから階層構造を保持した特徴パターンを抽出
- **パターン統合**: 同一の特徴を持つマイクロベンチマークをグループ化

## AI設定

プロジェクトにおける各種AI Agent（VSCode Copilot, Antigravity, Claude等）の動作ルールやコンテキスト指示のマスターファイルは、すべて `.agent/` ディレクトリに集約されています。AI設定のマスターは `.agent/` にあるため、環境等によりシンボリックリンクが機能しない場合は `.agent/` を直接参照してください。

## ディレクトリ構成

```
hayaLab/
├── data/                    # 入力データ・中間データ（raw/processed）
│   ├── raw/                 # 元データ（codes.json, patterns.json）
│   └── processed/           # 処理済みデータ（MB_separate.json等）
├── experiments/             # 実験スクリプト（入出力・パス・手順のオーケストレーション）
├── outputs/                 # 実験/解析結果の出力先
├── src/hayalab/            # メインパッケージ
│   ├── abst/               # コード抽象化モジュール
│   ├── classes/            # データクラス定義（Feature, GumTree）
│   ├── config/             # パス設定
│   ├── gumtree/            # GumTree関連処理
│   │   └── extractors/             # 各構文の特徴抽出器
│   ├── pattern/            # パターン統合
│   └── utils/              # ユーティリティ（babelAST, ファイルIO）
├── QL/                      # CodeQL クエリ・実行補助
├── targets/                 # 解析対象（GitHub / microbenchmark）
├── docker-compose.yml      # Docker環境設定
├── Dockerfile             # コンテナイメージ定義
└── pyproject.toml         # プロジェクト設定
```

## セットアップ

### 依存ツール

- Python 3.13+
- [uv](https://github.com/astral-sh/uv) (Pythonパッケージマネージャー)
- Docker & Docker Compose（コンテナ環境を使用する場合）
- GumTree 4.0.0-beta2（Dockerイメージに含有）
- Node.js 22.x & pnpm

### ローカル環境での実行

```bash
# 依存パッケージのインストール
uv sync

# ファイル実行
uv run python ./experiments/MB_diff/MB_diff.py
```

### Docker環境での実行

```bash
# コンテナの起動
docker compose up -d

# コンテナに入る
docker container exec -it hayalab bash

# スクリプトの実行
python3 ./experiments/MB_diff/slow_pattern.py
```

## パッケージ管理

```bash
# パッケージの追加
uv add {ライブラリ名}

# パッケージの削除
uv remove {ライブラリ名}

# 開発用パッケージの追加
uv add --dev {ライブラリ名}
```

## コード品質

```bash
# Ruffによるリント・フォーマット
uv run ruff check .
uv run ruff format .

# pre-commitフックの実行
uv run pre-commit run --all-files
```

## ライセンス

このプロジェクトのライセンスについては[LICENSE](LICENSE)を参照してください。

## 著者

hayato-n8810 (s276185@wakayama-u.ac.jp)
