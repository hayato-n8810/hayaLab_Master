"""マイクロベンチマークの差分解析を行う"""

from concurrent.futures import ProcessPoolExecutor

from tqdm import tqdm

import hayalab


def parallel_diff(mb_data: dict) -> dict:
    """マイクロベンチマークの差分解析を並列処理で実行する

    Args:
        mb_data (dict): マイクロベンチマーク実装対

    Returns:
        dict: 差分解析結果
    """
    id = mb_data["id"]
    slow_ast = hayalab.gum_parse(mb_data["slow"])
    fast_ast = hayalab.gum_parse(mb_data["fast"])

    # パース失敗時に1回だけリトライ
    if slow_ast is None:
        slow_ast = hayalab.gum_parse(mb_data["slow"])
    if fast_ast is None:
        fast_ast = hayalab.gum_parse(mb_data["fast"])

    diff = hayalab.gum_diff(slow_ast, fast_ast)
    return {"id": id, "diff": diff.model_dump() if diff else None}


if __name__ == "__main__":
    from config import PathConfig

    config = PathConfig()

    origin_data = hayalab.read_json(f"{config.processed}/MB_separate.json")

    # 並列処理
    results = []
    with ProcessPoolExecutor() as executor:
        results = list(tqdm(executor.map(parallel_diff, origin_data), total=len(origin_data)))

    # パース失敗したIDを出力
    failed_ids = [r["id"] for r in results if r.get("error") == "parse_failed"]
    if failed_ids:
        print(f"\nParse failed for IDs: {', '.join(failed_ids)}")

    # 結果を辞書形式にまとめる
    results.sort(key=lambda x: x["id"])
    hayalab.write_json(f"{config.output}/MB_diff/MBDiff.json", results)
