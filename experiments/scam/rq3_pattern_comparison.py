"""RQ3: 既存・新規パターンの検出比較。

`outputs/scam/approach/04_equivalence_classes.json` と `05_selections.json` を読み込み、
`data/baseline_patterns/*.json` に格納された既存研究パターンと 検出結果（detect_id） の
Jaccard 類似度で比較する。

設計方針: 既存パターンも本パイプラインと同じ `Pattern` 型・同じ `detect()` を使う。

入力:
    - `outputs/scam/approach/04_equivalence_classes.json` (Stage 4 出力)
    - `outputs/scam/approach/05_selections.json`         (Stage 5 出力)
    - MBDiff JSON                                         (baseline の 検出結果 計算用)
    - `data/baseline_patterns/*.json`                     (既存パターン)

出力:
    - `outputs/scam/rq3/rq3_classes.json`
    - `outputs/scam/rq3/rq3_summary.csv`
    - `outputs/scam/rq3/pattern.json`

実行例:
    uv run python experiments/scam/rq3_pattern_comparison.py --test --abst-level 2
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Any

import hayalab
from hayalab.classes.gumtree import GumDiff
from hayalab.classes.pattern import EquivalenceClass, Pattern
from hayalab.config import PathConfig
from hayalab.pattern import compute_detection


def parse_args() -> argparse.Namespace:
    """CLI 引数。"""
    parser = argparse.ArgumentParser(description="RQ3 baseline vs new pattern comparison")
    parser.add_argument("--input", type=Path, default=None, help="MBDiff JSON path")
    parser.add_argument("--test", action="store_true")
    parser.add_argument("--abst-level", type=int, default=2, choices=(0, 1, 2, 3))
    parser.add_argument("--classes", type=Path, default=None, help="Stage 4 出力 (equivalence_classes)")
    parser.add_argument("--class-patterns", type=Path, default=None, help="Stage 4 出力 (class_patterns)")
    parser.add_argument("--selections", type=Path, default=None, help="Stage 5 出力")
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--baseline-dir", type=Path, default=None)
    parser.add_argument("--jaccard-threshold", type=float, default=0.5)
    # 後方互換のため、weight-w を受け取れるが本スクリプトでは使用しない
    parser.add_argument("--weight-w", type=float, default=0.5)
    return parser.parse_args()


def determine_input(args: argparse.Namespace, pc: PathConfig) -> Path:
    """MBDiff JSON パス決定。"""
    if args.input is not None:
        return args.input
    if args.test:
        return pc.data / "test_data" / "MBDiff_target.json"
    return pc.processed / "MBDiff.json"


def class_from_dict(d: dict) -> EquivalenceClass:
    """Dict → EquivalenceClass (検出結果 を set 復元)。"""
    return EquivalenceClass.model_validate({**d, "detect_id": set(d["detect_id"])})


def load_baseline_patterns(baseline_dir: Path) -> list[tuple[str, Pattern]]:
    """既存パターン JSON を `data/baseline_patterns/*.json` から読み込む。

    JSON 形式:
        {"label": "...", "pattern": { ... Pattern model_dump ... }}
    """
    if not baseline_dir.exists():
        return []
    results: list[tuple[str, Pattern]] = []
    for path in sorted(baseline_dir.glob("*.json")):
        data: dict[str, Any] = hayalab.read_json(str(path))
        label = data.get("label", path.stem)
        pattern_dict = data.get("pattern")
        if pattern_dict is None:
            continue
        try:
            pattern = Pattern.model_validate(pattern_dict)
        except Exception as exc:  # noqa: BLE001
            print(f"  [WARN] failed to parse {path.name}: {exc}", flush=True)
            continue
        results.append((label, pattern))
    return results


def jaccard(a: set[int], b: set[int]) -> float:
    """集合 Jaccard。両方空なら 0.0。"""
    u = a | b
    if not u:
        return 0.0
    return len(a & b) / len(u)


def main() -> None:
    """RQ3 を実行する。"""
    args = parse_args()
    pc = PathConfig()
    classes_path = args.classes or (pc.outputs / "scam" / "approach" / "04_equivalence_classes.json")
    class_patterns_path = args.class_patterns or (pc.outputs / "scam" / "approach" / "04_class_patterns.json")
    selections_path = args.selections or (pc.outputs / "scam" / "approach" / "05_selections.json")
    output_dir = args.output_dir or (pc.outputs / "scam" / "rq3")
    output_dir.mkdir(parents=True, exist_ok=True)
    baseline_dir = args.baseline_dir or (pc.data / "baseline_patterns")
    input_path = determine_input(args, pc)

    for path in (classes_path, class_patterns_path, selections_path, input_path):
        if not path.exists():
            raise FileNotFoundError(f"必要な入力が見つかりません: {path}")

    print(f"[INPUT] classes        = {classes_path}", flush=True)
    print(f"[INPUT] class_patterns = {class_patterns_path}", flush=True)
    print(f"[INPUT] selections     = {selections_path}", flush=True)
    print(f"[INPUT] mbdiff         = {input_path}", flush=True)

    raw_classes = hayalab.read_json(str(classes_path))
    classes_for_level = [class_from_dict(c) for c in raw_classes[str(args.abst_level)]]
    # 各 class_id に属するパターン詳細（signature → Pattern）を補助 JSON から復元
    class_patterns_raw = hayalab.read_json(str(class_patterns_path))
    print(f"[CLASSES] A{args.abst_level}: total={len(classes_for_level)}", flush=True)

    # 集約された（|S| >= 2）クラスのみを比較対象にする
    aggregated_classes = [c for c in classes_for_level if len(c.detect_id) >= 2]
    print(f"[CLASSES] aggregated={len(aggregated_classes)}", flush=True)

    # baseline pattern の 検出結果 計算用 dataset
    mbdiff_records = hayalab.read_json(str(input_path))
    dataset: list[tuple[int, object]] = []
    for rec in mbdiff_records:
        diff = GumDiff.model_validate(rec["diff"])
        dataset.append((rec["id"], diff.base_ast))

    baseline = load_baseline_patterns(baseline_dir)
    print(f"[BASELINE] patterns: {len(baseline)} (from {baseline_dir})", flush=True)
    # baseline 各パターンの検出結果（マッチした MB id 集合）を計算
    baseline_detection: list[tuple[str, Pattern, set[int]]] = []
    for label, bp in baseline:
        s = compute_detection(bp, dataset)
        baseline_detection.append((label, bp, s))

    rq3_classes: list[dict[str, Any]] = []
    counts_existing = 0
    counts_new = 0
    for cls in aggregated_classes:
        best_jaccard = 0.0
        best_label: str | None = None
        best_pattern: Pattern | None = None
        for label, bp, bs in baseline_detection:
            j = jaccard(cls.detect_id, bs)
            if j > best_jaccard:
                best_jaccard = j
                best_label = label
                best_pattern = bp
        classification = "existing" if best_jaccard >= args.jaccard_threshold else "new"
        if classification == "existing":
            counts_existing += 1
        else:
            counts_new += 1
        cls_payload = cls.model_dump(mode="json")
        cls_payload["detect_id"] = sorted(cls.detect_id)
        rq3_classes.append(
            {
                "class": cls_payload,
                "best_baseline_label": best_label,
                "best_baseline_jaccard": best_jaccard,
                "best_baseline_pattern": (best_pattern.model_dump(mode="json") if best_pattern else None),
                "classification": classification,
            }
        )

    hayalab.write_json(str(output_dir / "rq3_classes.json"), rq3_classes)

    csv_path = output_dir / "rq3_summary.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["classification", "n_classes", "total_mb_coverage"])
        for cls_label, entries in [
            ("existing", [e for e in rq3_classes if e["classification"] == "existing"]),
            ("new", [e for e in rq3_classes if e["classification"] == "new"]),
        ]:
            covered: set[int] = set()
            for e in entries:
                covered |= set(e["class"]["detect_id"])
            writer.writerow([cls_label, len(entries), len(covered)])

    # 各 aggregated class の代表パターンは補助 JSON (class_patterns) から
    # 最初のメンバ（signature 昇順で先頭）を取り出して使用する。
    # 補助 JSON はキーが abst_level、その下が class_id の二段構造。
    level_class_patterns = class_patterns_raw.get(str(args.abst_level), {})
    new_patterns_aggregated: list[dict] = []
    for cls in aggregated_classes:
        entry = level_class_patterns.get(cls.class_id)
        if entry is None or not entry["patterns"]:
            continue
        # signature 昇順の先頭を代表とする（決定論的）
        rep = sorted(entry["patterns"], key=lambda p: p["signature"])[0]
        new_patterns_aggregated.append(rep)

    hayalab.write_json(
        str(output_dir / "pattern.json"),
        {
            "new_patterns_aggregated": new_patterns_aggregated,
            "baseline_patterns": [bp.model_dump(mode="json") for _, bp in baseline],
        },
    )

    print(f"[DONE] existing={counts_existing}, new={counts_new}", flush=True)
    print(f"  {csv_path}", flush=True)


if __name__ == "__main__":
    main()
