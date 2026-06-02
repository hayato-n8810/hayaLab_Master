r"""戦略 3: ≥k% メンバーで出現するトークンを残したスケルトンを作る.

label JSON の value 文字列 (``$v0`` 等のスロット記号を含む空白区切りトークン列)
を入力に、各位置において「クラス内 ≥k% のメンバーに同一トークンとして現れる」
ものだけを残し、可変箇所を ``*`` で表現したテンプレート文字列を生成する。

アライメント方針:
    クラス代表（medoid に近いものとして「token 数中央値に最も近いメンバー」を
    採用）の位置を基準に、各メンバーの token 列と長さを揃えて多数決を取る。
    厳密な MSA は重いので、本実装は実装容易性を優先した近似:

    1. メンバーの token 列を空白で分割。
    2. 「token 数が中央値に最も近い」（タイは id 最小）メンバーを基準列 ``base``
       に採用。
    3. 各位置 ``p`` について、 他メンバーの ``tokens[p]`` (範囲外は ``None``)
       を集計し、 base の token と一致するメンバー比率 ``support[p] / size``
       が ``k_threshold`` 以上ならそのまま、未満なら ``*`` を当てる。
    4. 連続する ``*`` は 1 つに圧縮する。

長さの大幅な差は ``*`` で吸収され、可変部の存在自体は維持される。位置ベースの
ため整列のズレに弱いが、整列状態が良いクラスター（クラスタリング目的を考えると
多数を占める）では十分機能する。

入力:
    label: ``outputs/scam/approach_minimum/integrate/{tau_dir}/level{L}/{depth}_label.json``
        ``{class_id: [{"id": int, "value": str}, ...]}``

出力:
    ``{tau_dir}/level{L}/{depth}_pattern_skeleton.json``

スキーマ::

    {
      "meta": {"tau_dir", "level", "depth",
                "strategy": "skeleton",
                "k_threshold": float, "num_classes": int},
      "classes": {
        class_id: {
          "size": int,
          "base_id": int,        // 基準列に採用したメンバー id
          "skeleton": str,       // 圧縮済みテンプレ
          "support_per_token": [int, ...]  // 圧縮前の各位置サポート
        }
      }
    }

実行例:
    uv run python experiments/scam/approach_minimum/Representative_value/skeleton.py \\
        --tau-dir jaccard07 --k 0.66 --levels 0
"""

from __future__ import annotations

import argparse
import os
from statistics import median_low
from typing import Any

from _common import DEPTHS, read_inputs, run_parallel, write_output

from hayalab.config import PathConfig

STRATEGY = "skeleton"
WILDCARD = "*"

# ワーカープロセスが参照する k_threshold（initializer で設定）。
_K: float = 0.0


def _worker_init(k_threshold: float) -> None:
    """ProcessPoolExecutor initializer: k_threshold をワーカーに展開する."""
    global _K
    _K = k_threshold


def _class_worker(item: tuple[str, list[dict[str, Any]]]) -> tuple[str, dict[str, Any]]:
    """1 クラスのスケルトン計算をワーカーで実行する."""
    class_id, rows = item
    return class_id, _compute_skeleton(rows, _K)


def _tokenize(value: str) -> list[str]:
    """Label value 文字列を空白区切り token 列にする（末尾空白は無視）."""
    return value.split()


def _pick_base(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Token 数中央値に最も近いメンバーを基準列に採る（同距離は id 昇順）."""
    lengths = [len(_tokenize(r["value"])) for r in rows]
    med = median_low(lengths)
    best: tuple[int, int, dict[str, Any]] | None = None  # (距離, id, row)
    for r, length in zip(rows, lengths, strict=True):
        key = (abs(length - med), r["id"])
        if best is None or key < (best[0], best[1]):
            best = (key[0], key[1], r)
    assert best is not None
    return best[2]


def _compute_skeleton(
    rows: list[dict[str, Any]],
    k_threshold: float,
) -> dict[str, Any]:
    """1 クラスのスケルトンと位置別サポートを返す.

    基準列の各位置における「同一トークンを持つメンバー比率」が ``k_threshold``
    以上ならそのトークン、未満なら ``*`` を当て、最後に連続 ``*`` を 1 つに
    圧縮する。
    """
    base = _pick_base(rows)
    base_tokens = _tokenize(base["value"])
    member_tokens = [_tokenize(r["value"]) for r in rows]
    size = len(rows)

    raw: list[str] = []
    supports: list[int] = []
    for p, tok in enumerate(base_tokens):
        support = sum(1 for ts in member_tokens if p < len(ts) and ts[p] == tok)
        supports.append(support)
        raw.append(tok if support / size >= k_threshold else WILDCARD)

    # 連続 ``*`` 圧縮（"a * * b" → "a * b"）。
    compressed: list[str] = []
    for tok in raw:
        if tok == WILDCARD and compressed and compressed[-1] == WILDCARD:
            continue
        compressed.append(tok)

    return {
        "size": size,
        "base_id": base["id"],
        "skeleton": " ".join(compressed),
        "support_per_token": supports,
    }


def process_depth(
    config: PathConfig,
    tau_dir: str,
    level: int,
    depth: str,
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
        initargs=(k_threshold,),
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
    p = argparse.ArgumentParser(description="戦略 skeleton: ≥k% メンバーで出現するトークンを残す")
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
    """全 level × 全 depth でスケルトンを生成する."""
    args = parse_args()
    config = PathConfig()
    workers = args.workers if args.workers is not None else (os.cpu_count() or 1)
    print(f"[CONFIG] workers={workers}", flush=True)

    for level in args.levels:
        for depth in args.depths:
            process_depth(config, args.tau_dir, level, depth, args.k, workers)


if __name__ == "__main__":
    main()
