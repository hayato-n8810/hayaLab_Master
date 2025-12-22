# 実装対において，抽出した特徴が位置する実装対を統合してパターン化する
import hayalab

# データ読み込み
data = hayalab.read_json(f"{hayalab.OUTPUT}/MB_diff/slow_feature.json")

# パターン統合
from hayalab import integrate_features

integrated = integrate_features(data)

# 結果保存
hayalab.write_json(f"{hayalab.OUTPUT}/pattern/MB_slow_patterns_id.json", integrated)
