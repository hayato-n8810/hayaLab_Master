# codeqlの実行結果CSVを解析する

from dataclasses import dataclass


@dataclass
class Qlcsv:
    """CodeQLの実行結果CSVの1行を表すクラス"""

    name: str
    description: str
    severity: str
    message: str
    path: str
    start_line: int
    start_col: int
    end_line: int
    end_col: int
