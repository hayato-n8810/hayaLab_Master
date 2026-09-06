"""パターン定義 JSON が target_previous_ast.json の参照 AST にマッチするか検証する。"""

from __future__ import annotations

import json
from pathlib import Path

from hayalab.classes.gumtree import ASTNode
from hayalab.gumtree.tree_pattern import find_tree_matches, load_tree_patterns

if __name__ == "__main__":
    spec_path = Path(__file__).parent / "patterns" / "slow_patterns.json"
    ref_path = Path("outputs/tmp/target_previous_ast.json")

    with open(spec_path, encoding="utf-8") as f:
        patterns = load_tree_patterns(json.load(f))
    with open(ref_path, encoding="utf-8") as f:
        refs = json.load(f)

    for pattern in patterns:
        ref = refs[f"id_{pattern.pattern_id}"]
        nodes = [ASTNode(**t) for t in ref["tree"]]
        own = find_tree_matches(nodes, ref["code"], pattern)
        cross = [p.pattern_id for p in patterns if p.pattern_id != pattern.pattern_id and find_tree_matches(nodes, ref["code"], p)]
        status = "OK " if own else "NG "
        print(f"{status} id_{pattern.pattern_id:<2} {pattern.key:<22} self={len(own)} cross={cross}")
        if own:
            print(f"      snippet: {own[0].snippet!r}")
