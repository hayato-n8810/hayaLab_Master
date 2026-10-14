import json
import tempfile
from subprocess import run

from hayalab.classes.gumtree import *
from hayalab.utils.file.file_clean import code_clean


# gumtreeにおけるAST解析
def exec(*command: str) -> list[str] | None:
    """コマンド実行

    Returns:
        list[str] | None: コマンドの出力
    """
    result = run(
        command,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        return None
    return result.stdout


def gum_parse(code: str, code_clean: bool = True) -> AST:
    """gumtreeによるASTの生成と解析

    Args:
        code (Code): JavaScriptコード

    Returns:
        AST: 生成されたgumtree(tree-sitter)AST
        gumtreeの実行またはJSONの読み込みに失敗した場合は None。

        AST(
            code = "",
            tree = [
                ASTNode(begin=0, end=282, label='program [0,282]', name='program', value='program', parent=[]),
                ...
            ]
        )
    """
    ast: list[ASTNode] = []

    if code_clean:
        code = code_clean(code)

    # 一時ファイルを作成
    with tempfile.NamedTemporaryFile(mode="w", suffix=".js", delete=True, encoding="utf-8") as temp_file:
        temp_file.write(code)
        temp_file.flush()
        # fオプションがないと文字列リテラル中の "\\n"（escape sequence）で出力が改行されるため正しく捕捉できない
        output = exec("gumtree", "parse", "-g", "js-treesitter-ng", "-f", "JSON", temp_file.name)

    if output is None:
        return None
    try:
        root = json.loads(output)["root"]
    except (json.JSONDecodeError, KeyError):
        return None

    # textdiffコマンドの出力がfオプションなしの形式のため
    # gumtree parseのfオプションの出力をfオプションがない場合の出力に変換
    stack: list[tuple[dict, list[int]]] = [(root, [])]
    while stack:
        # 各ノードの祖先インデックス列を parent とする
        node, parent = stack.pop()
        begin = int(node["pos"])
        end = begin + int(node["length"])
        name = node["type"]
        if "label" in node:
            value = node["label"]
            label = f"{name}: {value} [{begin},{end}]"
        else:
            value = name
            label = f"{name} [{begin},{end}]"
        ast.append(ASTNode(begin=begin, end=end, label=label, name=name, value=value, parent=parent))

        # 子を逆順に積み、元の順序で取り出す
        child_parent = parent + [len(ast) - 1]
        for child in reversed(node["children"]):
            stack.append((child, child_parent))

    return AST(code=code, tree=ast)


def gum_diff(base: AST, head: AST) -> GumDiff | None:
    """gumtreeASTの差分解析

    Args:
        base (AST): 変更前のプログラムAST
        head (AST): 変更後のプログラムAST

    Returns:
        GumtreeDiff | None: 差分解析結果
    """
    # 一時ファイルを作成
    base_code = code_clean(base.code)
    head_code = code_clean(head.code)
    with (
        tempfile.NamedTemporaryFile(mode="w", suffix=".js", delete=False, encoding="utf-8") as tmp_base,
        tempfile.NamedTemporaryFile(mode="w", suffix=".js", delete=False, encoding="utf-8") as tmp_head,
    ):
        tmp_base.write(base_code)
        tmp_head.write(head_code)
        tmp_base.flush()
        tmp_head.flush()

        # gumtree diffの実行
        output = exec("gumtree", "textdiff", "-f", "JSON", "-g", "js-treesitter-ng", tmp_base.name, tmp_head.name)

    if output is None:
        return None
    try:
        result = json.loads(output)
    except json.JSONDecodeError:
        print(f"[analysis_diff] JSON decode error: {output}")
        return None

    base_labels = {node.label: i for i, node in enumerate(base.tree)}
    head_labels = {node.label: i for i, node in enumerate(head.tree)}

    # 検出した全ての差分（アクション）について祖先ノードを探索
    base_actions: list[GumAction] = []
    head_actions: list[GumAction] = []
    for action in result["actions"]:
        base_ancestors = list[Ancestor]
        head_ancestors = list[Ancestor]

        # base_ast側の差分の場合
        if action["tree"] in base_labels:
            base_ancestors = trace_ancestors(base.tree, base_labels, action["tree"])
            base_actions.append(GumAction(action=action["action"], tree=action["tree"], index=base_labels[action["tree"]], ancestors=base_ancestors, label=action.get("label"), at=action.get("at")))

        # head_ast側の差分の場合
        elif action["tree"] in head_labels:
            head_ancestors = trace_ancestors(head.tree, head_labels, action["tree"])
            head_actions.append(GumAction(action=action["action"], tree=action["tree"], index=head_labels[action["tree"]], ancestors=head_ancestors, label=action.get("label"), at=action.get("at")))

        else:
            print(f"[analysis_diff] Action tree not found in either AST: {action['tree']}")

    return GumDiff(
        matches=sorted(
            [
                (
                    base_labels[match["src"]],
                    head_labels[match["dest"]],
                )
                for match in result["matches"]
            ]
        ),
        base_ast=base,
        base_actions=base_actions,
        head_ast=head,
        head_actions=head_actions,
    )


def trace_ancestors(ast: List[ASTNode], labels: dict[str, int], action_tree: str) -> list[Ancestor]:
    """編集されたノードについて，祖先ノードを辿り，元のASTでのインデックスとノード名を取得

    Args:
        ast (List[ASTNode]): 対象のAST
        labels (dict[str, int]): ASTの各行とインデックス
        action_tree (str): 編集されたノード

    Returns:
        list[Ancestor]: 祖先ノードの情報
    """
    ancestors: list[Ancestor] = []

    index = labels[action_tree]
    parents = ast[index].parent
    for parent in parents:
        ancestors.append(Ancestor(index=parent, name=ast[parent].name))

    return ancestors
