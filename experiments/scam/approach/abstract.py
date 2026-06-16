"""Stage 3: 抽象化レベル L1–L2 を cutouts.json に適用する (approach)。

``docs/abstract.md`` で確定した 2 段階累積階層 (L1/L2) を mb_id 単位で
各 cutout に適用し、レベル別に JSON ファイルとして書き出す。設計の背景・
関連研究との対応は ``docs/abstraction_design.md`` を参照。

Levels:
    L1 (Skeleton):  identifier 値 (VAR_/FUNCTION_) を slot 化。
    L2 (Standard):  L1 + literal 値 (number / string_fragment) を slot 化。
                    さらに ``regex`` ノード配下（regex ノードの origin_index
                    を parent に含む全ノード）の値を ``$r0`` 形式の slot に
                    置換する（削除はしない）。

paper (SCAM2026) における位置付け:
    本研究の確定方針 (paper §6.3.1) は「**抽象化 (Type-2 段階)
    × 類似度 (Type-3 相当の τ) の 2 軸で粒度を制御する**」設計を採用する。
    メイン分析は **L1 / L2 のみ** を用い、 Type-3 相当の柔軟性は τ 軸
    (integrate.py の ``--taus``) で吸収する。

Input:
    outputs/scam/approach/cutouts.json

Output:
    outputs/scam/approach/abstract/abstract_level{1,2}.json

Example:
    uv run python experiments/scam/approach/abstract.py --workers 8
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import hayalab
from hayalab.config import PathConfig
from hayalab.scam.abstract import abstract_level1, abstract_level2

# 抽象化レベル → トップレベル関数の対応表。 ProcessPoolExecutor の pickle 用に
# experiments トップレベルで再定義する（hayalab 側から import した純関数を値に持つ）。
LEVEL_FUNCTIONS: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {
    1: abstract_level1,
    2: abstract_level2,
}


def parse_args() -> argparse.Namespace:
    """CLI 引数を解析する。"""
    parser = argparse.ArgumentParser(description="Stage 3: abstraction L1–L2 (mb_id 並列)")
    parser.add_argument("--input", type=Path, default=None, help="cutouts.json のパス")
    parser.add_argument("--output-dir", type=Path, default=None, help="abstract_level{L}.json 出力先")
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="並列化数 (mb_id 単位で並列処理)。1 以下で逐次処理。",
    )
    parser.add_argument(
        "--server",
        action="store_true",
        help="server モード: 2 レベル × mb_id の全タスクを共有プールへ同時投入し最大限並列化する。",
    )
    return parser.parse_args()


def main() -> None:
    """抽象化を実行する。"""
    args = parse_args()
    pc = PathConfig()

    input_path = args.input or (pc.outputs / "scam" / "approach" / "cutouts.json")
    output_dir = args.output_dir or (pc.outputs / "scam" / "approach" / "abstract")
    output_dir.mkdir(parents=True, exist_ok=True)

    if not input_path.exists():
        raise FileNotFoundError(f"入力ファイルが見つかりません: {input_path}")
    print(f"[INPUT] {input_path}", flush=True)

    records = hayalab.read_json(str(input_path))
    print(f"[RECORDS] {len(records)}", flush=True)

    workers = max(1, args.workers)
    levels: tuple[int, ...] = (1, 2)
    print(f"[WORKERS] {workers} (mb_id 並列)", flush=True)

    # 逐次: workers <= 1
    if workers <= 1:
        for level in levels:
            results = [LEVEL_FUNCTIONS[level](r) for r in records]
            output_path = output_dir / f"abstract_level{level}.json"
            hayalab.write_json(str(output_path), results)
            print(f"[OUTPUT] {output_path}", flush=True)
        return

    # server モード: 全レベル × 全レコードを 1 プールに同時投入（大メモリ・多コア向け）
    if args.server:
        print("[MODE] server (全レベル同時投入・結果メモリ保持)", flush=True)
        with ProcessPoolExecutor(max_workers=workers) as pool:
            futures_per_level: dict[int, list] = {level: [pool.submit(LEVEL_FUNCTIONS[level], record) for record in records] for level in levels}
            for level in levels:
                results = [f.result() for f in futures_per_level[level]]
                output_path = output_dir / f"abstract_level{level}.json"
                hayalab.write_json(str(output_path), results)
                print(f"[OUTPUT] {output_path} ({len(results)} records)", flush=True)
        return

    # 通常モード: 1 レベルずつ mb_id 並列で処理し、ピークメモリを抑制する。
    # ProcessPoolExecutor はレベル間で再利用し、 map で入力順（id 昇順）を保つ。
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for level in levels:
            results = list(pool.map(LEVEL_FUNCTIONS[level], records, chunksize=16))
            output_path = output_dir / f"abstract_level{level}.json"
            hayalab.write_json(str(output_path), results)
            print(f"[OUTPUT] {output_path} ({len(results)} records)", flush=True)


if __name__ == "__main__":
    main()
