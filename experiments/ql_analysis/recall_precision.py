"""
マイクロベンチマークへのCodeQLクエリによる検索結果について
パターンの元となった実装対のIDと検出した実装対のIDを比較し，Recall・Precisionを計算する
"""

import csv
import logging
import re
from typing import Set, Tuple

import hayalab
from hayalab.config import PathConfig


def load_pattern_ids(json_path: str, feature_id: int) -> Set[int]:
    """
    JSONファイルから指定したfeature_idのidsをpatternIDとして読み込む

    Args:
        json_path: JSONファイルのパス
        feature_id: 対象のfeature_id

    Returns:
        patternIDのセット
    """
    data = hayalab.read_json(json_path)

    # feature_idに対応するidsを取得
    for item in data:
        if item.get("feature_id") == feature_id:
            return set(item.get("ids", []))

    return set()


def load_result_ids(csv_path: str) -> Set[int]:
    """
    CSVファイルの5番目の要素（ファイル名）からslow_{ID}.jsのIDをresultIDとして読み込む

    Args:
        csv_path: CSVファイルのパス

    Returns:
        resultIDのセット
    """
    result_ids = set()

    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        for row in reader:
            if len(row) >= 5:
                filename = row[4]  # 5番目の要素（0-indexed）
                # slow_{ID}.jsからIDを抽出
                match = re.search(r"/slow_(\d+)\.js", filename)
                if match:
                    result_ids.add(int(match.group(1)))

    return result_ids


def calculate_metrics(pattern_ids: Set[int], result_ids: Set[int]) -> Tuple[Set[int], Set[int], float, float]:
    """
    再現率（Recall）と適合率（Precision）を計算する

    Args:
        pattern_ids: patternIDのセット
        result_ids: resultIDのセット

    Returns:
        (検出されたpatternID, 検出されなかったpatternID, Recall, Precision)
    """
    # ResultIDに含まれるpatternID
    detected_pattern_ids = pattern_ids & result_ids

    # ResultIDに含まれなかったpatternID
    undetected_pattern_ids = pattern_ids - result_ids

    # 再現率（Recall）: ResultIDに含まれるpatternID数 / patternID数
    recall = len(detected_pattern_ids) / len(pattern_ids) if len(pattern_ids) > 0 else 0.0

    # 適合率（Precision）: ResultIDに含まれるpatternID数 / ResultID数
    precision = len(detected_pattern_ids) / len(result_ids) if len(result_ids) > 0 else 0.0

    return detected_pattern_ids, undetected_pattern_ids, recall, precision


def main():
    config = PathConfig()
    logging.basicConfig(filename=f"{config.output}/ql_analysis/recall_precision.log", level=logging.INFO)

    """メイン処理"""
    # ファイルパスの設定
    MB_pattern = f"{config.output}/pattern/sigse-bachelor/MB_slow_patterns_id.json"

    # feature_idの指定（必要に応じて変更）
    """
    feature_id 1: for-in
    feature_id 5: forEach
    feature_id 14: for-in_if_hasOwnProperty
    feature_id 84: apply_map
    feature_id 92: parse_stringify
    feature_id 139: for-of_push
    """
    feature_ids = [1, 5, 14, 84, 92, 139]  # 例: "1", "2", "3"など

    for pattern_id, feature_id in enumerate(feature_ids):
        # patternIDの読み込み
        pattern_ids = load_pattern_ids(MB_pattern, feature_id)
        logging.info(f"Pattern IDs (feature_id={feature_id}): {len(pattern_ids)}件")
        # logging.info(f"Pattern IDs: {sorted(pattern_ids)}")

        # 検出したマイクロベンチマーク低速コードのID（resultID）の読み込み
        csv_path = f"{config.codeql}/output/bachelorQL/id_{pattern_id + 1}.csv"
        result_ids = load_result_ids(csv_path)
        logging.info(f"Result IDs: {len(result_ids)}件")

        # メトリクスの計算
        detected, undetected, recall, precision = calculate_metrics(pattern_ids, result_ids)

        # 結果の表示
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


if __name__ == "__main__":
    main()
