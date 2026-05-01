---
name: codeql-regression-check
description: Review CodeQL query changes for precision/recall impact, schema compatibility, and reproducibility risks. Use when editing QL/query/**/*.ql files.
---

# CodeQL Regression Check

CodeQL query の変更をレビューする際、precision/recall の変動、スキーマ互換性、再現性リスクを確認するために使用する。

## Intent
Provide a consistent review workflow for query edits in `QL/query`.

## Steps
1. Identify changed predicates, selected columns, and labels.
2. Estimate precision/recall impact from predicate broadening or narrowing.
3. Verify output compatibility for downstream scripts and output paths.
4. Propose minimal edits if regressions are likely.
5. Summarize risks and recommended validation commands.

## Output Format
- Query scope
- Precision risk
- Recall risk
- Schema/path compatibility
- Minimal fix proposal
- Validation checklist

## Validation Checklist
- Compare result count deltas on representative targets.
- Confirm JSON/SARIF consumers still parse expected fields.
- Confirm no unintended output directory changes.
