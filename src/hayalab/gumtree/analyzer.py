"""GumTreeASTの解析モジュール"""

from hayalab.classes.gumtree import AST


def count_label(ast: AST, label_list: list[str]) -> dict[str, int]:
    """gumtreeAST中のノード検索

    Args:
        ast (AST): 対象のAST
        label_list (list[str]): 検索するノードのラベルのリスト

    Returns:
        dict[str, int]: ノードのラベルとその出現回数の辞書
    """
    label_count = {label: 0 for label in label_list}
    for node in ast.tree:
        if node.name in label_list:
            label_count[node.name] += 1
    return label_count


def collect_method_name(ast: AST) -> list[str]:
    """gumtreeによるASTのメソッド収集

    Args:
        ast (AST): 対象のAST

    Returns:
        list[str]: 収集されたメソッド名のリスト
    """
    method_list = []

    for node in ast.tree:
        if node.name == "property_identifier":
            method_list.append(node.value)

    return method_list
