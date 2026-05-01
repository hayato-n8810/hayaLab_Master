# hayaLab
研究の痕跡

### 主要機能

- **AST差分解析**: GumTreeを使用したJavaScriptコードの構造的差分抽出
- **差分ブロック抽出**: 検出された差分操作から意味のあるコードブロックを切り出し
- **特徴抽出**: 差分ブロックから階層構造を保持した特徴パターンを抽出
- **パターン統合**: 同一の特徴を持つマイクロベンチマークをグループ化

## AI Agent 運用

### 設定ファイルの構成

AI Agent（VSCode Copilot, Claude 等）の動作ルールやコンテキスト指示は `.agent/` に集約されています。
シンボリックリンクが機能しない環境では `.agent/` を直接参照してください。

| パス | 役割 |
|---|---|
| `.agent/agent-instructions.md` | 常時適用するルール・境界規約 |
| `.agent/instructions/*.md` | ファイル種別ごとの追加ルール |
| `.agent/prompts/*.md` | 再利用プロンプト集 |
| `.agent/skills/*.md` | 再利用スキル（複数ステップの手順） |
| `.agent/plans/` | 計画書の出力先（`YYYY-MM-DD-<topic>.md`） |

### 主要プロンプト

| プロンプト名 | 用途 |
|---|---|
| `implementation-plan` | 実装前に手順・検証・リスクを含む計画を作る |
| `code-understanding` | 既存コードの責務・依存・リスクを短時間で把握する |
| `safe-refactor` | 挙動を変えずに最小差分でリファクタ方針を立てる |
| `bug-investigation` | 再現・原因切り分け・最小修正・回帰防止まで進める |
| `plan-to-file` | 計画書を `.agent/plans/` へ所定フォーマットで保存する |

### 依頼テンプレート

以下の5点を含めると提案品質が安定する。

1. 目的（何を達成したいか）
2. 入力コンテキスト（対象ファイル、前提データ）
3. 制約（最小差分、API維持、安全性、実行環境）
4. 期待する出力形式（手順、diff、レビュー指摘など）
5. 受け入れ条件（完了判定）

### 変更前チェックリスト

- Python変更: `pyproject.toml` の Ruff 設定に準拠しているか
- Python実行/依存管理: `uv run` / `uv add` を使っているか
- CodeQLクエリ変更: 何を変更し、何を検出するかを説明しているか
- 出力変更: データ形式や下流互換性への影響を明記しているか
- 機密情報: 個人トークンや認証情報をコミットしていないか

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
