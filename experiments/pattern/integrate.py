# 実装対において，抽出した特徴が位置する実装対を統合してパターン化する
import hayalab
from config import PathConfig

config = PathConfig()

# データ読み込み
data = hayalab.read_json(f"{config.output}/MB_diff/slow_feature.json")

# パターン統合

integrated = hayalab.integrate_features(data)

# 結果保存
hayalab.write_json(f"{config.output}/pattern/MB_slow_patterns_id.json", integrated)
