# hayaLab — Project Overview for AI Agents

## Goal

研究のためのリポジトリ．真理の探究が主目的。

AI エージェントは **correctness（正しさ）・reproducibility（再現性）・minimal diffs（最小差分）** を優先する。

## Architecture

```
src/hayalab/      ← 再利用可能なライブラリ（純粋ロジック。I/O・パス決定はしない）
experiments/      ← 実験ランナー（I/O・パス・形式・手順を定義し hayalab を呼び出す）
data/             ← 入出力データ（raw/processed。スキーマ変更時は下流互換を確認）
outputs/          ← 実験・解析結果（パス命名規則を安定させる）
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
| `hayalab.scam` | SCAM2026 論文用の単体処理要素（ast_nav / diff_link / match / abstract / cluster / representative）。 実行エントリ・並列化・繋ぎは `experiments/scam/` 側 |

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

## Coding Rules

### 全般

- 変更はリクエストのスコープに限定し、最小差分にとどめる。
- 既存 API は明示的な指示がない限り維持する。
- 簡潔なトリックよりも明確な命名を優先する。
- 関数サイズの厳格な制限は設けない。凝集性が向上するならまとめてよい。
- 既存挙動が変わる場合は何が変わったか明示する。テストや動作確認コードの追加は必須ではない。

### Boundary Rules (hayalab vs experiments)

前提:

- `hayalab` は再利用可能な単体処理要素を提供する。1つの処理単位は1関数（または凝集したメソッド群）で閉じさせる。
- `experiments` は実験固有の I/O・パス・形式・実行順序を定義し、`hayalab` を呼び出して振る舞いを組み立てる。

ルール:

- **依存方向**: `experiments → hayalab` のみ。`src/hayalab/**` から `experiments/**` を import してはいけない。
- **I/O 境界**: ライブラリは具体的なパスを決めない。入力は引数で受け取り、結果を返却する。
  - 例外: 低レベル I/O ユーティリティ（例: `hayalab.utils.file`）は許容。ただしパス決定は呼び出し側。
- **パス決定**: どのファイルを読み書きするかは `experiments/**`（または CLI スクリプト）が決める。
- **出力スキーマ**: JSON 構造を変更する場合、下流互換性への影響（キー名・リスト順序・ソート）を明示する。

### Design Conventions for New Code

- ライブラリ API は小さく合成可能に保つ（「何でもできる」関数を増やさない）。
- 失敗モードは明示的かつ一貫させる（`None` 返却・例外・エラーを含む結果オブジェクトのいずれかに統一）。
- 再現性のため、乱数・dict 順序・ファイル列挙順序による非決定性を避ける。必要に応じて sort する。
- 既存の出力パス命名規則（例: `outputs/ql_analysis/...`）は明示的な指示なく変更しない。

---

## Python Rules

適用範囲: `src/**/*.py`, `experiments/**/*.py`

- `pyproject.toml` の Ruff 設定に従う。
- 文字列パス操作よりも `pathlib` を優先する。
- 新規・修正された公開関数には型ヒントを付ける。
- 実務上可能な範囲で I/O と純粋ロジックを分離する。
- Google スタイルの docstring を使う。
- 依存追加と実行は uv コマンド（`uv add`, `uv run`）を使う。
- テキストファイルは UTF-8、`open` には明示的に `encoding` を指定する。
- 設定値でない限り絶対パスをハードコードしない。
- 読み込み前にファイル存在を確認し、書き込み前に出力ディレクトリを作成する。
- CLI スクリプトは可能な限り冪等にする。
- 出力 JSON 構造を変更する場合は後方互換性の影響を応答に明示する。
- シリアライズ出力は決定的な順序を優先する（再現可能な diff のため）。

### Directory Boundaries（どこに何を実装するか）

- **`src/hayalab/**` (ライブラリ)**
  - 再利用可能なロジックを置く。関数は合成可能で焦点を絞る（実務上可能な範囲で1関数 = 1処理単位）。
  - 具体的な入出力パスをここで決めない。データ・パスは引数で受け取り、結果を返す。
  - `experiments/**` を import しない（依存方向: `experiments → hayalab`）。
  - 副作用は最小に。print / logging は opt-in にする（または呼び出し側に委ねる）。

- **`experiments/**` (実験ランナー)**
  - 実験固有のオーケストレーションを置く: CLI 引数、パス選択、I/O 形式、実行順序。
  - コードは薄く保つ: 入力読み込み → `hayalab` 呼び出し → 出力書き込み。
  - 実験の契約として、リポジトリ root 基準のパス（例: `data/`, `outputs/`）をハードコードしてよい。

### I/O and Schema Rules

- ファイル配置の決定権は experiments 側にある。ライブラリはデフォルトで `outputs/**` や `data/**` に書き込まない。
- 新しい出力ファイルを追加する必要がある場合、既存の `outputs/**` 命名規則に従い、名前を安定させる。
- JSON スキーマ変更時は下流互換性（キー名・リスト順序・ソート）を考慮する。

### Experiment Script Structure (`experiments/**/*.py`)

実験スクリプトは「上から読めば全フローが追える」ことを最優先する。抽象化は再利用が発生したときのみ導入する。

#### 必須ルール

1. **`main()` 関数を作らない**: 実行フローは `if __name__ == "__main__":` ブロックに直接書く。モジュールトップレベルに `def main(): ...` を置いて末尾で呼ぶ構造は使わない。
2. **1度しか呼ばれない処理を関数に切り出さない**: 単一の処理ステップは `__main__` ブロック内にインラインで記述する。「リーダブルな名前を付けたいから」だけの理由で関数化しない。
3. **関数として残してよいのは以下のみ**:
   - 複数回呼ばれるユーティリティ（タイムスタンプ生成・パス計算・JSON 保存等）
   - per-entry / per-URL / per-record のワーカー（リトライ・パース・抽出など、ループ内で 1 件ずつ呼ばれる処理）
   - 共通の組み立て処理（payload 構築など、複数箇所で同じ辞書/構造を作る場合）
4. **`__main__` ブロックは「セクションコメント＋線形フロー」で記述**: 区切りコメント (`# --- セクション名 -----`) を入れ、処理ブロックを上から順に並べる。早期終了が必要な箇所では `raise SystemExit(0)` を使ってよい。

#### 推奨パターン

```python
"""モジュール docstring（Google スタイル）。"""

from __future__ import annotations
import ...

# --- 定数（コード冒頭で調整可能なハイパーパラメータ）----
PARAM_A: int = ...

# --- ヘルパー（複数回呼ばれるもののみ）------------------
def _helper_called_many_times(...) -> ...:
    """Google スタイル docstring (Args/Returns/Raises)。"""
    ...

def _worker_per_record(...) -> ...:
    """per-entry の処理（ループ内で呼ばれる）。"""
    ...

# --- メインフロー -----------------------------------------
if __name__ == "__main__":
    # --- セクション 1: パス決定 ---
    ...

    # --- セクション 2: 入力読み込み ---
    ...

    # --- セクション 3: メインループ ---
    for entry in entries:
        _worker_per_record(entry)
        ...

    # --- セクション 4: 出力保存 ---
    ...
```

#### 判断基準（関数化すべきか）

- 「2 回以上呼ばれる？」→ Yes なら関数化
- 「ループ本体になるか？」（per-record 処理）→ Yes なら関数化してテスト/再利用に備える
- 「`__main__` の中で意味のあるまとまりを名前で示したいだけ？」→ No。**セクションコメントで代替**する
- 「失敗時のリカバリ処理が複雑？」→ Yes ならワーカー関数化して `try/except` を整理

---

## CodeQL Query Rules

適用範囲: `QL/query/**/*.ql`

- クエリの意図は明示的に保ち、暗黙の意味変更を避ける。
- クエリ修正時は、何を変えて何が検出されるようになるかを説明する。
- 大規模な書き直しよりも、predicate レベルの小さな修正を優先する。
- 下流解析が依存する出力ラベル・ID 命名規則を維持する。
- ロジックが非自明な箇所に限り、理由をコメントとして残す。
- 出力パス規約は明示的な指示なく変更しない。

---

## Review Checklist

- データ形式・出力スキーマを変えていないか？
- パス前提が GitHub 環境での実行でも有効か？
- 実験はリポジトリ root から再現可能か？

## Plan Output Rules

- ユーザーが計画を求めた場合、`.agent/plans/` に Markdown ファイルとして保存する。
- ファイル名形式: `YYYY-MM-DD-<short-topic>.md`
- 含めるセクション: Goal, Assumptions, Steps, Validation, Risks
- 計画は簡潔・アクション志向に。明示の指示がない限り実装詳細は書かない。

---

## AI Agent Workspace

`.agent/` がこのプロジェクトにおける AI エージェント設定の正規置き場。
各ファイルの役割と使うタイミングを以下に示す。

### File Map

| パス | 役割 | 使うタイミング |
|---|---|---|
| `AGENT.md`（このファイル） | プロジェクト概要・全ルール・ワークスペース案内 | 常時（エントリポイント） |
| `.agent/prompts/` | 再利用プロンプト集（`bug-investigation`, `implementation-plan` 等） | ユーザーが明示的に参照を求めた時 |
| `.agent/skills/` | 再利用スキル定義（複数ステップの手順） | ユーザーがスキル名で呼び出した時 |
| `.agent/agents/` | Claude Code サブエージェント定義 | Claude Code が自動読み込み |
| `.agent/plans/` | 計画書の出力先（`{仕様書ファイル名}/PLAN.md` 形式） | 計画作成を求められた時に書き出す |
| `.agent/docs/` | 実装仕様書置き場（Markdown のみ） | `architect` サブエージェントが読み込む |

### Tool-specific Entry Points

| ツール | 読み込むファイル | 実体 |
|---|---|---|
| Claude Code | `CLAUDE.md` | `AGENT.md`（このファイル、symlink） |

### Claude Code–specific Features

Claude Code はこのプロジェクトで以下の機能を持つ。

**Subagents** (`.agent/agents/` = `.claude/agents/` via symlink)

| エージェント | モデル | 役割 |
|---|---|---|
| `architect` | Opus | `.agent/docs/` の仕様書を読んで `.agent/plans/{topic}/PLAN.md` を作成 |
| `implementer` | Sonnet（inherit） | `PLAN.md` を読んでコードを実装 |
| `test-writer` | — | `src/hayalab/` のモジュールに対する pytest を自動生成 |
| `code-reviewer` | — | 境界規約・API安定性・再現性・Ruff準拠を優先度順にレビュー |

**Hooks** (`.claude/hooks/`)
- Python ファイル編集後に `ruff check --fix` + `ruff format` を自動実行

**Skills** (`.agent/skills/`)
- `codeql-regression-check` — CodeQL クエリ変更の precision/recall リスクをレビュー

#### Opus–Sonnet オーケストレーション

`.agent/docs/` に仕様書を置き、以下のように依頼するだけで Opus が計画を立て Sonnet が実装する：

```
> .agent/docs/{仕様書}.md の仕様を読んで実装して
```

モデル構成：
- メインセッション：`claude --model claude-opus-4-6` で起動
- `architect` サブエージェント：`model: opus`（frontmatter で明示固定）
- `implementer` サブエージェント：`model: inherit`（`.claude/settings.json` の `env.CLAUDE_CODE_SUBAGENT_MODEL` を参照）

セットアップ詳細は `.agent/skills/opus-orchestrated-implementation/SKILL.md` を参照。

---

@.agent/instructions/granularity-analysis.md
