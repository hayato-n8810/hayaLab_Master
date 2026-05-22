"""Stage 4: 抽象化レベル別に検出結果ベースの同値類集約を行う。

出力は 2 つに分割する:
    - `04_equivalence_classes.json`: 同値類本体（class_id, members, detect_id のみ）
        スキーマ: { "<abst_level>": [ {class_id, members, detect_id}, ... ] }
        members は ClassMember (mb_id, signature, depth) のリスト
    - `04_class_patterns.json`: 各 class_id に紐づく所属パターンの詳細
        （signature、mb_id、depth、abst_level、終端記号列、ast_template）
        スキーマ: { "<abst_level>": { "<class_id>": { "patterns": [...] }, ... } }

入力:
    - `outputs/scam/approach/02_patterns.json`  (Stage 2 出力)
    - `outputs/scam/approach/03_detection_ids.json`  (Stage 3 出力)

実行例:
    uv run python experiments/scam/approach/04_aggregate.py --test
"""

from __future__ import annotations

import argparse
from pathlib import Path

import hayalab
from hayalab.classes.pattern import Pattern
from hayalab.config import PathConfig
from hayalab.pattern import aggregate_equivalence_classes


def parse_args() -> argparse.Namespace:
    """CLI 引数。"""
    parser = argparse.ArgumentParser(description="Stage 4: equivalence class aggregation")
    parser.add_argument("--test", action="store_true")
    parser.add_argument("--patterns", type=Path, default=None)
    parser.add_argument("--detection-ids", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--tau", type=float, default=1.0)
    return parser.parse_args()


def main() -> None:
    """Stage 4 を実行する。"""
    args = parse_args()
    pc = PathConfig()
    output_dir = args.output_dir or (pc.outputs / "scam" / "approach")
    output_dir.mkdir(parents=True, exist_ok=True)
    patterns_path = args.patterns or (output_dir / "02_patterns.json")
    detection_ids_path = args.detection_ids or (output_dir / "03_detection_ids.json")
    classes_out_path = output_dir / "04_equivalence_classes.json"
    class_patterns_out_path = output_dir / "04_class_patterns.json"

    if not patterns_path.exists():
        raise FileNotFoundError(f"Stage 2 出力が見つかりません: {patterns_path}")
    if not detection_ids_path.exists():
        raise FileNotFoundError(f"Stage 3 出力が見つかりません: {detection_ids_path}")

    patterns_data = hayalab.read_json(str(patterns_path))
    detection_raw = hayalab.read_json(str(detection_ids_path))
    # キー: パターン同一性判定用ハッシュ (Pattern.signature)、値: 検出された MB id 集合
    detection_results: dict[str, set[int]] = {sig: set(mb_ids) for sig, mb_ids in detection_raw.items()}

    # 抽象化レベル別に Pattern を集める
    patterns_by_level: dict[int, list[Pattern]] = {0: [], 1: [], 2: [], 3: []}
    for entry in patterns_data:
        for level_str, plist in entry["patterns"].items():
            for p_dict in plist:
                patterns_by_level[int(level_str)].append(Pattern.model_validate(p_dict))

    # 同値類本体（class_id, members, detect_id）と
    # 各 class に属するパターンの詳細（終端記号列 + AST）を 2 ファイルに分けて出力。
    classes_output: dict[str, list[dict]] = {}
    class_patterns_output: dict[str, dict[str, dict]] = {}

    for level in (0, 1, 2, 3):
        classes = aggregate_equivalence_classes(
            patterns_by_level[level],
            detection_results,
            tau=args.tau,
        )
        # 当該抽象化レベルでの signature → Pattern マップ（abst_level が一致した Pattern を返す）
        level_sig_to_pattern: dict[str, Pattern] = {}
        for p in patterns_by_level[level]:
            level_sig_to_pattern.setdefault(p.signature, p)

        serializable: list[dict] = []
        for c in classes:
            payload = c.model_dump(mode="json")
            payload["detect_id"] = sorted(c.detect_id)
            serializable.append(payload)

            # 各 class に属するパターン群について、その抽象度の終端記号列と
            # 対応する AST 列を補助ファイルに書き出す。signature 単位で重複排除する
            # （同 signature の異 mb_id member は同一 ast_template を共有するため）。
            patterns_detail: list[dict] = []
            seen_sigs: set[str] = set()
            for m in c.members:
                if m.signature in seen_sigs:
                    continue
                seen_sigs.add(m.signature)
                p = level_sig_to_pattern.get(m.signature)
                if p is None:
                    continue
                # 終端記号列の抽出: is_terminal=True のノードを順に取り出し、
                # 識別子は abst_level に応じた表現（literal_generalize=False: 元値、True: PREFIX_* 形）、
                # その他終端（記号・キーワード・抽象リテラル）は value をそのまま使う。
                literal_generalize = bool(p.abst_level >> 1)
                terminal_tokens: list[str] = []
                for tn in p.ast_template:
                    if not tn.get("is_terminal", False):
                        continue
                    if tn.get("slot_id") is not None and tn.get("prefix") is not None:
                        if literal_generalize:
                            terminal_tokens.append(f"{tn['prefix']}_*")
                        else:
                            terminal_tokens.append(tn.get("original_value") or tn["value"])
                    else:
                        terminal_tokens.append(tn["value"])

                patterns_detail.append(
                    {
                        "signature": p.signature,
                        "mb_id": p.mb_id,
                        "depth": p.depth,
                        "abst_level": p.abst_level,
                        "terminal_tokens": " ".join(terminal_tokens),
                        "ast_template": p.ast_template,
                    }
                )
            class_patterns_output.setdefault(str(level), {})[c.class_id] = {
                "patterns": patterns_detail,
            }

        classes_output[str(level)] = serializable
        n_agg = sum(1 for c in classes if len(c.detect_id) >= 2)
        print(
            f"  A{level}: classes={len(classes)}, aggregated={n_agg}, just_match={len(classes) - n_agg}",
            flush=True,
        )

    hayalab.write_json(str(classes_out_path), classes_output)
    hayalab.write_json(str(class_patterns_out_path), class_patterns_output)
    print(f"[OUTPUT] classes      = {classes_out_path}", flush=True)
    print(f"[OUTPUT] class_patterns = {class_patterns_out_path}", flush=True)


if __name__ == "__main__":
    main()
