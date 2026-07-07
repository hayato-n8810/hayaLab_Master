import csv
import json
from pathlib import Path


def read_file(file_path: str) -> str:
    """ファイルを読み込む。

    Args:
        file_path (str): 読み込むファイルのパス。

    Returns:
        str: ファイルの内容を文字列として返す。
    """
    with open(file_path, "r", encoding="utf-8") as f:
        return f.read()


def write_file(file_path: str, data: str, sort_flg: bool = True) -> None:
    """文字列をファイルとして書き込む。

    Args:
        data (str): 書き込むデータ。
        file_path (str): 書き込むファイルのパス。
        sort_flg (bool): JSONのキーをソートするかどうか。
    """
    Path(file_path).parent.mkdir(parents=True, exist_ok=True)
    with open(file_path, "w", encoding="utf-8", sort_keys=sort_flg) as f:
        f.write(data)


def read_json(file_path: str) -> dict:
    """JSONファイルを読み込む。

    Args:
        file_path (str): 読み込むJSONファイルのパス。

    Returns:
        dict: JSONファイルの内容を辞書として返す。
    """
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_json(file_path: str, data: dict) -> None:
    """辞書をJSONファイルとして書き込む。

    Args:
        data (dict): 書き込むデータ。
        file_path (str): 書き込むJSONファイルのパス。
    """
    Path(file_path).parent.mkdir(parents=True, exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


def read_jsonl(file_path: str) -> list[dict]:
    """JSONL ファイルをリストとして読み込む.

    Args:
        file_path (str): 読み込むJSONLファイルのパス

    Returns:
        list[dict]: JSONLファイルの内容
    """
    records: list[dict] = []
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def write_jsonl(file_path: str, data: list[dict]) -> None:
    """辞書のリストをJSONL として書き出す (順序保存).

    Args:
        data (list[dict]): 書き込むデータ
        file_path (str): 書き込むJSONLファイルのパス
    """
    Path(file_path).parent.mkdir(parents=True, exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        for r in data:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def read_csv(file_path: str) -> dict:
    """CSVファイルを読み込む。

    Args:
        file_path (str): 読み込むcsvファイルのパス。

    Returns:
        dict: csvファイルの内容を返す。
    """
    with open(file_path, "r", encoding="utf-8") as f:
        return list(csv.reader(f))
