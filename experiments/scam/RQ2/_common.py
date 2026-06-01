"""RQ2 集計スクリプト共通ユーティリティ.

入力スキーマ (``outputs/scam/approach_temp_v2_jaccard_tau{tau}/classes_A{n}_M{m}.json``):

.. code-block:: json

    [
      {
        "class_id": "L0_M1_9105bb13",
        "abst_level": 0,
        "method": "M1",
        "size": 6129,
        "members": ["10014_Parent", "10019_Parent", ...]
      },
      ...
    ]

cutout_id の形式は ``"{mb_id}_{depth}"`` で、``depth`` は
``{"Diff", "Brother", "ExParent", "Parent"}`` のいずれか。

本モジュールは I/O とパス決定を experiments 側に集約するための補助関数群を
提供し、純粋ロジックは ``src/hayalab`` には置かない (本集計は実験固有のため)。
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Iterable

# サイズ順序（Diff ⊆ Brother ⊆ ExParent ⊆ Parent）。
# ``min_effective_size`` 判定で最小サイズから順に走査する。
DEPTHS: tuple[str, ...] = ("Diff", "Brother", "ExParent", "Parent")

# 抽象化レベルとメソッドの全列挙。集計時の列ヘッダ等で参照する。
ABST_LEVELS: tuple[int, ...] = (0, 1, 2, 3)
METHODS: tuple[str, ...] = ("M1", "M2")

# Jaccard 閾値の既定セット。CLI で個別に指定可能。
TAU_VALUES: tuple[str, ...] = ("0.5", "0.7", "0.9")


def parse_cutout_id(cutout_id: str) -> tuple[int, str]:
    """``"{mb_id}_{depth}"`` を ``(mb_id, depth)`` に分解する.

    Args:
        cutout_id: ``"10014_Parent"`` 形式の文字列.

    Returns:
        ``(mb_id, depth)`` のタプル.

    Raises:
        ValueError: フォーマットが不正な場合.
    """
    # mb_id 側にアンダースコアは含まれない前提だが、念のため右側から分割する.
    idx = cutout_id.rfind("_")
    if idx == -1:
        raise ValueError(f"unexpected cutout_id format: {cutout_id!r}")
    mb_id_str, depth = cutout_id[:idx], cutout_id[idx + 1 :]
    if depth not in DEPTHS:
        raise ValueError(f"unknown depth in cutout_id: {cutout_id!r}")
    return int(mb_id_str), depth


def load_classes(path: Path) -> list[dict[str, Any]]:
    """``classes_A{n}_M{m}.json`` を読み込む.

    Args:
        path: 入力 JSON のパス.

    Returns:
        クラスエントリのリスト.

    Raises:
        FileNotFoundError: ファイルが存在しない場合.
    """
    if not path.exists():
        raise FileNotFoundError(f"入力ファイルが見つかりません: {path}")
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def cutout_to_class(
    classes: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """各 cutout_id を所属クラスのメタ情報に逆引きする辞書を作る.

    Args:
        classes: ``load_classes`` の出力.

    Returns:
        ``{cutout_id: {"class_id": str, "size": int}}``.
    """
    out: dict[str, dict[str, Any]] = {}
    for cls in classes:
        class_id = cls["class_id"]
        size = cls["size"]
        for cutout_id in cls["members"]:
            out[cutout_id] = {"class_id": class_id, "size": size}
    return out


def tau_dir(outputs_root: Path, tau: str) -> Path:
    """τ 別の入力ディレクトリパスを返す.

    Args:
        outputs_root: ``outputs`` ディレクトリ.
        tau: ``"0.5" / "0.7" / "0.9"``.

    Returns:
        ``outputs/scam/approach_temp_v2_jaccard_tau{tau}`` の Path.
    """
    return outputs_root / "scam" / f"approach_temp_v2_jaccard_tau{tau}"


def classes_path(tau_root: Path, level: int, method: str) -> Path:
    """``classes_A{level}_M{method}.json`` のパスを返す."""
    return tau_root / f"classes_A{level}_{method}.json"


def output_dir(outputs_root: Path) -> Path:
    """RQ2 集計結果の出力先 (``outputs/scam/RQ2``)."""
    return outputs_root / "scam" / "RQ2"


def write_json(path: Path, data: Any) -> None:
    """JSON 書き出し (UTF-8, indent=2, ASCII エスケープなし)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def write_csv(path: Path, header: Iterable[str], rows: Iterable[Iterable[Any]]) -> None:
    """CSV 書き出し (UTF-8, LF 改行)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(list(header))
        for row in rows:
            writer.writerow(list(row))
