"""同じ特徴を持つデータを統合してパターンとする"""

import hayalab
from hayalab.config import PathConfig

config = PathConfig()

# ループを含むMBペアのみに絞る
MB_hasLoop_data = hayalab.read_json(f"{config.outputs}/pattern/MB_pre_analysis.json")

has_loop_id = []
for mb_pair in MB_hasLoop_data:
    if mb_pair["slow"]["has_loop"] == True or mb_pair["fast"]["has_loop"] == True:
        has_loop_id.append(mb_pair["id"])

print(f"ループを含むMBペアの数: {len(has_loop_id)}")

# データ読み込み
feature_data = hayalab.read_json(f"{config.outputs}/pattern/slow_feature.json")

loop_filtered_data = []
for item in feature_data:
    if item["id"] in has_loop_id:
        loop_filtered_data.append(item)

# パターン統合
integrated = hayalab.integrate_features(loop_filtered_data)

# feature_idを振る
for i, item in enumerate(integrated):
    item["feature_id"] = i

# 結果保存
hayalab.write_json(f"{config.outputs}/pattern/slow_pattern.json", integrated)
