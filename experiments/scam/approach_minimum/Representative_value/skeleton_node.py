r"""戦略 5: AST node 列での skeleton 抽出（``skeleton.py`` の AST 版）.

``skeleton.py`` は label value 文字列（終端の value をスペース区切りで連結した
もの）で位置別多数決を行うが、 本戦略は **bigram 構築に使われた AST node の
token 列**（``tokens_from_nodes`` が返す ``(name, normalized_value)`` 列）に
同じアルゴリズムを適用する。

これにより、 クラスタリングが拠って立つ AST 同型の核を「位置を保ったまま」
可視化できる。 ノードの ``name`` まで含めて多数決するため、 終端文字列で
多数派になるが ``name`` が違うケース（例: identifier の値が同じだが node 種別が
違う）を区別できる。

アライメント方針（``skeleton.py`` と同じ）:
    1. 各メンバーの token 列を ``tokens_from_nodes`` で抽出（variadic 除外、
       slot 番号正規化）。
    2. token 数中央値に最も近いメンバー（タイは mb_id 昇順）を基準列 ``base``
       に採用。
    3. 各位置 ``p`` について、 他メンバーの ``tokens[p]`` が ``base[p]`` と
       一致するメンバー比率 ``support[p] / size`` が ``k_threshold`` 以上なら
       そのトークン、 未満なら ``*`` を当てる。
    4. 連続 ``*`` は 1 つに圧縮する。

bigram cache は順序を捨てて frozenset 化しているため位置別計算には使えず、
本戦略は abstract JSON を読み込んで token 列を取得する（[TOKENS] reading...
ログを出す）。 そのため起動は他戦略より遅い点に注意。

入力:
    cluster:  ``outputs/scam/approach_minimum/integrate/{tau_dir}/level{L}/{depth}/{depth}.json``
    label:    ``..._label.json``（クラスメンバー id の取得に利用）
    abstract: ``outputs/scam/approach_minimum/abstract/abstract_level{L}.json``

出力:
    ``{tau_dir}/level{L}/{depth}/{depth}_pattern_skeleton_node.json``

スキーマ::

    {
      "meta": {"tau_dir", "level", "depth",
                "strategy": "skeleton_node",
                "k_threshold": float, "num_classes": int},
      "classes": {
        class_id: {
          "size": int,
          "base_id": int,                                 // 基準列メンバー
          "skeleton": [[name, value] or "*", ...],        // 圧縮済み node 列
          "skeleton_str": str,                            // 人間可読版 (name:value 区切り)
          "support_per_position": [int, ...]              // 圧縮前の各位置サポート
        }
      }
    }

実行例:
    uv run python experiments/scam/approach_minimum/Representative_value/skeleton_node.py \
        --tau-dir jaccard07 --k 0.66 --levels 0
"""

from __future__ import annotations

import argparse
import os
from statistics import median_low
from typing import Any

from _common import DEPTHS, load_id_to_tokens, read_inputs, run_parallel, write_output

from hayalab.config import PathConfig

STRATEGY = "skeleton_node"
WILDCARD = "*"

# ワーカープロセスが参照する token テーブルと k_threshold（initializer で設定）。
_TOKENS: dict[int, list[tuple[str, str]]] = {}
_K: float = 0.0


def _worker_init(id_to_tokens: dict[int, list[tuple[str, str]]], k_threshold: float) -> None:
    """ProcessPoolExecutor initializer: token テーブルと閾値をワーカーに展開."""
    global _TOKENS, _K
    _TOKENS = id_to_tokens
    _K = k_threshold


def _class_worker(item: tuple[str, list[dict[str, Any]]]) -> tuple[str, dict[str, Any]]:
    """1 クラスの AST skeleton 計算をワーカーで実行する."""
    class_id, rows = item
    return class_id, _compute_skeleton(rows, _TOKENS, _K)


def _pick_base(
    member_ids: list[int],
    member_tokens: list[list[tuple[str, str]]],
) -> int:
    """Token 数中央値に最も近いメンバーの index を返す（同距離は id 昇順）."""
    lengths = [len(t) for t in member_tokens]
    med = median_low(lengths)
    best_idx: int | None = None
    best_key: tuple[int, int] | None = None
    for i, (mid, length) in enumerate(zip(member_ids, lengths, strict=True)):
        key = (abs(length - med), mid)
        if best_idx is None or key < best_key:  # type: ignore[operator]
            best_idx = i
            best_key = key
    assert best_idx is not None
    return best_idx


def _compute_skeleton(
    rows: list[dict[str, Any]],
    id_to_tokens: dict[int, list[tuple[str, str]]],
    k_threshold: float,
) -> dict[str, Any]:
    """1 クラスの AST skeleton と位置別サポートを返す.

    基準列の各位置で「同一 token を持つメンバー比率」が ``k_threshold`` 以上なら
    そのトークン、 未満なら ``*`` を当て、 最後に連続 ``*`` を 1 つに圧縮する。
    トークンが取れないメンバー（abstract に該当 cutout が無い等）は空リスト扱い。
    """
    member_ids = [r["id"] for r in rows]
    member_tokens = [id_to_tokens.get(mid, []) for mid in member_ids]
    size = len(rows)

    base_idx = _pick_base(member_ids, member_tokens)
    base_id = member_ids[base_idx]
    base_tokens = member_tokens[base_idx]

    raw: list[tuple[str, str] | None] = []
    supports: list[int] = []
    for p, tok in enumerate(base_tokens):
        support = sum(1 for ts in member_tokens if p < len(ts) and ts[p] == tok)
        supports.append(support)
        raw.append(tok if support / size >= k_threshold else None)  # None = wildcard

    # 連続 ``None`` (wildcard) 圧縮。
    compressed: list[tuple[str, str] | None] = []
    for tok in raw:
        if tok is None and compressed and compressed[-1] is None:
            continue
        compressed.append(tok)

    # JSON 出力用に直列化（tuple → list、 wildcard → "*"）。
    skeleton_json: list[Any] = [list(tok) if tok is not None else WILDCARD for tok in compressed]
    # 人間可読の文字列（``name:value`` または ``name``、 value 空なら省略）。
    skeleton_str_parts: list[str] = []
    for tok in compressed:
        if tok is None:
            skeleton_str_parts.append(WILDCARD)
        else:
            name, value = tok
            skeleton_str_parts.append(f"{name}:{value}" if value else name)
    skeleton_str = " ".join(skeleton_str_parts)

    return {
        "size": size,
        "base_id": base_id,
        "skeleton": skeleton_json,
        "skeleton_str": skeleton_str,
        "support_per_position": supports,
    }


def process_depth(
    config: PathConfig,
    tau_dir: str,
    level: int,
    depth: str,
    id_to_tokens: dict[int, list[tuple[str, str]]],
    k_threshold: float,
    workers: int,
) -> None:
    """1 (tau_dir, level, depth) を処理する."""
    _cluster, label = read_inputs(config, tau_dir, level, depth)
    if label is None:
        print(f"[SKIP] {tau_dir}/level{level}/{depth}: missing input", flush=True)
        return

    items = list(label.items())
    results = run_parallel(
        items,
        _class_worker,
        workers,
        initializer=_worker_init,
        initargs=(id_to_tokens, k_threshold),
    )
    classes: dict[str, dict[str, Any]] = dict(results)

    payload = {
        "meta": {
            "tau_dir": tau_dir,
            "level": level,
            "depth": depth,
            "strategy": STRATEGY,
            "k_threshold": k_threshold,
            "num_classes": len(classes),
        },
        "classes": classes,
    }
    out = write_output(config, tau_dir, level, depth, STRATEGY, payload)
    print(f"[OUTPUT] {out}  (classes={len(classes)})", flush=True)


def parse_args() -> argparse.Namespace:
    """CLI 引数."""
    p = argparse.ArgumentParser(
        description="戦略 skeleton_node: AST node 列で位置別 ≥k% majority スケルトンを抽出",
    )
    p.add_argument("--tau-dir", type=str, default="jaccard07")
    p.add_argument("--levels", type=int, nargs="+", default=[0, 1, 2, 3])
    p.add_argument("--depths", type=str, nargs="+", default=list(DEPTHS))
    p.add_argument("--k", type=float, default=0.66, help="トークン採用閾値 (default: 0.66)")
    p.add_argument(
        "--workers",
        type=int,
        default=None,
        help="並列ワーカー数 (default: os.cpu_count())。1 で逐次実行",
    )
    return p.parse_args()


def main() -> None:
    """全 level × 全 depth で AST node スケルトンを生成する."""
    args = parse_args()
    config = PathConfig()
    workers = args.workers if args.workers is not None else (os.cpu_count() or 1)
    print(f"[CONFIG] workers={workers}", flush=True)

    for level in args.levels:
        table = load_id_to_tokens(config, level)
        if table is None:
            print(f"[SKIP] level{level}: abstract JSON missing", flush=True)
            continue

        for depth in args.depths:
            id_to_tokens = table.get(depth, {})
            process_depth(config, args.tau_dir, level, depth, id_to_tokens, args.k, workers)
        # peak メモリを抑えるため、 次 level に進む前に table を解放する。
        del table


if __name__ == "__main__":
    main()
