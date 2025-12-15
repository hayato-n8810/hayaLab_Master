"""パターン統合モジュール

同一の特徴パターンを持つデータをグループ化する
"""

import json
from collections import defaultdict


def integrate_features(data: list[dict]) -> list[dict]:
    """特徴が完全一致するデータを統合

    Args:
        data (list[dict]): IDと特徴のリスト
            各要素は {"id": int, "feature": list[dict]} の形式

    Returns:
        list[dict]: 統合結果のリスト
            各要素は {"feature": list[dict], "origin_num": int, "ids": list[int]} の形式
            origin_numで降順にソート済み
    """
    # featureをJSON文字列化してハッシュキーとして使用
    pattern_groups = defaultdict(list)

    for item in data:
        # featureを正規化したJSON文字列に変換（キーの順序を統一）
        feature_key = json.dumps(item["feature"], sort_keys=False, ensure_ascii=False)
        pattern_groups[feature_key].append(item["id"])

    # 結果を構築
    results = []
    for feature_key, ids in pattern_groups.items():
        # JSON文字列を元のdict形式に戻す
        feature = json.loads(feature_key)
        results.append(
            {
                "feature": feature,
                "origin_num": len(ids),
                "ids": sorted(ids),  # IDをソート
            }
        )

    # origin_numで降順にソート
    results.sort(key=lambda x: x["origin_num"], reverse=True)

    return results
