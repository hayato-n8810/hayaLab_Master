"""Stage 3: 全 Pattern の検出結果（マッチした MB id 集合）を計算し、保存する。

各パターンに対し、データセット全体に対する単一処理 `compute_detection` を呼ぶ。
パターン同一性判定用ハッシュ（Pattern.signature）が同じパターンは検出結果も同一なので、
ハッシュ単位で重複排除する。`--workers N` で ProcessPoolExecutor による並列化が可能。

入力:
    - `outputs/scam/approach/02_patterns.json`  (Stage 2 出力)
    - MBDiff JSON (dataset として全 MB の base_ast を参照)

出力: `outputs/scam/approach/03_detection_ids.json`

スキーマ:
    {
        "<パターン同一性ハッシュ>": [<mb_id>, <mb_id>, ...],   // ソート済み整数リスト
        ...
    }

実行例:
    uv run python experiments/scam/approach/03_detection.py --test
    uv run python experiments/scam/approach/03_detection.py --workers 6
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import hayalab
from hayalab.classes.gumtree import AST, GumDiff
from hayalab.classes.pattern import Pattern
from hayalab.config import PathConfig
from hayalab.pattern import compute_detection

# ProcessPoolExecutor が参照する共有データセット。
# 各 worker が初期化時に一度だけセットアップして以降は参照する。
_SHARED_DATASET: list[tuple[int, AST]] = []


def parse_args() -> argparse.Namespace:
    """CLI 引数。"""
    parser = argparse.ArgumentParser(description="Stage 3: detection computation")
    parser.add_argument("--input", type=Path, default=None, help="MBDiff JSON path")
    parser.add_argument("--test", action="store_true", help="use data/test_data/MBDiff_target.json")
    parser.add_argument("--patterns", type=Path, default=None, help="Stage 2 出力パス")
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="並列ワーカー数（1 なら逐次）",
    )
    return parser.parse_args()


def determine_input(args: argparse.Namespace, pc: PathConfig) -> Path:
    """入力 MBDiff JSON パス決定。"""
    if args.input is not None:
        return args.input
    if args.test:
        return pc.data / "test_data" / "MBDiff_target.json"
    return pc.processed / "MBDiff.json"


def load_dataset(mbdiff_path: Path) -> list[tuple[int, AST]]:
    """MBDiff JSON から (mb_id, base_ast) のリストを構築する。"""
    records = hayalab.read_json(str(mbdiff_path))
    return [(rec["id"], GumDiff.model_validate(rec["diff"]).base_ast) for rec in records]


def _init_worker(mbdiff_path_str: str) -> None:
    """ProcessPoolExecutor の各 worker でデータセットを一度だけロードする初期化関数。"""
    global _SHARED_DATASET
    _SHARED_DATASET = load_dataset(Path(mbdiff_path_str))


def _detect_one(pattern_payload: tuple[str, dict[str, Any]]) -> tuple[str, list[int]]:
    """単一パターンに対する検出結果計算（worker 側）。

    Args:
        pattern_payload: (パターン同一性ハッシュ, Pattern.model_dump() の辞書)。

    Returns:
        (パターン同一性ハッシュ, ソート済み MB id リスト)。
    """
    sig, pattern_dict = pattern_payload
    pattern = Pattern.model_validate(pattern_dict)
    ids = compute_detection(pattern, _SHARED_DATASET)
    return sig, sorted(ids)


def main() -> None:
    """Stage 3 を実行する。"""
    args = parse_args()
    pc = PathConfig()
    input_path = determine_input(args, pc)
    output_dir = args.output_dir or (pc.outputs / "scam" / "approach")
    output_dir.mkdir(parents=True, exist_ok=True)
    patterns_path = args.patterns or (output_dir / "02_patterns.json")
    output_path = output_dir / "03_detection_ids.json"

    if not patterns_path.exists():
        raise FileNotFoundError(f"Stage 2 出力が見つかりません: {patterns_path}")
    if not input_path.exists():
        raise FileNotFoundError(f"MBDiff JSON が見つかりません: {input_path}")

    print(f"[INPUT] patterns={patterns_path}", flush=True)
    print(f"[INPUT] mbdiff={input_path}", flush=True)
    patterns_data = hayalab.read_json(str(patterns_path))

    # 全 Pattern を flat list に展開し、パターン同一性判定用ハッシュ (signature) で重複排除
    sig_to_pattern_dict: dict[str, dict] = {}
    for entry in patterns_data:
        for level_patterns in entry["patterns"].values():
            for p_dict in level_patterns:
                sig_to_pattern_dict.setdefault(p_dict["signature"], p_dict)
    print(f"[PATTERNS] unique signatures: {len(sig_to_pattern_dict)}", flush=True)

    payloads = sorted(sig_to_pattern_dict.items())
    detect_ids: dict[str, list[int]] = {}

    if args.workers <= 1:
        # 逐次実行
        _SHARED_DATASET.extend(load_dataset(input_path))
        print(f"[DATASET] {len(_SHARED_DATASET)} MBs (逐次)", flush=True)
        for sig, p_dict in payloads:
            sig_out, ids = _detect_one((sig, p_dict))
            detect_ids[sig_out] = ids
    else:
        # 並列実行（worker 初期化時にデータセットを 1 回ロード）
        print(f"[DATASET] (並列, workers={args.workers})", flush=True)
        with ProcessPoolExecutor(
            max_workers=args.workers,
            initializer=_init_worker,
            initargs=(str(input_path),),
        ) as executor:
            for sig_out, ids in executor.map(_detect_one, payloads):
                detect_ids[sig_out] = ids

    print(f"[DETECTION] computed for {len(detect_ids)} signatures", flush=True)

    serializable = {sig: detect_ids[sig] for sig in sorted(detect_ids.keys())}
    hayalab.write_json(str(output_path), serializable)
    print(f"[OUTPUT] {output_path}", flush=True)


if __name__ == "__main__":
    main()
