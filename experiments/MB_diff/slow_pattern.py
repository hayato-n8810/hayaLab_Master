"""TODO
extract_node_feature関数において取得する特徴量（論理構造や引数）の追加
現在は以下の特徴量を取得
- ループ文の種類(for_statement, for_in_statement, while_statement)とその派生特徴量
- メソッド呼び出し(property_identifier)
- new_expression（コンストラクタ呼び出し）

上記に合わせて，出力形式の再考（階層構造の組み方）
"""

# AST(gumtree)の差分からパターンを生成する
import logging

import hayalab
from hayalab.classes.gumtree import AST, ASTNode, GumAction, GumDiff
from hayalab.feature.extractors import DiffFeatureExtractor

# 対象とするアクション
# ACTION_TO_PATTERNS = ["delete-tree", "update-node"]

# 特徴抽出器のインスタンス
feature_extractor = DiffFeatureExtractor()


def cut_diff_blocks(ast: AST, actions: list[GumAction]) -> list[dict]:
    """検出差分ノードブロックを元のASTから抽出

    Args:
        ast (AST): 対象のAST
        actions (list[GumAction]): 検出差分

    Returns:
        list[dict]: 抽出された差分のアクションとそのノードブロック
    """
    # 対象AST
    ast_tree = ast.tree

    diff_blocks = []

    for action in actions:
        # 差分となったノード
        action_node = ast_tree[action.index]
        action_name = action.action
        diff_begin = action_node.begin
        diff_end = action_node.end
        action_parent = set(action_node.parent)
        action_parent.add(action.index)  # 自分自身を親とする要素を求めるため

        # ログ用
        base_idx = action.index
        logging.info(f"action:{base_idx} {action_name}")
        logging.info(f"action node: {action_node}")
        logging.info(f"  diff range: {diff_begin} - {diff_end}")

        # アクションの対象を絞る
        # if action_name not in ACTION_TO_PATTERNS:
        #     logging.info("  skip this action")
        #     logging.info("")
        #     continue

        diff_block: list[ASTNode] = []
        diff_block.append(action_node)
        # 差分ノードをparentにもつ配下ノードをすべて抽出
        for node in ast_tree[action.index :]:
            if set(node.parent) >= action_parent:
                diff_block.append(node)
                # ログ
                base_idx = base_idx + 1
                logging.info("    " * len(set(node.parent) - action_parent) + f"  node:{base_idx} {node}")

        diff_blocks.append({"action": action.action, "diff_block": diff_block})

    logging.info("")
    return diff_blocks


def get_diff_features(diff_block: list[ASTNode], action: str) -> dict:
    """差分ノードブロックから特徴量を抽出（新しい抽出器を使用）

    Args:
        diff_block (list[ASTNode]): ある一つの差分ノードブロック
        action (str): アクション名

    Returns:
        dict: 抽出された特徴量(親子関係を含むネスト構造)
    """
    if not diff_block:
        return {}

    feature_tree = feature_extractor.extract_features(diff_block, action)
    return feature_tree.to_dict()


# ================================================================================
# 以下は旧実装（互換性のため残す）
# ================================================================================


def find_children(node_list: list[ASTNode], target_idx: int, target_parent: list[int]) -> list[ASTNode]:
    """指定したノードの一つ下の子ノードのインデックスを取得

    Args:
        node_list: ASTNodeリスト
        target_idx: node_list中の指定ノードのインデックス
        target_parent: 指定ノードのparent

    Returns:
        子ノードのリスト
    """
    children: list[ASTNode] = []
    target_depth = len(target_parent) + 1
    target_parent_set = set(target_parent)

    # 子要素はtarget_idx以降にしか存在しない
    for node in node_list[target_idx + 1 :]:
        # 指定ノードのparentが完全に含まれ、かつ深さが1つ深い場合，直下の子ノードである
        candidate_parent = node.parent
        if (set(candidate_parent) >= target_parent_set) and (len(candidate_parent) == target_depth):
            children.append(node)
            continue

    return children


def extract_node_feature(nodes_list: list[ASTNode], node: ASTNode, node_idx: int) -> tuple[str | None, list | None]:
    """ノードから特徴を抽出

    Args:
        nodes_list: ASTNodeリスト
        node: nodes_list中の一つのASTNode
        node_idx: nodeのnodes中のインデックス

    Returns:
        (特徴キー, 特徴値)のタプル。特徴がない場合は(None, None)
    """
    name = node.name

    # 1つ下の子ノードを取得
    children_node = find_children(nodes_list, node_idx, node.parent)

    # 取得したい要素があれば追加可能
    if name == "for_statement":
        # 子ノードにbinary_expression(論理演算子)があるか確認
        has_binary = any(child.name == "binary_expression" for child in children_node)
        if has_binary:
            return ("for_statement_binary_expression", None)
        else:
            return ("for_statement", None)

    elif name == "for_in_statement":
        # 子ノードにofがあるか確認
        has_of = any(child.name == "of" for child in children_node)
        if has_of:
            return ("for_of_statement", None)
        else:
            return ("for_in_statement", None)

    elif name == "while_statement":
        # 子ノードにbinary_expression（論理演算子）があるか確認
        has_binary = any(child.name == "binary_expression" for child in children_node)
        if has_binary:
            return ("while_statement_binary_expression", None)
        else:
            return ("while_statement", None)

    elif name == "property_identifier":
        return ("call_exp", [node.value])

    elif name == "new_expression":
        # 子ノードからidentifier(コンストラクタの名前)を探す
        for child in children_node:
            if child.name == "identifier":
                return ("new_exp", [child.value])
        return ("new_exp", [])

    return (None, None)


def build_hierarchy(features_list: list[dict]) -> dict:
    """特徴量リストから階層構造を構築

    入力形式: [
        {'key': str, 'value': list, 'parent': list[int]},
        ...
    ]

    出力形式: {
        'key1': [...],  # valueがlistの場合
        'key2': {       # valueがNoneの場合
            'children': {...}
        },
        ...
    }

    Args:
        features_list: 各ノードの特徴リスト

    Returns:
        階層構造化された辞書
    """
    if not features_list:
        return {}

    def find_direct_parent(idx: int, items: list[dict]) -> int:
        """指定されたインデックスの直接の親インデックスを取得（なければ-1）"""
        current_parent = items[idx]["parent"]
        direct_parent = -1
        min_parent_size = float("inf")

        for i in range(idx):
            other_parent = items[i]["parent"]
            # 親のparentが子のparentに完全に包含される場合、親の候補とする
            # 空チェックと長さチェックを先に
            if not other_parent or len(other_parent) > len(current_parent):
                continue
            if set(other_parent).issubset(current_parent):
                # 最小の親（最も特定的な親）を選ぶ
                if len(other_parent) < min_parent_size:
                    min_parent_size = len(other_parent)
                    direct_parent = i

        return direct_parent

    def build_tree_node(idx: int, items: list[dict]) -> dict:
        """指定されたインデックスのノードを構築"""
        item = items[idx]
        node = {}

        # valueがない、または空リストの場合、childrenを持つ
        if not item.get("value") or (isinstance(item["value"], list) and len(item["value"]) == 0):
            children = {}

            # 直接の子要素を探す
            for i in range(idx + 1, len(items)):
                child_item = items[i]
                direct_parent_idx = find_direct_parent(i, items)

                if direct_parent_idx == idx:
                    child_key = child_item["key"]

                    if not child_item.get("value") or (isinstance(child_item["value"], list) and len(child_item["value"]) == 0):
                        # 子要素もvalueがない
                        children[child_key] = build_tree_node(i, items)
                    else:
                        # 子要素はvalueを持つ
                        if child_key not in children:
                            children[child_key] = []
                        children[child_key].extend(child_item["value"])

            node["children"] = children

        return node

    # メイン処理：トップレベルの要素を見つける
    features = {}

    for idx, item in enumerate(features_list):
        direct_parent = find_direct_parent(idx, features_list)

        # トップレベル（親がない）要素のみ処理
        if direct_parent == -1:
            key = item["key"]
            value = item.get("value", [])

            if not value or (isinstance(value, list) and len(value) == 0):
                # valueがない場合、階層構造を作成
                if key not in features:
                    features[key] = build_tree_node(idx, features_list)
            else:
                # valueがある場合、配列に追加
                if key not in features:
                    features[key] = []
                features[key].extend(value)

    return features


def get_diff_features_legacy(diff_block: list[ASTNode]) -> dict:
    """差分ノードブロックから特徴量を抽出（旧実装）

    Args:
        diff_block (list[ASTNode]): ある一つの差分ノードブロック

    Returns:
        dict: 抽出された特徴量(親子関係を含むネスト構造)
    """
    if not diff_block:
        return {}

    # 各ノードの特徴を抽出(キー、値、深さ、インデックスを保持)
    # ここのインデックスは差分ブロックの中でのインデックス
    diff_features = []
    for idx, node in enumerate(diff_block):
        feature_key, feature_value = extract_node_feature(diff_block, node, idx)
        if feature_key is not None:
            diff_features.append(
                {
                    "key": feature_key,
                    "value": feature_value,
                    "parent": node.parent,
                }
            )

    # 親子関係に基づいて階層構造を構築
    result = build_hierarchy(diff_features)

    return result


if __name__ == "__main__":
    # ログ設定
    logging.basicConfig(
        filename=f"{hayalab.OUTPUT}/MB_diff/slow_pattern.log",
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    logging.info("===== Program started =====")

    # AST差分データの読み込み（diff.pyで出力されたJSONファイル）
    mb_diff_js = hayalab.read_json(f"{hayalab.OUTPUT}/MB_diff/MBDiff.json")
    mb_diff_json = mb_diff_js[0:20]

    print(mb_diff_json)

    total = len(mb_diff_json)
    results = []
    skipped_ids = []

    for item in mb_diff_json:
        mb_id = item["id"]
        diff_data = item.get("diff")

        # 差分データがない場合はスキップ
        if diff_data is None:
            logging.info(f"Skipping {mb_id}: no diff data")
            skipped_ids.append(mb_id)
            continue

        logging.info(f"Processing {mb_id}")

        # Pydanticモデルで復元
        gumtree_diff = GumDiff.model_validate(diff_data)

        # あるMBペアの低速コードにおけるすべての差分ブロックリスト
        diff_blocks = cut_diff_blocks(gumtree_diff.base_ast, gumtree_diff.base_actions)

        # 各差分ブロックからパターンを抽出
        mb_pair_result = {"id": mb_id, "diff_blocks": []}

        # 各アクションについて
        for block in diff_blocks:
            pattern = get_diff_features(block["diff_block"], block["action"])
            # 特徴が抽出されなかった場合はスキップ
            if not pattern.get("features") or not pattern["features"].get("children"):
                logging.info(f"  skip block: {block['action']}")
                logging.info("")
                continue
            mb_pair_result["diff_blocks"].append(pattern)

        results.append(mb_pair_result)

    # 結果をJSONファイルに出力
    output_path = f"{hayalab.OUTPUT}/MB_diff/pattern_results.json"
    hayalab.write_json(output_path, results)

    logging.info(f"Results saved to {output_path}")
    logging.info(f"Total processed: {len(results)}/{total}")
    if skipped_ids:
        logging.info(f"Skipped IDs: {', '.join(skipped_ids)}")
    logging.info("===== Program finished =====")

    # スキップしたIDを標準出力
    if skipped_ids:
        print(f"\nSkipped IDs (no diff data): {', '.join(skipped_ids)}")
    print(f"\nProcessed: {len(results)}/{total}")
    print(f"Results saved to: {output_path}")
