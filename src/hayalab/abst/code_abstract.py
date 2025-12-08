import os
import re
import subprocess
from dataclasses import dataclass

@dataclass
class CodeAbstract():
    """jsプログラム抽象化クラス（型定義）"""

    def __init__(self, code: str, ast: dict):
        """コンストラクタ
        
        Args:
            code (str): 元のJavaScriptコード
            ast (dict): パースされたAST
        """
        self.code: str = code
        self.ast: dict = ast
        self.identifiers: list = []
        self.declarations: list = []
        self.literals: list = []
        self.literal_types: dict = {}
        self.template_literals: list = []
        self.counter: dict = {}
        self.abstract_code: str = ""
        self.abstract(self.ast)

    def get_node(self, path):
        """ASTから特定ノードを取得する

        Args:
            path(list): ノードを指定するパス

        Returns:
            node(dict): 該当ノード
        """
        node = self.ast
        for key in path:
            node = node[key]
        return node

    def search_node(self, start, ast=None, path=[]):
        """ASTから指定した位置(start)のノードを探索する（使用していない）

        Args:
            start (number): 探索開始位置
            ast (str, optional): 探索対象AST. デフォルトは None.
            path (list, optional): 現在のあるリテラルまでのパス. デフォルトは None.

        Returns:
            node_path(list): 指定した開始位置のノードまでのパス
        """
        # 指定しない場合（探索開始）は元プログラムAST
        if ast is None:
            ast = self.ast

        # 変数名・関数名の宣言を発見
        if ast["type"] == "Identifier" and ast["start"] == start:
            return path

        # 変数名・関数名の宣言を見つけるまで再帰処理
        for key, value in ast.items():
            # 辞書形式（対象がAST的に子をもつ）かつ type（要素宣言）があるとき
            if type(value) is dict and "type" in value:
                node_path = self.search_node(start, value, path + [key])
                if node_path:
                    return node_path
            # リスト形式（対象が入れ子要素）のとき
            if type(value) is list:
                for i, child in enumerate(value):
                    # 中身について，さらに調査
                    if child is not None:
                        node_path = self.search_node(start, child, path + [key, i])
                        if node_path:
                            return node_path

    def abstract(self, ast, path=[]):
        """ASTを再帰的に探索し，変数・関数を抽象化

        Args:
            ast (str): AST
            path (list, optional): ASTのノードパス. デフォルトは空リスト.
        """
        # 名前のついた変数・関数を確認
        if ast["type"] == "Identifier" and ast["name"] != "undefined":
            # リストを逆順に探索
            for i, floor in enumerate(path[::-1]):
                # 指定した階層に到達した時にそこまでのパスをスコープ範囲として文字列に変換
                if floor in ["body", "consequent", "alternate", "params"]:
                    block_scope = "/".join(map(str, path[: len(path) - i - 1]))
                    break

            # 関数スコープを特定
            function_scope = "program"
            # 関数宣言のIDノードを持つとき
            if path[-1] == "id" and self.get_node(path[:-1])["type"] == "FunctionDeclaration":
                for i, floor in enumerate(path[:-1:-1]):
                    # 最後の要素（id）をのぞいて関数宣言やアロー関数式を探索しスコープを決定
                    if (not (i != 0 and type(path[len(path) - i]) is int)) and self.get_node(path[: len(path) - i])[
                        "type"
                    ] in ["FunctionDeclaration", "ArrowFunctionExpression"]:
                        function_scope = "/".join(map(str, path[: len(path) - i]))
                        break
            else:
                for i, floor in enumerate(path[:1:-1]):
                    if (not (i != 0 and type(path[len(path) - i]) is int)) and self.get_node(path[: len(path) - i])[
                        "type"
                    ] in ["FunctionDeclaration", "ArrowFunctionExpression"]:
                        function_scope = "/".join(map(str, path[: len(path) - i]))
                        break

            self.identifiers.append((ast, path))
            node_address = "/".join(map(str, path))

            # 関数式・アロー関数式の宣言
            if (
                re.search("declarations/[0-9]+/id", "/".join(map(str, path[-3:])))
                and self.get_node(path[:-1] + ["init"]) is not None
                and self.get_node(path[:-1] + ["init"])["type"] in ["ArrowFunctionExpression", "FunctionExpression"]
            ):
                for i, floor in enumerate(path[::-1]):
                    if floor == "declarations":
                        # declarator: var/const/let
                        declarator = self.get_node(path[: len(path) - i - 1])["kind"]
                        break

                if declarator == "var":
                    self.declarations.append(
                        {
                            "name": ast["name"],
                            "type": "FUNCTION",
                            "scope": function_scope,
                            "scope_kind": "function",
                            "path": node_address,
                            "key": False,
                        }
                    )
                else:
                    self.declarations.append(
                        {
                            "name": ast["name"],
                            "type": "FUNCTION",
                            "scope": block_scope,
                            "scope_kind": "block",
                            "path": node_address,
                            "key": False,
                        }
                    )

            # クラス宣言
            elif (
                re.search("declarations/[0-9]+/id", "/".join(map(str, path[-3:])))
                and self.get_node(path[:-1] + ["init"]) is not None
                and self.get_node(path[:-1] + ["init"])["type"] == "ClassExpression"
            ):
                for i, floor in enumerate(path[::-1]):
                    if floor == "declarations":
                        declarator = self.get_node(path[: len(path) - i - 1])["kind"]
                        break

                if declarator == "var":
                    self.declarations.append(
                        {
                            "name": ast["name"],
                            "type": "CLASS",
                            "scope": function_scope,
                            "scope_kind": "function",
                            "path": node_address,
                            "key": False,
                        }
                    )
                else:
                    self.declarations.append(
                        {
                            "name": ast["name"],
                            "type": "CLASS",
                            "scope": block_scope,
                            "scope_kind": "block",
                            "path": node_address,
                            "key": False,
                        }
                    )

            # 変数宣言
            elif re.search("declarations/[0-9]+/id", node_address):
                for i, floor in enumerate(path[::-1]):
                    if floor == "declarations":
                        declarator = self.get_node(path[: len(path) - i - 1])["kind"]
                        break

                if declarator == "var":
                    self.declarations.append(
                        {
                            "name": ast["name"],
                            "type": "VAR",
                            "scope": function_scope,
                            "scope_kind": "function",
                            "path": node_address,
                            "key": False,
                        }
                    )
                else:
                    self.declarations.append(
                        {
                            "name": ast["name"],
                            "type": "VAR",
                            "scope": block_scope,
                            "scope_kind": "block",
                            "path": node_address,
                            "key": False,
                        }
                    )

            # 代入されるクラス宣言
            elif (
                re.search("left", node_address)
                and not re.search("object", node_address)
                and self.get_node(path[: -path[::-1].index("left") - 1])["type"] == "AssignmentExpression"
                and self.get_node(path[: -path[::-1].index("left") - 1])["right"]["type"] == "ClassExpression"
            ):
                is_this = False
                for i in range(len(path)):
                    if path[i] == "object" and self.get_node(path[: i + 1])["type"] == "ThisExpression":
                        is_this = True
                        break

                self.declarations.append(
                    {
                        "name": ast["name"],
                        "type": "CLASS",
                        "scope": "program",
                        "scope_kind": "global",
                        "path": node_address,
                        "key": is_this,
                    }
                )

            # 代入される関数宣言
            elif (
                re.search("left", node_address)
                and not re.search("object", node_address)
                and self.get_node(path[: -path[::-1].index("left") - 1])["type"] == "AssignmentExpression"
                and self.get_node(path[: -path[::-1].index("left") - 1])["right"]["type"]
                in ["ArrowFunctionExpression", "FunctionExpression"]
            ):
                is_this = False
                for i in range(len(path)):
                    if path[i] == "object" and self.get_node(path[: i + 1])["type"] == "ThisExpression":
                        is_this = True
                        break

                self.declarations.append(
                    {
                        "name": ast["name"],
                        "type": "FUNCTION",
                        "scope": "program",
                        "scope_kind": "global",
                        "path": node_address,
                        "key": is_this,
                    }
                )

            # グローバルスコープの変数
            elif (
                re.search("left", node_address)
                and not re.search("object", node_address)
                and self.get_node(path[: -path[::-1].index("left") - 1])["type"] == "AssignmentExpression"
            ):
                is_this = False
                for i in range(len(path)):
                    if path[i] == "property" and self.get_node(path[:i] + ["object"])["type"] == "ThisExpression":
                        is_this = True
                        break

                self.declarations.append(
                    {
                        "name": ast["name"],
                        "type": "VAR",
                        "scope": "program",
                        "scope_kind": "global",
                        "path": node_address,
                        "key": is_this,
                    }
                )

            # 関数のパラメータ
            elif re.search("params", node_address):
                self.declarations.append(
                    {
                        "name": ast["name"],
                        "type": "VAR",
                        "scope": function_scope,
                        "scope_kind": "function",
                        "path": node_address,
                        "key": False,
                    }
                )
            elif re.search("param", node_address):
                self.declarations.append(
                    {
                        "name": ast["name"],
                        "type": "VAR",
                        "scope": function_scope,
                        "scope_kind": "function",
                        "path": node_address,
                        "key": False,
                    }
                )

            # オブジェクトのキー
            elif path[-1] == "key":
                self.declarations.append(
                    {
                        "name": ast["name"],
                        "type": "KEY",
                        "scope": node_address,
                        "scope_kind": "block",
                        "path": node_address,
                        "key": True,
                    }
                )

            # 関数名をもつノード
            elif path[-1] == "id" and self.get_node(path[:-1])["type"] == "FunctionDeclaration":
                self.declarations.append(
                    {
                        "name": ast["name"],
                        "type": "FUNCTION",
                        "scope": function_scope,
                        "scope_kind": "function",
                        "path": node_address,
                        "key": False,
                    }
                )

            # クラス名を持つノード
            elif path[-1] == "id" and self.get_node(path[:-1])["type"] == "ClassDeclaration":
                self.declarations.append(
                    {
                        "name": ast["name"],
                        "type": "CLASS",
                        "scope": function_scope,
                        "scope_kind": "function",
                        "path": node_address,
                        "key": False,
                    }
                )

        # リテラルのとき
        elif ast["type"] == "Literal":
            # 0，1および論理値を除外
            if ast["raw"] not in ["0", "1", "true", "false", "null"]:
                # 正規表現
                if "regex" in ast:
                    literal_type = "REGEX"
                # その他はリテラルの型をjsファイルを経由して出力
                else:
                    with open(f"./parser_{os.getpid()}_literal_type.js", "w") as f:
                        f.write(f"console.log(typeof({ast['raw']}));")

                    out = subprocess.run(
                        f"node ./parser_{os.getpid()}_literal_type.js",
                        shell=True,
                        text=True,
                        capture_output=True,
                    )
                    literal_type = out.stdout[:-1].upper()

                    # 一時ファイルの削除
                    os.remove(f"parser_{os.getpid()}_literal_type.js")

                # 空文字か1文字の文字リテラル以外のリテラルを収集
                if not (literal_type == "STRING" and len(ast["raw"]) <= 2):
                    self.literals.append((ast, path))
                    self.literal_types[ast["raw"]] = literal_type
        # テンプレートリテラル（`***`）は個別に収集
        elif ast["type"] == "TemplateElement":
            self.template_literals.append((ast, path))

        # ASTの入れ子構造を再帰的に取得
        for key, value in ast.items():
            # astが子の要素をもつとき
            if type(value) is dict and "type" in value and value is not None:
                # 親に対する要素名(key)を付与して配下のASTの探索継続
                self.abstract(value, path + [key])
            # astがパラメータを持つ要素のとき
            if type(value) is list:
                # 親に対する要素名(key)と要素の並び順の値(i)を付与して配下のASTの探索継続
                for i, child in enumerate(value):
                    if child is not None:
                        self.abstract(child, path + [key, i])

    def weak_abstract_code(self, counter=None):
        """リテラルを除いた抽象化を行う．

        Args:
            counter (dict, optional): 抽象化した変数の出現回数. デフォルトは None.
        """
        # self.identifiers から同じ開始位置を持つ重複識別子を削除し開始位置でソート
        identifiers = []
        for identifier in sorted(self.identifiers, key=lambda x: x[0]["start"]):
            if len(identifiers) == 0 or identifier[0]["start"] != identifiers[-1][0]["start"]:
                identifiers.append(identifier)

        # "VAR", "FUNCTION", "KEY", "CLASS"をキーとする辞書．valueは空のリスト（[]）
        if counter is None:
            self.counter = {key: [] for key in ["VAR", "FUNCTION", "KEY", "CLASS"]}
        else:
            self.counter = counter

        # declaration: 抽象化する対象
        # identifiers: プログラム中の変数・関数全て

        self.abstract_code = self.code
        i = 0

        # scopeの文字列の長いものからマッチングするように
        sorted_declarations = sorted(self.declarations, key=lambda x: len(x["scope"]), reverse=True)

        for node, path in identifiers:
            path_str = "/".join(map(str, path))
            is_found = False
            match_declaration = []

            # 抽象化対象とプログラム中の変数が一致したら置換
            for declaration in sorted_declarations:
                if (
                    declaration["scope_kind"] != "global"
                    and declaration["name"] == node["name"]
                    and declaration["path"] == path_str
                ):
                    is_found = True
                    match_declaration = declaration
                    break

            if not is_found:
                for declaration in sorted_declarations:
                    if (
                        declaration["scope_kind"] != "global"
                        and declaration["name"] == node["name"]
                        and declaration["scope"] in path_str
                        and path[-1] not in ["property", "callee", "object"]
                    ):
                        is_found = True
                        match_declaration = declaration
                        break

            if not is_found:
                for declaration in sorted_declarations:
                    if (
                        declaration["name"] == node["name"]
                        and (path[-2] == "callee" or path[-1] == "callee")
                        and declaration["type"] == "FUNCTION"
                        and declaration["key"]
                        and path[-1] == "property"
                    ):
                        is_found = True
                        match_declaration = declaration
                        break

            if not is_found:
                for declaration in sorted_declarations:
                    if (
                        declaration["name"] == node["name"]
                        and (path[-2] != "callee" and path[-1] != "callee")
                        and declaration["type"] != "FUNCTION"
                        and declaration["key"]
                        and path[-1] == "property"
                    ):
                        is_found = True
                        match_declaration = declaration
                        break

            if not is_found:
                for declaration in sorted_declarations:
                    if (
                        declaration["scope_kind"] == "global"
                        and declaration["name"] == node["name"]
                        and declaration["path"] == path_str
                    ):
                        is_found = True
                        match_declaration = declaration
                        break

            if not is_found:
                for declaration in sorted_declarations:
                    if (
                        declaration["name"] == node["name"]
                        and (path[-2] == "callee" or path[-1] == "callee")
                        and declaration["type"] == "FUNCTION"
                    ):
                        is_found = True
                        match_declaration = declaration
                        break

            if not is_found:
                for declaration in sorted_declarations:
                    if (
                        declaration["name"] == node["name"]
                        and (path[-2] != "callee" and path[-1] != "callee")
                        and declaration["type"] != "FUNCTION"
                    ):
                        is_found = True
                        match_declaration = declaration
                        break

            if not is_found:
                for declaration in sorted_declarations:
                    if declaration["name"] == node["name"]:
                        is_found = True
                        match_declaration = declaration
                        break

            if not is_found:
                continue

            # 抽象化の型を指定（VAR, FUNCTION ...）
            abstract_token = match_declaration["type"]
            # 初めて置換する変数の場合，計上
            if match_declaration not in self.counter[abstract_token]:
                self.counter[abstract_token].append(match_declaration)

            # 抽象化の数字を振る
            abstract_token += f"_{self.counter[abstract_token].index(match_declaration) + 1}"

            # 置換
            self.abstract_code = (
                self.abstract_code[: node["start"] + i] + abstract_token + self.abstract_code[node["end"] + i :]
            )
            # 置換した分のずれを考慮
            i += len(abstract_token) - (node["end"] - node["start"])