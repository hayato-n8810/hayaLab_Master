import json
import subprocess
import tempfile

from hayalab.config.hayalab_path import UTILS
from hayalab.utils.file.file_clean import code_clean


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
        temp_file.write(code.encode("utf-8"))
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
