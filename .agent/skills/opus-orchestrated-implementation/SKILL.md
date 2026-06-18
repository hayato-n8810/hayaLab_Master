---
name: opus-orchestrated-implementation
description: |
  .agent/plans/ に置かれた Markdown 仕様書を指定して実装を依頼されたとき、Opus が仕様を解釈して計画を立て、Sonnet が実装を行うマルチモデル・オーケストレーションワークフローをセットアップする。
  以下のいずれかに当てはまる場合は必ずこのスキルを使うこと：
  - 「.agent/plans/ の仕様を実装して」と言われたとき
  - 「仕様書を読んで実装計画を立て、実装して」と言われたとき
  - 「Opus に計画させて Sonnet に実装させて」と言われたとき
  - architect / implementer のサブエージェントをセットアップしたいとき
---

# Opus-Orchestrated Implementation Skill

## 概要

このスキルは Claude Code の **サブエージェント機能** と **モデル分離** を使い、以下の役割分担で実装を行う：

| 役割 | モデル | サブエージェント | 担当 |
|---|---|---|---|
| オーケストレーター | Opus（メインセッション） | — | 全体把握・委譲・レビュー |
| アーキテクト | Opus | `architect` | 仕様解釈・計画書作成 |
| 実装者 | Sonnet | `implementer` | コード実装 |

---

## セットアップ手順

### 1. モデル設定（`settings.json`）

プロジェクトルートの **`.claude/settings.json`** に以下を追記する。これが `CLAUDE_CODE_SUBAGENT_MODEL` の正規の記述場所。

```json
{
  "env": {
    "CLAUDE_CODE_SUBAGENT_MODEL": "claude-sonnet-4-6"
  }
}
```

> **なぜ `settings.json` の `env` キーか？**
> `CLAUDE_CODE_SUBAGENT_MODEL` は環境変数であり、シェルの `export` でもセットできるが、
> `settings.json` の `env` ブロックに書くとプロジェクトに追従し、`git` で共有できる。
> `.claude/settings.local.json` に書けば個人設定として git から除外される。
> シェルの環境変数は `settings.json` の `env` より優先される点に注意。

サブエージェントの `model: inherit` はこの値を引き継ぐ。
`architect.md` は `model: opus` を明示するので上書きされる。

### 2. サブエージェント定義ファイル

以下の2ファイルを `.agent/agents/`（= `.claude/agents/` へのシンボリックリンク）に配置する。

#### `.agent/agents/architect.md`

```markdown
---
name: architect
description: |
  .agent/plans/ 内の Markdown 仕様書を読み込み、実装計画書を作成する。
  「仕様書を読んで計画を立てて」「.agent/plans/ の md を解析して」と言われたら必ず使う。
  計画書は .agent/plans/{仕様書ファイル名（拡張子なし）}/ に PLAN.md として保存する。
tools: Read, Glob, Write
model: opus
effort: high
---

あなたはソフトウェアアーキテクトです。
指定された `.agent/plans/` 内の Markdown 仕様書を精読し、以下の構成で実装計画書を作成してください。

## 出力先

`.agent/plans/{仕様書ファイル名（拡張子なし）}/PLAN.md`

例：仕様書が `.agent/plans/auth-spec.md` なら `.agent/plans/auth-spec/PLAN.md`

## 計画書の構成

```markdown
# 実装計画：{仕様書タイトル}

## 仕様サマリー
（仕様書の目的・スコープを3〜5行で）

## 実装方針
（アーキテクチャ上の判断・既存コードとの統合方針）

## ファイル構成案
（新規作成・変更するファイルの一覧）

## 実装ステップ

- [ ] ステップ1：{タイトル}
  - 対象ファイル：
  - 内容：
  - 成功条件：

- [ ] ステップ2：...

## 実装者への注意事項
（モデル名・依存関係・境界規約など implementer が知るべき情報）

## レビュー観点
（architect が最終確認すべきポイント）
```

## 作業ルール

1. 仕様書を **全文** 読んでから計画を書く。曖昧な点は `[要確認]` タグを付けて記録する。
2. このプロジェクトの `AGENT.md` の規約を遵守する。
3. 計画書を保存したら、保存先パスと主要ステップの概要をメインセッションに返す。
4. コードは書かない。計画書のみを出力する。
```

#### `.agent/agents/implementer.md`

```markdown
---
name: implementer
description: |
  .agent/plans/ 内の PLAN.md を読み込み、実装ステップに従いコードを書く。
  「計画書に従って実装して」「PLAN.md を見て実装して」と言われたら必ず使う。
tools: Read, Write, Edit, Bash, Glob, Grep
model: inherit
---

あなたはシニアエンジニアです。
指定された `.agent/plans/{topic}/PLAN.md` を読み込み、実装ステップを順番に実行してください。

## 作業ルール

1. **PLAN.md を最初に全文読む**。仕様サマリーと実装方針を把握してから着手する。
2. ステップを **1つずつ** 実行し、完了したら PLAN.md のチェックボックスを `[x]` にする。
3. ステップの内容が曖昧・矛盾していると判断した場合は **実装を止め**、理由をメインセッションに報告する。計画外の変更は行わない。
4. `src/hayalab/` への変更は境界規約（`experiments → hayalab` のみ）を遵守する。
5. 新規ファイル・変更ファイルはすべて `uv run ruff check` と `uv run ruff format` を通す（Hook が自動実行するが、エラーは自分で修正する）。
6. テストが書ける実装には必ず pytest を追加する。
7. 全ステップ完了後、変更ファイルの一覧と実装サマリーをメインセッションに返す。
```

### 3. メインセッションの起動方法

```bash
# Opusをオーケストレーターとして起動（推奨）
claude --model claude-opus-4-7
# Sonnetをオーケストレーターとして起動（実験的）
claude --model claude-sonnet-4-7
```
# settings.json に CLAUDE_CODE_SUBAGENT_MODEL が設定されていれば
# architect → Opus（frontmatterで上書き）
# implementer → Sonnet（inherit → settings.jsonのenv値を使用）
```

---

## 実際のワークフロー

ユーザーの操作：
```
> .agent/plans/pattern-extractor-spec.md の仕様を読んで実装して
```

Claude Code（Opus）が自動的に：
1. `architect` サブエージェント（Opus）を起動 → 仕様書を読んで `.agent/plans/pattern-extractor-spec/PLAN.md` を作成
2. 計画書をメインセッションに返して確認（必要なら修正指示）
3. `implementer` サブエージェント（Sonnet）を起動 → PLAN.md に従い実装
4. 実装完了報告を受け取り、`code-reviewer` サブエージェント（既存）でレビュー

---

## ディレクトリ構成まとめ

```
.agent/
├── agents/
│   ├── architect.md         ← 新規作成（このスキルで追加）
│   ├── implementer.md       ← 新規作成（このスキルで追加）
│   ├── test-writer.md       ← 既存
│   └── code-reviewer.md     ← 既存
├── plans/
│   └── {仕様書}.md          ← ユーザーが用意する入力
└── plans/
    └── {仕様書ファイル名}/
        └── PLAN.md          ← architect が出力する計画書

.claude/
└── settings.json            ← env.CLAUDE_CODE_SUBAGENT_MODEL を追記
```

---

## モデル指定の仕組み（早見表）

| 設定箇所 | 方法 | 優先度 | 用途 |
|---|---|---|---|
| シェル `export` | `export CLAUDE_CODE_SUBAGENT_MODEL=...` | 最高 | 一時的な上書き |
| `.claude/settings.json` の `env` | `{"env": {"CLAUDE_CODE_SUBAGENT_MODEL": "..."}}` | 高 | プロジェクト共有設定 |
| `.claude/settings.local.json` の `env` | 同上 | 高（個人） | git 除外の個人設定 |
| サブエージェント frontmatter `model:` | `model: opus` / `model: sonnet` | エージェント個別 | 特定エージェントを固定 |
| サブエージェント frontmatter `model: inherit` | — | 上記の env 値を使用 | デフォルト動作 |

> `CLAUDE_CODE_SUBAGENT_MODEL` は環境変数であり、**サブエージェントの `model: inherit` がこれを参照する**。
> `model: opus` のように明示したエージェントはこの設定を無視して指定モデルで動く。

---

## トラブルシューティング

**サブエージェントが Opus で動いてしまう（コストが高い）**
→ `settings.json` の `env` に `CLAUDE_CODE_SUBAGENT_MODEL` が設定されているか確認。
→ `implementer.md` の frontmatter が `model: inherit`（または `model: sonnet`）になっているか確認。

**architect が計画書を作らずコードを書いてしまう**
→ `architect.md` のシステムプロンプト末尾「コードは書かない」の記述を確認。
→ ツールが `Write` のみで `Edit`・`Bash` が含まれていないか確認（誤って実装できないように）。

**PLAN.md の保存先が違う**
→ 仕様書のファイル名（拡張子なし）がそのままディレクトリ名になる。
→ 例：`auth-spec.md` → `.agent/plans/auth-spec/PLAN.md`

**モデル名が古くなった場合**
→ `settings.json` の値と `architect.md` の `model:` フィールドを最新のモデルIDに更新する。
→ 現時点のモデルID：`claude-opus-4-6`、`claude-sonnet-4-6`