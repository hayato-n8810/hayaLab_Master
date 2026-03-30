"""
マイクロベンチマークへのCodeQLクエリによる検索結果について
パターンの元となった実装対のIDと検出した実装対のIDを比較し，Recall・Precisionを計算する
"""

import logging
import re
from typing import Set, Tuple

import hayalab
from hayalab.config import PathConfig


def load_origin_ids(json_path: str, feature_id: int) -> Set[int]:
    """
    パターン元となったidをoriginIDとして読み込む

    Args:
        json_path: JSONファイルのパス
        feature_id: 特徴ID

    Returns:
        originIDのセット
    """
    data = hayalab.read_json(json_path)

    # feature_idに対応するidsを取得
    for item in data:
        if item.get("feature_id") == feature_id:
            return set(item.get("ids", []))

    return set()


def load_result_ids(json_path: str) -> Set[int]:
    """
    検出結果からslow_{ID}.jsのIDをresultIDとして読み込む

    Args:
        json_path: JSONファイルのパス

    Returns:
        resultIDのセット
    """
    result_ids = set()

    data = hayalab.read_json(json_path)
    for item in data["results"]:
        filename = item["file_path"]
        # slow_{ID}.jsからIDを抽出
        match = re.search(r"(?:^|/)slow_(\d+)\.js$", filename)
        if match:
            result_ids.add(int(match.group(1)))

    return result_ids


def calculate_metrics(origin_ids: Set[int], result_ids: Set[int]) -> Tuple[Set[int], Set[int], float, float]:
    """
    再現率（Recall）と適合率（Precision）を計算する

    Args:
        origin_ids: originIDのセット
        result_ids: resultIDのセット

    Returns:
        (検出されたoriginID, 検出されなかったoriginID, Recall, Precision)
    """
    # ResultIDに含まれるoriginID
    detected_origin_ids = origin_ids & result_ids

    # ResultIDに含まれなかったoriginID
    undetected_origin_ids = origin_ids - result_ids

    # 再現率（Recall）: ResultIDに含まれるoriginID数 / originID数
    recall = len(detected_origin_ids) / len(origin_ids) if len(origin_ids) > 0 else 0.0

    # 適合率（Precision）: ResultIDに含まれるoriginID数 / ResultID数
    precision = len(detected_origin_ids) / len(result_ids) if len(result_ids) > 0 else 0.0

    return detected_origin_ids, undetected_origin_ids, recall, precision


if __name__ == "__main__":
    config = PathConfig()
    logging.basicConfig(filename=f"{config.outputs}/ql_analysis/microbenchmark/recall_precision.log", level=logging.INFO)

    # ファイルパスの設定
    pattern_path = f"{config.outputs}/pattern/slow_pattern.json"  # パターンの元となった実装対のIDが記載されたJSONファイルのパス
    result_ids_dir = f"{config.codeql}/outputs/microbenchmark/code"  # CodeQLクエリの結果が保存されたディレクトリのパス

    # 作成したパターンとcodeQLクエリの対応表
    # feature_id 1    ---    ID1 for-in
    # feature_id 5    ---    ID2 forEach
    # feature_id 14   ---    ID3 for-in_if_hasOwnProperty
    # feature_id 84   ---    ID4 apply_map
    # feature_id 92   ---    ID5 parse_stringify
    # feature_id 139  ---    ID6 for-of_push

    feature_ids = [1, 5, 14, 84, 92, 139]

    for pattern_id, feature_id in enumerate(feature_ids):
        # patternIDの読み込み
        pattern_ids = load_origin_ids(pattern_path, feature_id)

        # 検出したマイクロベンチマーク低速コードのID（resultID）の読み込み
        QLresults_path = f"{result_ids_dir}/id_{pattern_id + 1}_code.json"
        result_ids = load_result_ids(QLresults_path)

        # メトリクスの計算
        detected, undetected, recall, precision = calculate_metrics(pattern_ids, result_ids)

        # 結果の表示
        logging.info(f"Pattern IDs (feature_id={feature_id}): {len(pattern_ids)}件")
        logging.info(f"Result IDs: {len(result_ids)}件")
        logging.info("=" * 60)
        logging.info("結果")
        logging.info("=" * 60)
        logging.info(f"検出されたpatternID数: {len(detected)}")
        logging.info(f"検出されたpatternID: {sorted(detected)}")
        logging.info("")
        logging.info(f"検出されなかったpatternID数: {len(undetected)}")
        logging.info(f"検出されなかったpatternID: {sorted(undetected)}")
        logging.info("")
        logging.info(f"再現率（Recall）: {recall:.4f} ({recall * 100:.2f}%)")
        logging.info(f"適合率（Precision）: {precision:.4f} ({precision * 100:.2f}%)")
        logging.info("")
        logging.info(f"F1スコア: {2 * (precision * recall) / (precision + recall):.4f}" if (precision + recall) > 0 else "F1スコア: 0.0000")
        logging.info("=" * 60)
        logging.info("\n")
