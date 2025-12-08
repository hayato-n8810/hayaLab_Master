import subprocess
import tempfile
from ...config.hayalab_path import UTILS
import json

# def remove_comment(self, code):
#   return self.node(["node", "comment_remover.js"], code)

def prettier(code: str) -> str:
    """フォーマッターの適応（メモリ上で処理）

    Args:
        code (str): 対象プログラム

    Returns:
        str: フォーマッター適応後プログラム
    """
    result = subprocess.run(
        ["npx", "prettier", "--stdin-filepath", "temp.js"],
        input=code,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    return result.stdout


def code_clean(code: str) -> str:
    """コードの前処理を行う関数

    Args:
        code (str): 元のJavaScriptコード

    Returns:
        str: 前処理後のJavaScriptコード
    """
    # 改行コードの標準化・コメント除去・フォーマッタの適応
    code = code.replace("\r\n", "\n")
    # code = self.remove_comment(code)
    code = prettier(code)

    return code


def babel_parse(code: str) -> tuple[str, dict]:
    """Babelを使用してJavaScriptコードのASTを生成する関数

    Args:
        code (str): JavaScriptコード

    Returns:
        tuple[str, dict]: (整形後のコード, 生成されたAST) のタプル
    """

    # 改行コードの標準化・コメント除去(TODO)・フォーマッタの適応
    code = code_clean(code)

    # 整形後コードが空の場合は終了
    if len(code) == 0:
        return None

    # 一時ファイルでAST生成を実施
    with tempfile.NamedTemporaryFile(suffix=".js", delete=True) as temp_file:
        temp_file.write(code.encode('utf-8'))
        temp_file.flush()

        # AST生成
        ast_str = subprocess.run(
            ["node", f"{UTILS}/ast/babel_parser.js", temp_file.name],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        ).stdout

    if len(ast_str) == 0:
        return None, None
    
    # json形式で読み込み
    ast = json.loads(ast_str)

    return code, ast