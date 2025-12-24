from pathlib import Path

from hayalab.classes.codeql import Qlcsv
from hayalab.utils.file.file_clean import code_clean, prettier
from hayalab.utils.file.file_io import read_file


def extract_code_block(qlcsv: Qlcsv, base_path: str = "") -> str:
    """Qlcsvオブジェクトからコードブロックを抽出する。

    Args:
        qlcsv (Qlcsv): CodeQLの実行結果を表すオブジェクト。
        base_path (str, optional): ファイルパスのベースとなるディレクトリ。デフォルトは空文字列。

    Returns:
        str: 指定された行範囲のコードブロック。
    """
    # ファイルパスを構築
    if base_path:
        file_path = str(Path(base_path) / qlcsv.path.lstrip("/"))
    else:
        file_path = qlcsv.path.lstrip("/")

    # ファイルを読み込む
    content = read_file(file_path)

    # 行ごとに分割
    lines = content.splitlines()

    # start_lineからend_lineの範囲を切り出す（1-indexed → 0-indexed）
    # start_lineとend_lineは両端を含む
    start_idx = qlcsv.start_line - 1
    end_idx = qlcsv.end_line

    # 指定範囲の行を取得
    code_block_lines = lines[start_idx:end_idx]

    # 改行で結合
    code_block = "\n".join(code_block_lines)
    code_block = code_clean(code_block)
    code_block = prettier(code_block)
    return code_block
