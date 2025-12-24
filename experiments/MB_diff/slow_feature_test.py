"""TODO
extract_node_feature関数において取得する特徴量（論理構造や引数）の追加
現在は以下の特徴量を取得
- ループ文の種類(for_statement, for_in_statement, while_statement)とその派生特徴量
- メソッド呼び出し(property_identifier)
- new_expression（コンストラクタ呼び出し）

上記に合わせて，出力形式の再考（階層構造の組み方）
"""

# AST(gumtree)の差分からパターンを生成する
import logging

import hayalab
from hayalab.classes.gumtree import GumDiff

# 特徴抽出器のインスタンス
feature_extractor = hayalab.DiffFeatureExtractor()


if __name__ == "__main__":
    from hayalab.config import PathConfig

    config = PathConfig()

    # ログ設定
    logging.basicConfig(filename=f"{config.output}/MB_diff/slow_feature_test.log", level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", force=True)

    logging.info("===== Program started =====")

    # AST差分データの読み込み（diff.pyで出力されたJSONファイル）
    mb_diff_js = hayalab.read_json(f"{config.output}/MB_diff/MBDiff.json")
    mb_diff_json = mb_diff_js[10:15]

    total = len(mb_diff_json)
    results = []
    skipped_ids = []

    for item in mb_diff_json:
        mb_id = item["id"]
        diff_data = item.get("diff")

        # 差分データがない場合はスキップ
        if diff_data is None:
            logging.info(f"Skipping {mb_id}: no diff data")
            skipped_ids.append(mb_id)
            continue

        logging.info(f"Processing {mb_id}")

        # Pydanticモデルで復元
        gumtree_diff = GumDiff.model_validate(diff_data)

        # あるMBペアの低速コード（変更前）におけるすべての差分ブロックリスト
        # 対象とするアクション
        TARGET_ACTIONS = ["delete-node", "delete-tree", "update-node"]
        slow_diff_blocks = hayalab.base_diff_blocks(gumtree_diff, target_actions=TARGET_ACTIONS)

        # 各差分ブロックからパターンを抽出
        mb_slow_feature = {"id": mb_id, "feature": []}

        feature = feature_extractor.extract_features(slow_diff_blocks).to_dict()
        mb_slow_feature["feature"].append(feature)

        results.append(mb_slow_feature)

    # 結果をJSONファイルに出力
    output_path = f"{config.output}/MB_diff/feature_results_test.json"
    hayalab.write_json(output_path, results)

    logging.info(f"Results saved to {output_path}")
    logging.info(f"Total processed: {len(results)}/{total}")
    if skipped_ids:
        logging.info(f"Skipped IDs: {', '.join(skipped_ids)}")
    logging.info("===== Program finished =====")

    # スキップしたIDを標準出力
    if skipped_ids:
        print(f"\nSkipped IDs (no diff data): {', '.join(skipped_ids)}")
    print(f"\nProcessed: {len(results)}/{total}")
    print(f"Results saved to: {output_path}")
