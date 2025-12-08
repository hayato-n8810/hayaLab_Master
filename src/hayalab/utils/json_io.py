import json

def read_json(file_path: str) -> dict:
    """JSONファイルを読み込む。

    Args:
        file_path (str): 読み込むJSONファイルのパス。

    Returns:
        dict: JSONファイルの内容を辞書として返す。
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        return json.load(f)
    
def write_json(data: dict, file_path: str) -> None:
    """辞書をJSONファイルとして書き込む。

    Args:
        data (dict): 書き込むデータ。
        file_path (str): 書き込むJSONファイルのパス。
    """
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)