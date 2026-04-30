# AI Agent Operations Guide

このドキュメントは、hayaLab で AI Agent（VSCode Copilot, Antigravity, Claude等）を最大限活用するための実運用ガイドです。

## 1. 現在の構成（このリポジトリ）

- 常時ルール: `.agent/agent-instructions.md`
- ファイル種別ルール: `.agent/instructions/*.md`
- 再利用プロンプト: `.agent/prompts/*.md`
- 再利用スキル: `.agent/skills/*.md`
- 計画書出力先: `.agent/plans/`

## 2. AI Agent の使い分け

基本方針:
- 常時守るルールは `agent-instructions.md` に書く。
- 対象ファイル依存のルールは `instructions/` に書く。
- 反復する問い合わせは `prompts/` に切り出す。
- 複数ステップの再利用手順は `skills/` に切り出す。

このリポジトリで使う主要プロンプト:
- `requirements-clarification`: 要件が曖昧なときに、目的・制約・受け入れ条件を整理する。
- `implementation-plan`: 実装前に、手順・検証・リスクを含む実行計画を作る。
- `code-understanding`: 既存コードの責務、依存、リスクを短時間で把握する。
- `safe-refactor`: 挙動を変えずに最小差分でリファクタ方針を立てる。
- `bug-investigation`: 再現、原因切り分け、最小修正、回帰防止まで進める。
- `risk-first-code-review`: バグ・回帰・テスト不足を優先してレビューする。
- `plan-to-file`: 計画書を `.agent/plans/` 配下へ所定フォーマットで保存する。

## 3. 品質を上げる依頼テンプレート

以下の5点を毎回入れると、提案品質が安定する。

1. 目的（何を達成したいか）
2. 入力コンテキスト（対象ファイル、前提データ）
3. 制約（最小差分、API維持、安全性、実行環境）
4. 期待する出力形式（手順、diff、レビュー指摘など）
5. 受け入れ条件（完了判定）

## 4. このリポジトリ向けチェックリスト

- Python変更: `pyproject.toml` の Ruff 設定準拠か。
- Python実行/依存管理: `uv run` / `uv add` を使っているか。
- Query変更: 何を変更し、何を検出するかを説明しているか。
- 出力変更: データ形式や下流互換性への影響を明記しているか。
- パス前提: GitHub 環境での実行を前提に成立するか。

## 5. 安全運用

- 個人トークンや機密情報はコミットしない。
- 不要な広域変更を避け、レビューしやすい最小差分を維持する。
- ワークフローを変えた場合は、変更内容を明確に記録する。

## 6. 実装方針（どこに何を書くか）

配置判断の一次ソース:

- 常時ルール（リポジトリ全体の責務・境界）: `.agent/agent-instructions.md`
- Python 編集時のルール（適用範囲付き）: `.agent/instructions/python-research.md`
- CodeQL クエリ編集時のルール: `.agent/instructions/codeql-query.md`

ライブラリ設計の補助ドキュメント:

- `hayalab` のAPI/モジュール概要: `src/hayalab/README.md`

運用上の意図:

- `src/hayalab/**` は再利用可能な処理を実装し、I/O とパス決定は原則しない。
- `experiments/**` は実験固有の実行（入出力・パス・形式・手順）を定義し、`hayalab` を呼び出して組み立てる。


