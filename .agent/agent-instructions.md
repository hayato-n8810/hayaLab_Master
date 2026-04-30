# AI Agent Workspace Instructions for hayaLab

## Goal
This repository focuses on CodeQL-based pattern analysis and Python data pipelines.
AI Agent should prioritize correctness, reproducibility, and minimal diffs.

## Repository Responsibility Map

AI Agent should decide "where to implement what" according to the responsibilities below.

- `src/hayalab/**`: Reusable library implementation (pure logic; independent from any specific experiment)
- `experiments/**`: Experiment-specific runs (orchestration of I/O, paths, formats, and execution order)
- `QL/query/**`: CodeQL queries themselves (detection logic; keep output labels stable)
- `QL/scripts/**`: Helper scripts for CodeQL execution, conversion, and aggregation (CLI/batch oriented)
- `data/**`: Input/intermediate datasets (raw/processed). Be careful with schema changes.
- `outputs/**` and `codeql/outputs/**`: Experiment/analysis outputs (keep path conventions stable for reproducibility)
- `targets/**`: Analysis targets (GitHub / microbenchmark input sets)

## Boundary Rules (hayalab vs experiments)

Assumptions:

- `hayalab` provides reusable processing units; design them so one processing unit is closed within one function (or a cohesive set of methods).
- `experiments` defines experiment-specific I/O, paths, formats, and execution steps, composing behavior by calling `hayalab`.

Rules:

- Dependency direction: `experiments -> hayalab` only. Never import `experiments/**` from `src/hayalab/**`.
- I/O boundary: the library should not decide concrete paths. Accept inputs via arguments and return outputs.
	- Exception: low-level I/O utilities (e.g., `hayalab.utils.file`) are allowed, but callers still decide paths.
- Path decisions: which files to read/write must be decided in `experiments/**` (or CLI scripts).
- Output schema: if you change JSON structures, explicitly describe downstream compatibility impact (key names, list ordering, sorting).

## Design Conventions for New Code

- Keep library APIs small and composable (avoid adding "do-everything" functions).
- Make failure modes explicit and consistent (choose one: return `None`, raise, or return a result object that includes errors).
- Reproducibility: avoid nondeterminism from randomness, dict ordering, or file iteration ordering; sort when needed.
- Do not change existing output path conventions and naming (e.g., `outputs/ql_analysis/...`) unless explicitly requested.

## Tech Stack
- Python 3.12+ (source code under src/hayalab)
- CodeQL query development (QL/query)
- Analysis scripts in experiments and QL/scripts

## Coding Rules
- Keep changes minimal and scoped to the request.
- Preserve existing APIs unless explicitly asked to break them.
- Prefer clear naming and over compact tricks.
- Do not enforce strict function size limits; prefer grouping cohesive processing into a single function when it improves clarity.
- When existing behavior changes, clearly describe what changed. Adding tests or quick validation code is not required.

## Python Rules
- Follow Ruff settings defined in `pyproject.toml`.
- Prefer pathlib over raw string path operations.
- Add type hints for new or modified public functions.
- Keep I/O and pure logic separated when practical.
- Use Google-style docstrings.
- This repository uses uv-managed environments. Use uv commands for dependency install and execution, such as `uv add` and `uv run`.

## CodeQL/Research Workflow Rules
- Do not silently change query semantics.
- When modifying queries, explain what changed and what will be detected by the updated query.
- Keep output path conventions stable unless explicitly requested.

## Review Checklist
- Does this change alter data format or output schema?
- Are path assumptions valid for GitHub environment execution?
- Are experiments reproducible from repository root?

## Plan Output Rules
- When a user asks for a plan, save it as a Markdown file under `.agent/plans/`.
- Use filename format: `YYYY-MM-DD-<short-topic>.md`.
- Include sections: Goal, Assumptions, Steps, Validation, Risks.
- Keep plans concise and action-oriented; avoid implementation details unless requested.

## Modular Instructions

The following modular instruction files provide context-specific rules:

- Python and analysis code: `.agent/instructions/python-research.md`
- CodeQL query files: `.agent/instructions/codeql-query.md`
