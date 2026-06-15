r"""事前分析の matcher を cut 部分木に流して既知パターンを構造的に同定する。

字句的な署名述語 $\pi_p$（代表値トークンの包含判定）に代えて，事前分析
(experiments/scam/PreAnalysis/slow_patterns/) の matcher を**検出ロジック無改変**で
クラスタ代表値の元 cut（部分木）に適用し，変更前構造の有無で同定する。

cut 部分木への無改変対応:
  ast_nav は ``nodes[idx].parent``（root からの祖先 full-tree インデックスのパス）と
  「リスト位置 idx」が一致している前提で子を辿る（``walk_pre`` は単なる range(len)）。
  cut ノードは ``origin_index`` と full parent パスを保持しているため，
  「リスト位置 = origin_index のスパース配列」を組めば matcher を無改変で流せる。
  欠損位置は placeholder（name="__absent__", parent=[-1] のセンチネル）で埋める。
  実ノードの親パスは全て >=0 なので placeholder はどの候補名にも一致せず，
  子探索でも拾われない。結果として cut に含まれるノード間だけが正しく辿られ，
  cut の外のノードは「存在しない」ものとして扱われる（cut が捉えた範囲のみで判定）。

注: 同定は Stage A（変更前構造の検出）のみを用いる。is_base_covered / Stage B の
    diff 連動フィルタは使わない（字句 $\pi_p$ と同じく「代表の before 構造の有無」に対応）。
    matcher は具体ノード（value/name）で判定するため抽象化レベル $\alpha$ に依存せず，
    結果は (pair id, depth) のみで決まる。
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

# ---------------------------------------------------------------------------
# hayalab.classes.gumtree（pydantic のみ依存）をスタブ経由で読み込み，
# hayalab パッケージ本体（scipy 等の重い依存）の import を回避する。
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[3]

if "hayalab.classes.gumtree" not in sys.modules:
    _hay = types.ModuleType("hayalab")
    _hay.__path__ = []  # type: ignore[attr-defined]
    _cls = types.ModuleType("hayalab.classes")
    _cls.__path__ = []  # type: ignore[attr-defined]
    sys.modules.setdefault("hayalab", _hay)
    sys.modules.setdefault("hayalab.classes", _cls)
    _spec = importlib.util.spec_from_file_location("hayalab.classes.gumtree", str(ROOT / "src/hayalab/classes/gumtree.py"))
    _gum = importlib.util.module_from_spec(_spec)
    sys.modules["hayalab.classes.gumtree"] = _gum
    _spec.loader.exec_module(_gum)

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experiments.scam.PreAnalysis.slow_patterns.p01_for_in_has_own import (  # noqa: E402
    ForInHasOwnMatcher,
)
from experiments.scam.PreAnalysis.slow_patterns.p02_substr_single_char import (  # noqa: E402
    SubstrSingleCharMatcher,
)
from experiments.scam.PreAnalysis.slow_patterns.p03_string_cast import (  # noqa: E402
    StringCastMatcher,
)
from experiments.scam.PreAnalysis.slow_patterns.p06_split_join_chain import (  # noqa: E402
    SplitJoinChainMatcher,
)
from experiments.scam.PreAnalysis.slow_patterns.p07_to_string_call import (  # noqa: E402
    ToStringCallMatcher,
)
from experiments.scam.PreAnalysis.slow_patterns.p08_modulo_even_odd import (  # noqa: E402
    ModuloEvenOddMatcher,
)
from experiments.scam.PreAnalysis.slow_patterns.p09_higher_order_array import (  # noqa: E402
    HigherOrderArrayMatcher,
)
from hayalab.classes.gumtree import ASTNode  # noqa: E402

# RQ1 で評価する 7 パターンの matcher（検出ロジックは PreAnalysis のまま無改変）
MATCHERS = {
    1: ForInHasOwnMatcher(),
    2: SubstrSingleCharMatcher(),
    3: StringCastMatcher(),
    6: SplitJoinChainMatcher(),
    7: ToStringCallMatcher(),
    8: ModuloEvenOddMatcher(),
    9: HigherOrderArrayMatcher(),
}

_NODE_FIELDS = ("begin", "end", "label", "name", "value", "parent")


def build_subtree_nodes(cut_nodes: list[dict]) -> list[ASTNode]:
    """Cut ノード列から，リスト位置 = origin_index のスパース ASTNode 配列を組む。

    欠損位置は placeholder（matcher に拾われないノード）で埋める。
    """
    max_idx = 0
    for n in cut_nodes:
        max_idx = max(max_idx, n["origin_index"])
        if n.get("parent"):
            max_idx = max(max_idx, max(n["parent"]))

    placeholder = ASTNode(begin=0, end=0, label="", name="__absent__", value="", parent=[-1])
    arr: list[ASTNode] = [placeholder] * (max_idx + 1)
    for n in cut_nodes:
        arr[n["origin_index"]] = ASTNode(**{k: n[k] for k in _NODE_FIELDS})
    return arr


def match_patterns_on_cut(cut_nodes: list[dict]) -> set[int]:
    """Cut 部分木に各 matcher（Stage A のみ）を流し，検出されたパターン id 集合を返す。"""
    if not cut_nodes:
        return set()
    nodes = build_subtree_nodes(cut_nodes)
    hit: set[int] = set()
    for pid, matcher in MATCHERS.items():
        for _pm in matcher.find(nodes, "", mb_id=0):
            hit.add(pid)
            break  # 1 件でも検出されれば充足
    return hit
