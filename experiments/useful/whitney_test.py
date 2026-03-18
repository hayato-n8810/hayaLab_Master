"""TestSecondのJSONデータに対してマンホイットニーのU検定を実行"""

import hayalab
from hayalab.config import PathConfig


def main():
    config = PathConfig()

    """CAMERA_before.jsonとCAMERA_after_all.jsonのデータに対して統計検定を実行"""
    # データファイルのパス
    test_dir = config.experiments / "useful" / "TestSecond"
    before_path = test_dir / "CAMERA_before.json"
    after_path = test_dir / "CAMERA_after_all.json"

    # データ読み込み
    print("データを読み込んでいます...")
    baseline_data = hayalab.read_json(before_path)
    target_data = hayalab.read_json(after_path)

    print(f"CAMERA_before.json: {len(baseline_data)}件のデータ")
    print(f"CAMERA_after_all.json: {len(target_data)}件のデータ")
    print()

    # 基本統計量を表示
    import numpy as np

    print("=== 基本統計量 ===")
    print("CAMERA_before (baseline):")
    print(f"  平均: {np.mean(baseline_data):.6f}")
    print(f"  中央値: {np.median(baseline_data):.6f}")
    print(f"  標準偏差: {np.std(baseline_data, ddof=1):.6f}")
    print()

    print("CAMERA_after_all (target):")
    print(f"  平均: {np.mean(target_data):.6f}")
    print(f"  中央値: {np.median(target_data):.6f}")
    print(f"  標準偏差: {np.std(target_data, ddof=1):.6f}")
    print()

    # マンホイットニーのU検定を実行
    print("=== マンホイットニーのU検定 ===")
    alpha = 0.05
    result = hayalab.mann_whitney_test(baseline_data, target_data, alpha=alpha)

    # 結果を表示
    print(f"有意水準: {result['alpha']}")
    print(f"p値: {result['p_value']:.6f}")
    print(f"U統計量: {result['u_statistic']:.6f}")
    print(f"効果量 (Cliff's Delta): {result['cliff_delta']:.6f}")
    print()

    # 効果量の解釈
    delta = abs(result["cliff_delta"])
    if delta < 0.147:
        effect_size = "negligible (無視できる)"
    elif delta < 0.330:
        effect_size = "small (小)"
    elif delta < 0.474:
        effect_size = "medium (中)"
    else:
        effect_size = "large (大)"

    print(f"効果量の大きさ: {effect_size}")
    print()

    # 検定結果の判定
    if result["significant"]:
        print("✓ 有意差あり")
        print(f"  → CAMERA_beforeとCAMERA_after_allの分布には統計的に有意な差があります (p < {alpha})")
    else:
        print("✗ 有意差なし")
        print(f"  → CAMERA_beforeとCAMERA_after_allの分布に統計的に有意な差は認められません (p >= {alpha})")


if __name__ == "__main__":
    main()
