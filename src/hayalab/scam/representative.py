"""1 クラスのメンバー列から代表 value を選ぶ単体処理（mode + medoid）。

戦略:
    1. メンバーの value 文字列が**過半数 mode**を持つならそれを代表に採用。
    2. 過半数 mode が無ければ **bigram-Jaccard medoid**（他メンバーへの Jaccard
       平均が最大、 同点は mb_id 昇順）を採用。
    3. メンバーが 1 件のみの場合はそのまま代表に採用。

bigram の定義は ``hayalab.scam.cluster.tokens.bigrams_from_nodes`` と完全に同一
（クラスタ生成と整合）。
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from .cluster.jaccard import jaccard


def pick_mode(rows: list[dict[str, Any]]) -> tuple[dict[str, Any], int] | None:
    """Value の過半数 mode を返す。 無ければ ``None``。

    Args:
        rows: ``[{"id": int, "value": str}, ...]``。

    Returns:
        ``(代表 row, support)`` または過半数 mode が無いとき ``None``。
        同 value の中で id 最小のものを代表に採る（決定性確保）。
    """
    counts = Counter(r["value"] for r in rows)
    value, support = counts.most_common(1)[0]
    if support * 2 <= len(rows):  # 過半数条件: support > size / 2
        return None
    cands = [r for r in rows if r["value"] == value]
    representative = min(cands, key=lambda r: r["id"])
    return representative, support


def pick_medoid(
    rows: list[dict[str, Any]],
    id_to_bigrams: dict[int, frozenset],
) -> dict[str, Any]:
    """bigram-Jaccard 平均が最大のメンバーを返す。同点は ``id`` 昇順。

    Args:
        rows: クラスメンバー（``{"id", "value"}``）。
        id_to_bigrams: mb_id → bigram frozenset。

    Returns:
        代表 row。
    """
    sets = [(r, id_to_bigrams.get(r["id"], frozenset())) for r in rows]
    best: tuple[float, int, dict[str, Any]] | None = None
    for r_i, s_i in sets:
        total = sum(jaccard(s_i, s_j) for r_j, s_j in sets if r_j["id"] != r_i["id"])
        avg = total / max(len(sets) - 1, 1)
        key = (-avg, r_i["id"])  # 平均降順、 id 昇順
        if best is None or key < (-best[0], best[1]):
            best = (avg, r_i["id"], r_i)
    assert best is not None
    return best[2]


def representative_for_class(
    rows: list[dict[str, Any]],
    id_to_bigrams: dict[int, frozenset],
) -> dict[str, Any]:
    """1 クラスに対する代表選択結果を作る（mode → medoid → single の優先順）。

    Args:
        rows: クラスメンバー（``[{"id": int, "value": str}, ...]``）。
        id_to_bigrams: medoid 計算用の ``mb_id → bigram frozenset``。

    Returns:
        ``{"size", "strategy", "representative", "support"}`` 形式の dict。
        ``strategy`` は ``"mode" | "medoid" | "single"``。
    """
    size = len(rows)
    if size == 1:
        r = rows[0]
        return {
            "size": 1,
            "strategy": "single",
            "representative": {"id": r["id"], "value": r["value"]},
            "support": 1,
        }

    mode_res = pick_mode(rows)
    if mode_res is not None:
        rep, support = mode_res
        return {
            "size": size,
            "strategy": "mode",
            "representative": {"id": rep["id"], "value": rep["value"]},
            "support": support,
        }

    rep = pick_medoid(rows, id_to_bigrams)
    return {
        "size": size,
        "strategy": "medoid",
        "representative": {"id": rep["id"], "value": rep["value"]},
        "support": sum(1 for r in rows if r["value"] == rep["value"]),
    }
