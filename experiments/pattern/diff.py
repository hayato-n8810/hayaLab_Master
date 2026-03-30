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
    try:
        # slow_ast = hayalab.gum_parse(mb_data["separate"]["slow"])
        # fast_ast = hayalab.gum_parse(mb_data["separate"]["fast"])
        slow_ast = hayalab.gum_parse(mb_data["slow"])
        fast_ast = hayalab.gum_parse(mb_data["fast"])

        # パース失敗時に1回だけリトライ
        if slow_ast is None:
            # slow_ast = hayalab.gum_parse(mb_data["separate"]["slow"])
            slow_ast = hayalab.gum_parse(mb_data["slow"])
        if fast_ast is None:
            # fast_ast = hayalab.gum_parse(mb_data["separate"]["fast"])
            fast_ast = hayalab.gum_parse(mb_data["fast"])

        # どちらかが None の場合は差分解析を行わずスキップ
        if slow_ast is None or fast_ast is None:
            return {"id": id, "diff": None}

        diff = hayalab.gum_diff(slow_ast, fast_ast)
        return {"id": id, "diff": diff.model_dump() if diff else None}
    except Exception:
        # ワーカー例外で全体が止まらないよう、同じI/O形式で握りつぶす
        return {"id": id, "diff": None}


if __name__ == "__main__":
    from hayalab.config import PathConfig

    config = PathConfig()

    origin_data = hayalab.read_json(f"{config.processed}/MB_separate.json")

    # 並列処理
    results = []
    max_workers = 1  # 同時実行プロセス数を制限
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        results = list(tqdm(executor.map(parallel_diff, origin_data), total=len(origin_data)))

    # パース失敗したIDを出力
    failed_ids = [r["id"] for r in results if r.get("error") == "parse_failed"]
    if failed_ids:
        print(f"\nParse failed for IDs: {', '.join(failed_ids)}")

    # 結果を辞書形式にまとめる
    results.sort(key=lambda x: x["id"])
    hayalab.write_json(f"{config.outputs}/pattern/MBDiff.json", results)
