# CodeQL Query Instructions

Apply when editing: `QL/query/**/*.ql`

- Keep query intent explicit and avoid hidden semantic changes.
- When modifying queries, explain what changed and what will be detected by the updated query.
- Prefer small predicate-level edits over full query rewrites.
- Preserve output labeling and ID naming conventions used by downstream analysis.
- Keep comments focused on reasoning when query logic is non-obvious.
