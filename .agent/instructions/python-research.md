# Python and Analysis File Instructions

Apply when editing: `src/**/*.py`, `QL/scripts/**/*.py`, `experiments/**/*.py`

- Do not enforce strict function size limits; prefer grouping cohesive processing into a single function when it improves clarity.
- When behavior changes, clearly describe what changed. Adding tests or quick validation code is not required.
- Follow Ruff settings defined in `pyproject.toml`.
- Keep CLI scripts idempotent where possible.
- Validate file existence before reading and create output directories before writing.
- Use UTF-8 for text files and explicit encoding in open calls.
- Avoid hard-coded absolute paths unless they are configuration values.
- Use Google-style docstrings.
- Use uv-managed workflow commands for Python dependencies and execution, such as `uv add` and `uv run`.
- When changing output JSON structure, document backward compatibility impact in the response.
- Prefer deterministic ordering for serialized outputs (for reproducible diffs).

## Directory Boundaries (where to implement)

- `src/hayalab/**` (library)
	- Put reusable logic here. Keep functions composable and focused (one processing unit per function where practical).
	- Do not decide concrete input/output paths here; take data/paths as arguments and return results.
	- Avoid importing `experiments/**`. Dependency direction is `experiments -> hayalab`.
	- Keep side effects minimal; printing/logging should be opt-in (or handled by callers).

- `experiments/**` (experiment runners)
	- Put experiment-specific orchestration here: CLI args, path selection, I/O formats, and execution order.
	- Keep the code thin: read inputs, call `hayalab`, write outputs.
	- It is OK to hard-code paths relative to repo root (e.g., `data/`, `outputs/`) when that is the experiment contract.

- `QL/scripts/**` (automation / batch utilities)
	- Put CodeQL execution helpers, conversions (e.g., SARIF -> JSON), and aggregations here.
	- Prefer CLI-friendly interfaces and idempotent behavior (safe re-runs).

## I/O and Schema Rules

- Experiments own file layout decisions; the library should not write into `outputs/**` or `data/**` by default.
- If you must add a new output file, place it under the existing `outputs/**` conventions and keep naming stable.
- When changing JSON schema, keep downstream compatibility in mind (key names, list ordering, and sorting).
