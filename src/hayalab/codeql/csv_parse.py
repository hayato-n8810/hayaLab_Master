from hayalab.classes.codeql import Qlcsv
from hayalab.utils.file.file_io import read_csv


def codeql_csv(file_path: str) -> list[Qlcsv]:
    """CodeQLの実行結果CSVをパースしてQlcsvクラスのリストを返す。

    Args:
        file_path (str): 読み込むCSVファイルのパス。

    Returns:
        list[Qlcsv]: CSVの各行をQlcsvクラスに変換したリスト。
    """
    csv_data = read_csv(file_path)
    result = []

    for row in csv_data:
        if len(row) == 9:  # 正しい項目数であることを確認
            qlcsv = Qlcsv(name=row[0], description=row[1], severity=row[2], message=row[3], path=row[4], start_line=int(row[5]), start_col=int(row[6]), end_line=int(row[7]), end_col=int(row[8]))
            result.append(qlcsv)

    return result
