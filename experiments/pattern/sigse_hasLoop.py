# SIGSE向け：ループを含む実装対に絞って，特徴を統合してパターン化する
import hayalab
from config import PathConfig
from hayalab import integrate_features

config = PathConfig()

all_data = hayalab.read_json(f"{config.output}/pattern/sigse-bachelor/MB_loop_method_all.json")

has_loop_id = []
for mb_pair in all_data:
    if mb_pair["slow"]["has_loop"] == True or mb_pair["fast"]["has_loop"] == True:
        has_loop_id.append(mb_pair["id"])

print(f"ループを含むMBペアの数: {len(has_loop_id)}")

# データ読み込み
feature_data = hayalab.read_json(f"{config.output}/MB_diff/slow_feature.json")

loop_filtered_data = []
for item in feature_data:
    if item["id"] in has_loop_id:
        loop_filtered_data.append(item)

# パターン統合
integrated = integrate_features(loop_filtered_data)

# feature_idを振る
for i, item in enumerate(integrated):
    item["feature_id"] = i

# 結果保存
hayalab.write_json(f"{config.output}/pattern/sigse-bachelor/MB_slow_patterns.json", integrated)
