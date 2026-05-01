# hayaLab — Project Overview for AI Agents

## What is this project?

JavaScriptマイクロベンチマーク（slow/fast実装ペア）を対象に、GumTreeによるAST差分解析とパターン抽出を行うPythonライブラリ。
パフォーマンス差異に関連する構文パターンを抽出・統合することが主目的。

## Architecture

```
src/hayalab/      ← 再利用可能なライブラリ（純粋ロジック。I/O・パス決定はしない）
experiments/      ← 実験ランナー（I/O・パス・形式・手順を定義し hayalab を呼び出す）
data/             ← 入出力データ（スキーマ変更時は下流互換を確認）
outputs/          ← 実験・解析結果（パス命名規則を安定させる）
codeql/           ← CodeQL関連（クエリ・スクリプト・出力）
```

依存方向: `experiments → hayalab` のみ。逆方向の import は禁止。

## Key Modules

| モジュール | 役割 |
|---|---|
| `hayalab.gumtree` | GumTree コマンドの Python ラッパー。AST パース・差分取得 |
| `hayalab.pattern` | 差分ブロックからの構文パターン抽出（For/While/If 等の extractor 群） |
| `hayalab.classes` | データモデル（`ASTNode`, `SyntaxFeature`, `NodePosition` 等） |
| `hayalab.abst` | コード抽象化ユーティリティ |
| `hayalab.config` | 設定値 |
| `hayalab.utils` | 汎用ユーティリティ（ファイル I/O 等） |

## Tech Stack

- Python 3.13+（`uv` で環境管理）
- tree-sitter / tree-sitter-javascript（AST パース）
- GumTree（AST 差分）
- Babel parser（JavaScript AST、experiments 側）
- CodeQL（静的解析クエリ）
- Ruff（lint + format）、pre-commit

## Execution

```bash
uv run python experiments/<topic>/<script>.py   # 実験スクリプト実行
uv run ruff check src/                           # lint
uv run ruff format src/                          # format
```

---

## AI Agent Workspace

`.agent/` がこのプロジェクトにおける AI エージェント設定の正規置き場。
各ファイルの役割と使うタイミングを以下に示す。

### File Map

| パス | 役割 | 使うタイミング |
|---|---|---|
| `AGENT.md`（このファイル） | プロジェクト概要・ワークスペース全体の案内 | 常時（エントリポイント） |
| `.agent/agent-instructions.md` | 常時適用するルール・境界規約・設計規約 | 常時 |
| `.agent/instructions/python-research.md` | Python・実験スクリプト編集時の追加ルール | `.py` ファイル編集時 |
| `.agent/instructions/codeql-query.md` | CodeQL クエリ編集時の追加ルール | `.ql` ファイル編集時 |
| `.agent/prompts/` | 再利用プロンプト集（`bug-investigation`, `implementation-plan` 等） | ユーザーが明示的に参照を求めた時 |
| `.agent/skills/` | 再利用スキル定義（複数ステップの手順） | ユーザーがスキル名で呼び出した時 |
| `.agent/agents/` | Claude Code サブエージェント定義 | Claude Code が自動読み込み |
| `.agent/plans/` | 計画書の出力先（`YYYY-MM-DD-<topic>.md` 形式） | 計画作成を求められた時に書き出す |

### Tool-specific Entry Points

各ツールが読み込む設定ファイルはシンボリックリンクで `.agent/` の内容を参照している。

| ツール | 読み込むファイル | 実体 |
|---|---|---|
| Claude Code | `CLAUDE.md` | `AGENT.md`（このファイル） |
| GitHub Copilot | `.github/copilot-instructions.md` | `.agent/agent-instructions.md` |

### Claude Code–specific Features

Claude Code はこのプロジェクトで以下の機能を持つ。

**Subagents** (`.agent/agents/` = `.claude/agents/` via symlink)
- `test-writer` — `src/hayalab/` のモジュールに対する pytest を自動生成
- `code-reviewer` — 境界規約・API安定性・再現性・Ruff準拠を優先度順にレビュー

**Hooks** (`.claude/hooks/`)
- Python ファイル編集後に `ruff check --fix` + `ruff format` を自動実行

**Skills** (`.agent/skills/`)
- `codeql-regression-check` — CodeQL クエリ変更の precision/recall リスクをレビュー

---

<!-- Claude Code 向け指示ファイルの読み込み。@import 構文を解釈しないツールはこのブロックを無視してください。 -->
@.agent/agent-instructions.md
@.agent/instructions/python-research.md
@.agent/instructions/codeql-query.md
@.agent/instructions/granularity-analysis.md
