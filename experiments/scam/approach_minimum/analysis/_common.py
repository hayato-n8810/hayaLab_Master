"""SCAM2026 paper 分析用の共通ユーティリティ.

各 E*.py スクリプトから import される。 ロジックは self-contained に
保ち、 hayalab には依存しない (experiments/ 配下の自己完結方針)。

提供 API:

* ``normalize_value`` — integrate.py の slot 番号 strip と同一
* ``DEPTH_TO_SCOPE_FILE`` — depth → AST_HEAD ファイル名の辞書
* ``ROOT`` — リポジトリルート
* ``INTEGRATE_DIR``, ``RQ1_DIR``, ``AST_HEAD_DIR``, ``ABSTRACT_DIR``, ``OUT_DIR``
* ``load_classes(tau, level, depth)`` → ``{class_id: [member_id, ...]}``
* ``load_meta(tau, level, depth)`` → meta dict
* ``load_representative(tau, level, depth, strategy)`` → ``{class_id: {...}}``
* ``load_rq1_ground_truth(pattern_id)`` → ``[{mb_id, target_id, base_code, head_code}, ...]``
* ``load_ast_head(depth)`` → ``{mb_id: record}``
* ``build_member_to_class(classes, depth)`` → ``{mb_id: class_id}``
* ``KNOWN_PATTERNS`` — Stage-B 通過 ≥ 1 の既知パターン id 一覧 (1,2,3,6,7,8,9)
"""

from __future__ import annotations

import json
import re
from pathlib import Path

# --------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------

# experiments/scam/approach_minimum/analysis/_common.py から
# プロジェクトルートまで 5 階層上がる。
ROOT = Path(__file__).resolve().parents[4]

INTEGRATE_DIR = ROOT / "outputs/scam/approach_minimum/integrate"
RQ1_DIR = ROOT / "outputs/scam/RQ1"
AST_HEAD_DIR = ROOT / "outputs/AST_HEAD"
ABSTRACT_DIR = ROOT / "outputs/scam/approach_minimum/abstract"
OUT_DIR = ROOT / "outputs/scam/approach_minimum/analysis"

# --------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------

DEPTHS: tuple[str, ...] = ("Diff", "Brother", "ExParent", "Parent")
LEVELS: tuple[int, ...] = (0, 1)
TAUS: tuple[float, ...] = (0.7, 0.9)

# Stage-B 通過 ≥ 1 の既知パターン id (paper §preanalysis の tab:pre-result より)
KNOWN_PATTERNS: tuple[int, ...] = (1, 2, 3, 6, 7, 8, 9)

DEPTH_TO_SCOPE_FILE: dict[str, str] = {
    "Diff": "scope_DIFF_BLOCK_all.json",
    "Brother": "scope_BROTHER_DIFF_all.json",
    "ExParent": "scope_BLOCK_EXCLUDE_PARENT_all.json",
    # 注: ファイル名は BLOCK_INCLUDE_DIFF (Parent のラベルだが歴史的事情)
    "Parent": "scope_BLOCK_INCLUDE_DIFF_all.json",
}

REPRESENTATIVE_STRATEGIES: tuple[str, ...] = (
    # paper 議論で採用する代表値の 2 種 (Jun 4 生成済み)。
    # skeleton_node / common_bigrams は今回スコープ外 (paper 言及なし)。
    "skeleton",
    "mode_medoid",
)

# --------------------------------------------------------------------
# slot 番号正規化 (integrate.py:80-95 と同一仕様)
# --------------------------------------------------------------------

_SLOT_NUM_RE = re.compile(r"^\$([vfkns])\d+$")


def normalize_value(value: str | None) -> str:
    """``$v0`` → ``$v`` のように slot 番号を除く。"""
    if value is None:
        return ""
    m = _SLOT_NUM_RE.match(value)
    if m:
        return f"${m.group(1)}"
    return value


# --------------------------------------------------------------------
# tau ディレクトリ名
# --------------------------------------------------------------------


def tau_dirname(tau: float) -> str:
    """0.7 → 'jaccard07', 0.9 → 'jaccard09'."""
    return f"jaccard{round(tau * 10):02d}"


# --------------------------------------------------------------------
# I/O
# --------------------------------------------------------------------


def _read_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def load_classes(tau: float, level: int, depth: str) -> dict[str, list[str]]:
    """``{class_id: [member_id (=\"{mb_id}_{depth}\") ...]}`` を返す。"""
    path = INTEGRATE_DIR / tau_dirname(tau) / f"level{level}" / depth / f"{depth}.json"
    payload = _read_json(path)
    return payload["classes"]


def load_meta(tau: float, level: int, depth: str) -> dict:
    """``{depth}.json`` の meta dict を返す。"""
    path = INTEGRATE_DIR / tau_dirname(tau) / f"level{level}" / depth / f"{depth}.json"
    return _read_json(path)["meta"]


def load_representative(tau: float, level: int, depth: str, strategy: str) -> dict[str, dict]:
    """``{class_id: {代表値 dict}}`` を返す。 ``strategy`` は ``REPRESENTATIVE_STRATEGIES`` のいずれか。"""
    if strategy not in REPRESENTATIVE_STRATEGIES:
        raise ValueError(f"unknown strategy: {strategy!r}")
    path = INTEGRATE_DIR / tau_dirname(tau) / f"level{level}" / depth / f"{depth}_pattern_{strategy}.json"
    return _read_json(path)["classes"]


def load_labels(tau: float, level: int, depth: str) -> dict[str, list[dict]]:
    """``_label.json`` の ``{class_id: [{id, value}, ...]}`` を返す。"""
    path = INTEGRATE_DIR / tau_dirname(tau) / f"level{level}" / depth / f"{depth}_label.json"
    return _read_json(path)


def load_rq1_ground_truth(pattern_id: int) -> list[dict]:
    """``pattern_{pattern_id}/diff_linked.jsonl`` をパースして list で返す。"""
    path = RQ1_DIR / f"pattern_{pattern_id}" / "diff_linked.jsonl"
    out: list[dict] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def load_ast_head(depth: str) -> dict[int, dict]:
    """``{mb_id: record}`` を返す。 record は ``{id, merged.nodes, per_action: [...]}``."""
    fname = DEPTH_TO_SCOPE_FILE[depth]
    path = AST_HEAD_DIR / fname
    payload = _read_json(path)
    # payload は list[record]。 id をキーにした dict に直す。
    out: dict[int, dict] = {}
    for rec in payload:
        out[int(rec["id"])] = rec
    return out


# --------------------------------------------------------------------
# 索引ビルダー
# --------------------------------------------------------------------


def build_member_to_class(classes: dict[str, list[str]], depth: str) -> dict[int, str]:
    """``{mb_id (int): class_id}`` を作る。 member_id は ``"{mb_id}_{depth}"`` 形式。"""
    suffix = f"_{depth}"
    out: dict[int, str] = {}
    for cid, members in classes.items():
        for m in members:
            if m.endswith(suffix):
                mb_id = int(m[: -len(suffix)])
                out[mb_id] = cid
    return out


# --------------------------------------------------------------------
# 出力ヘルパ
# --------------------------------------------------------------------


def ensure_out_dir() -> Path:
    """``outputs/`` を作って返す。"""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    return OUT_DIR
