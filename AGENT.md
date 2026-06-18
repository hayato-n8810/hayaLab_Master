# hayaLab — Project Overview for AI Agents

## Goal

A research repository. The primary goal is the pursuit of truth.

AI agents MUST prioritize **correctness**, **reproducibility**, and **minimal diffs**.

## Architecture

```
src/hayalab/      ← Reusable library (pure logic; does NOT decide I/O paths)
experiments/      ← Experiment runners (define I/O, paths, formats, steps; call hayalab)
data/             ← Input/intermediate data (raw/processed; verify downstream compatibility on schema changes)
outputs/          ← Experiment / analysis results (keep path naming conventions stable)
```

Dependency direction: `experiments → hayalab` only. Importing in the reverse direction is forbidden.

## Key Modules

| Module | Role |
|---|---|
| `hayalab.gumtree` | Python wrapper for the GumTree CLI; AST parsing and diff extraction |
| `hayalab.pattern` | Syntax pattern extraction from diff blocks (For / While / If extractors, etc.) |
| `hayalab.classes` | Data models (`ASTNode`, `SyntaxFeature`, `NodePosition`, etc.) |
| `hayalab.abst` | Code abstraction utilities |
| `hayalab.config` | Configuration values |
| `hayalab.utils` | General utilities (file I/O, etc.) |
| `hayalab.scam` | Single-purpose processing units for the SCAM2026 paper (ast_nav / diff_link / match / abstract / cluster / representative). Execution entry points, parallelism, and wiring live in `experiments/scam/` |

## Tech Stack

- Python 3.13+ (managed via `uv`)
- tree-sitter / tree-sitter-javascript (AST parsing)
- GumTree (AST diff)
- Babel parser (JavaScript AST, on the experiments side)
- CodeQL (static analysis queries)
- Ruff (lint + format), pre-commit

## Execution

```bash
uv run python experiments/<topic>/<script>.py   # Run an experiment script
uv run ruff check src/                           # lint
uv run ruff format src/                          # format
```

---

## Coding Rules

### General

- Keep changes within the scope of the request; aim for minimal diffs.
- Preserve existing APIs unless explicitly told to break them.
- Prefer clear naming over compact tricks.
- Do NOT enforce strict function size limits. Grouping cohesive processing into a single function is fine when it improves clarity.
- When existing behavior changes, state explicitly what changed. Adding tests or quick validation code is not required.
- Comments MUST describe ONLY what role the file/code plays. NEVER write the history that led to the implementation — no discussion logs, no "what changed from last time", no implementation rationale narratives.

### Boundary Rules (hayalab vs experiments)

Assumptions:

- `hayalab` provides reusable single-purpose processing units. Each processing unit should be closed within one function (or a cohesive group of methods).
- `experiments` defines experiment-specific I/O, paths, formats, and execution order, composing behavior by calling `hayalab`.

Rules:

- **Dependency direction**: `experiments → hayalab` ONLY. Code under `src/hayalab/**` MUST NOT import from `experiments/**`.
- **I/O boundary**: The library MUST NOT decide concrete paths. Accept inputs via arguments and return results.
  - Exception: low-level I/O utilities (e.g., `hayalab.utils.file`) are allowed, but the caller still decides paths.
- **Path decisions**: Which files to read/write is decided in `experiments/**` (or CLI scripts).
- **Output schema**: When JSON structures change, explicitly describe downstream compatibility impact (key names, list ordering, sorting).

### Design Conventions for New Code

- Keep library APIs small and composable. Do NOT add "do-everything" functions.
- Make failure modes explicit and consistent: pick one of returning `None`, raising, or returning a result object that carries errors — and stick with it.
- For reproducibility, avoid nondeterminism from randomness, dict ordering, or filesystem iteration order. Sort when needed.
- Do NOT change existing output path naming conventions (e.g., `outputs/ql_analysis/...`) unless explicitly requested.

---

## Python Rules

Scope: `src/**/*.py`, `experiments/**/*.py`

- Follow the Ruff configuration in `pyproject.toml`.
- Prefer `pathlib` over raw string path operations.
- Add type hints to new or modified public functions.
- Separate I/O from pure logic where practical.
- Use Google-style docstrings.
- Use `uv` for dependency management and execution (`uv add`, `uv run`).
- Text files are UTF-8. Always pass an explicit `encoding` argument to `open`.
- Do NOT hard-code absolute paths unless they are configuration values.
- Verify file existence before reading; create output directories before writing.
- Keep CLI scripts idempotent where possible.
- When changing output JSON structure, document the backward-compatibility impact in your response.
- Prefer deterministic ordering for serialized output (so diffs stay reproducible).

### Directory Boundaries (where to implement what)

- **`src/hayalab/**` (library)**
  - Place reusable logic here. Functions should be composable and focused (one processing unit per function where practical).
  - Do NOT decide concrete input/output paths here. Take data/paths as arguments and return results.
  - Do NOT import from `experiments/**` (dependency direction: `experiments → hayalab`).
  - Keep side effects minimal. `print` / `logging` should be opt-in (or delegated to the caller).

- **`experiments/**` (experiment runners)**
  - Place experiment-specific orchestration here: CLI args, path selection, I/O formats, execution order.
  - Keep the code thin: read inputs → call `hayalab` → write outputs.
  - It is OK to hard-code paths relative to the repository root (e.g., `data/`, `outputs/`) as the experiment contract.

### I/O and Schema Rules

- File layout decisions belong to the experiments side. The library MUST NOT write into `outputs/**` or `data/**` by default.
- When adding a new output file, follow existing `outputs/**` naming conventions and keep names stable.
- When changing JSON schema, keep downstream compatibility in mind (key names, list ordering, sorting).

### Experiment Script Structure (`experiments/**/*.py`)

Experiment scripts MUST be readable top-to-bottom — the entire flow should be traceable by reading from the top. Introduce abstractions ONLY when reuse actually occurs.

#### Required rules

1. **Do NOT define a `main()` function.** Write the execution flow directly inside an `if __name__ == "__main__":` block. Do NOT put `def main(): ...` at module top level and call it at the bottom.
2. **Do NOT extract single-use code into functions.** A single processing step should be written inline inside the `__main__` block. Do NOT create a function just to "give it a readable name".
3. **The ONLY functions that may remain are:**
   - Utilities called multiple times (timestamp generation, path computation, JSON saving, etc.)
   - per-entry / per-URL / per-record workers (retry, parse, extract, etc. — anything called once per loop iteration)
   - Shared assembly logic (e.g., payload construction used in multiple places that builds the same dict/structure)
4. **Write the `__main__` block as `section comments + linear flow`.** Insert section delimiters (`# --- section name -----`) and stack processing blocks top-to-bottom. Use `raise SystemExit(0)` for early termination.

#### Recommended pattern

```python
"""Module docstring (Google style)."""

from __future__ import annotations
import ...

# --- Constants (hyperparameters tunable at the top of the file) ----
PARAM_A: int = ...

# --- Helpers (only those called multiple times) --------------------
def _helper_called_many_times(...) -> ...:
    """Google-style docstring (Args/Returns/Raises)."""
    ...

def _worker_per_record(...) -> ...:
    """per-entry processing (called inside a loop)."""
    ...

# --- Main flow -----------------------------------------------------
if __name__ == "__main__":
    # --- Section 1: Path resolution ---
    ...

    # --- Section 2: Input loading ---
    ...

    # --- Section 3: Main loop ---
    for entry in entries:
        _worker_per_record(entry)
        ...

    # --- Section 4: Output saving ---
    ...
```

#### Decision criteria (should this be a function?)

- "Is it called 2+ times?" → Yes → make it a function.
- "Will it become a loop body?" (per-record processing) → Yes → make it a function so it can be tested/reused.
- "I just want to label a meaningful chunk inside `__main__`?" → No. **Use a section comment instead.**
- "Is the failure recovery logic complex?" → Yes → extract a worker function and structure its `try/except`.

---

## CodeQL Query Rules

Scope: `QL/query/**/*.ql`

- Keep query intent explicit. Avoid implicit semantic changes.
- When modifying a query, explain what changed and what will now be detected.
- Prefer small predicate-level edits over large rewrites.
- Preserve output labels and ID naming conventions that downstream analysis depends on.
- Add comments only where the logic is non-obvious, and explain the reason.
- Do NOT change output path conventions unless explicitly requested.

---

## Review Checklist

- Did this change alter data formats or output schemas?
- Are path assumptions still valid for execution in a GitHub environment?
- Is the experiment reproducible from the repository root?

## Plan Output Rules

- When the user requests a plan, save it as a Markdown file under `.agent/plans/`.
- Filename format: `YYYY-MM-DD-<short-topic>.md`
- Required sections: Goal, Assumptions, Steps, Validation, Risks.
- Keep plans concise and action-oriented. Do NOT include implementation details unless explicitly requested.

---

## AI Agent Workspace

`.agent/` is the canonical home for AI agent configuration in this project.
The role and timing for each file are listed below.

### File Map

| Path | Role | When to use |
|---|---|---|
| `AGENT.md` (this file) | Project overview, all rules, workspace guide | Always (entry point) |
| `.agent/prompts/` | Reusable prompt collection (`bug-investigation`, `implementation-plan`, etc.) | When the user explicitly references one |
| `.agent/skills/` | Reusable skill definitions (multi-step procedures) | When the user invokes a skill by name |
| `.agent/agents/` | Claude Code subagent definitions | Auto-loaded by Claude Code |
| `.agent/plans/` | Plan output location (`{spec-filename}/PLAN.md` format) | When asked to write a plan |
| `.agent/docs/` | Implementation specs (Markdown only) | Read by the `architect` subagent |

### Tool-specific Entry Points

| Tool | File loaded | Actual target |
|---|---|---|
| Claude Code | `CLAUDE.md` | `AGENT.md` (this file, via symlink) |

### Claude Code–specific Features

Claude Code has the following capabilities in this project.

**Subagents** (`.agent/agents/` = `.claude/agents/` via symlink)

| Agent | Model | Role |
|---|---|---|
| `architect` | Opus | Reads specs in `.agent/docs/` and writes `.agent/plans/{topic}/PLAN.md` |
| `implementer` | Sonnet (inherit) | Reads `PLAN.md` and implements the code |
| `test-writer` | — | Generates pytest tests for modules under `src/hayalab/` |
| `code-reviewer` | — | Reviews changes in priority order: boundary rules, API stability, reproducibility, Ruff compliance |

**Hooks** (`.claude/hooks/`)
- After Python file edits, auto-run `ruff check --fix` + `ruff format`

**Skills** (`.agent/skills/`)
- `codeql-regression-check` — Reviews precision/recall risk of CodeQL query changes

#### Opus–Sonnet orchestration

Place a spec under `.agent/docs/` and request it like this — Opus will plan and Sonnet will implement:

```
> Read .agent/docs/{spec}.md and implement it
```

Model configuration:
- Main session: launch with `claude --model claude-opus-4-6`
- `architect` subagent: `model: opus` (pinned in frontmatter)
- `implementer` subagent: `model: inherit` (reads `env.CLAUDE_CODE_SUBAGENT_MODEL` in `.claude/settings.json`)

See `.agent/skills/opus-orchestrated-implementation/SKILL.md` for setup details.

