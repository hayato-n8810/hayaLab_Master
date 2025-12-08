from .code_abstract import CodeAbstract
from ..utils import *


def abst(js_file_path: str) -> str:
    """抽象化実行関数

    Args:
        js_file_path (str): 対象ファイルのパス

    Returns:
        str: 抽象化後のファイル
    """
    
    code = read_file(js_file_path)
    # Babelを使用してASTを生成
    code, ast = babel_parse(code)

    # 弱抽象化の実施（整形後のコードを使用）
    abstcode = CodeAbstract(code, ast)
    abstcode.weak_abstract_code()

    # 抽象化結果を返す
    return abstcode.abstract_code
