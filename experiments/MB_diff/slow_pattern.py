"""TODO
メソッド呼び出しにおける実行順序の考慮
現在：メソッドは文字列としての登場順
理想：メソッドの呼び出し順

例: JSON.parse(JSON.stringify(VAR_2));
現在 - parse → stringify の登場順
理想 - stringify → parse の実行順

extract_node_feature関数において取得する特徴量
現在は以下の特徴量を取得
- ループ文の種類(for_statement, for_in_statement, while_statement)とその派生特徴量
- メソッド呼び出し(property_identifier)
- new_expression（コンストラクタ呼び出し）
- if_statement（条件分岐）
"""

# AST(gumtree)の差分からパターンを生成する
import logging
from concurrent.futures import ProcessPoolExecutor

import tqdm

import hayalab
from hayalab.classes.gumtree import GumDiff

# 特徴抽出器のインスタンス
feature_extractor = hayalab.DiffFeatureExtractor()


def parallel_extract_pattern(mb_diff_data: dict) -> dict:
    """マイクロベンチマーク差分データからパターンを抽出する並列処理関数

    Args:
        mb_diff_data (dict): マイクロベンチマーク差分データ

    Returns:
        dict: 抽出されたパターンデータ
    """
    mb_id = mb_diff_data["id"]
    diff_data = mb_diff_data.get("diff")

    # 差分データがない場合はスキップ
    if diff_data is None:
        return {"id": mb_id, "pattern": None}

    # Pydanticモデルで復元
    gumtree_diff = GumDiff.model_validate(diff_data)

    # あるMBペアの低速コード（変更前）におけるすべての差分ブロックリスト
    # 対象とするアクション
    TARGET_ACTIONS = ["delete-node", "delete-tree", "update-node"]
    slow_diff_block = hayalab.base_diff_blocks(gumtree_diff, target_actions=TARGET_ACTIONS)

    # 各差分ブロックからパターンを抽出
    mb_slow_pattern = {"id": mb_id, "pattern": []}
    pattern = feature_extractor.extract_features(slow_diff_block).to_dict()
    mb_slow_pattern["pattern"].append(pattern)

    return mb_slow_pattern


if __name__ == "__main__":
    # ログ設定
    logging.basicConfig(filename=f"{hayalab.OUTPUT}/MB_diff/slow_pattern.log", level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", force=True)

    logging.info("===== Program started =====")

    # AST差分データの読み込み（diff.pyで出力されたJSONファイル）
    mb_diff_json = hayalab.read_json(f"{hayalab.OUTPUT}/MB_diff/MBDiff.json")

    total = len(mb_diff_json)
    results = []
    skipped_ids = []

    # 並列処理で実行
    with ProcessPoolExecutor() as executor:
        # tqdmで進捗表示
        patterns = [executor.submit(parallel_extract_pattern, item) for item in mb_diff_json]

        for future in tqdm.tqdm(patterns, total=total, desc="Processing"):
            result = future.result()

            # パターンがNoneの場合はスキップ扱い
            if result["pattern"] is None:
                skipped_ids.append(result["id"])
            else:
                results.append(result)

    # 結果をJSONファイルに出力
    output_path = f"{hayalab.OUTPUT}/MB_diff/slow_pattern.json"
    results.sort(key=lambda x: x["id"])
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
