import subprocess

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
