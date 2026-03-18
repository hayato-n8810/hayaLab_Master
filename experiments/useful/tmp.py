"""
マイクロベンチマークへのCodeQLクエリによる検索結果について
パターンの元となった実装対のIDと検出した実装対のIDを比較し，Recall・Precisionを計算する
"""

from typing import Set

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


def main():
    config = PathConfig()

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

    feature_id = [1, 5, 14, 84, 92, 139]
    for qid, fid in enumerate(feature_id):
        if fid == 14:
            continue

        pattern_ids = load_pattern_ids(MB_pattern, fid)

        for pid in sorted(pattern_ids):
            filePath = f"{config.codeql}/output/bachelorQL/id_{qid + 1}/block_slow_{pid}.js"
            jscode = hayalab.read_file(filePath)
            outputPath = f"/Users/hayato-n/projects/code2vec4js_saiki/ql2vec/origin_pattern/id_{qid + 1}/code/block_slow_{pid}.js"
            hayalab.write_file(outputPath, jscode)

            vectorPath = f"{config.output}/ql_analysis/vector/id_{qid + 1}/vectors/block_slow_{pid}.vector"
            jscodeVector = hayalab.read_file(vectorPath)
            outputPathVector = f"/Users/hayato-n/projects/code2vec4js_saiki/ql2vec/origin_pattern/id_{qid + 1}/vectors/block_slow_{pid}.vector"
            hayalab.write_file(outputPathVector, jscodeVector)


if __name__ == "__main__":
    main()
