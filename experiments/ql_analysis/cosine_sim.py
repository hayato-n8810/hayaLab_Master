"""
マイクロベンチマークへのCodeQLクエリによる検索結果について
パターンの元となった実装対のIDのvectorファイルと、検出した実装対のvectorファイルのコサイン類似度を計算する
"""

import os
import re
from typing import Dict, List, Set

import numpy as np

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


def load_vector(vector_path: str) -> np.ndarray:
    """
    vectorファイルを読み込んでnumpy配列として返す

    Args:
        vector_path: vectorファイルのパス

    Returns:
        ベクトルのnumpy配列
    """
    with open(vector_path, "r", encoding="utf-8") as f:
        content = f.read().strip()
        vector = np.array([float(x) for x in content.split()])
    return vector


def cosine_similarity(vec1: np.ndarray, vec2: np.ndarray) -> float:
    """
    2つのベクトル間のコサイン類似度を計算する

    Args:
        vec1: ベクトル1
        vec2: ベクトル2

    Returns:
        コサイン類似度
    """
    dot_product = np.dot(vec1, vec2)
    norm1 = np.linalg.norm(vec1)
    norm2 = np.linalg.norm(vec2)

    if norm1 == 0 or norm2 == 0:
        return 0.0

    return dot_product / (norm1 * norm2)


def extract_id_from_filename(filename: str) -> str:
    """
    ファイル名からIDを抽出する（拡張子なし）

    Args:
        filename: ファイル名（例: "block_slow_1008.vector"）

    Returns:
        ID部分（例: "1008"）
    """
    # block_slow_{ID}.vectorからIDを抽出
    match = re.search(r"block_slow_(\d+)\.vector", filename)
    if match:
        return match.group(1)
    return ""


def calculate_cosine_similarities(
    target_vector_path: str,
    pattern_vector_paths: List[str],
    target_id: str,
) -> Dict:
    """
    対象のvectorファイルとpatternIDのvectorファイル全てとのコサイン類似度を計算する

    Args:
        target_vector_path: 対象のvectorファイルのパス
        pattern_vector_paths: patternIDのvectorファイルパスのリスト
        target_id: 対象のID

    Returns:
        コサイン類似度の結果辞書
    """
    # 対象のベクトルを読み込む
    target_vector = load_vector(target_vector_path)

    similarities = {}
    similarity_values = []

    for pattern_path in pattern_vector_paths:
        pattern_filename = os.path.basename(pattern_path)
        pattern_id = extract_id_from_filename(pattern_filename)

        # 同じファイルはスキップ
        if pattern_id == target_id:
            continue

        # patternベクトルを読み込む
        pattern_vector = load_vector(pattern_path)

        # コサイン類似度を計算
        similarity = cosine_similarity(target_vector, pattern_vector)

        # キー名を "jsperf_{ID}" 形式にする
        key = f"jsperf_{pattern_id}"
        similarities[key] = similarity
        similarity_values.append(similarity)

    # 平均と分散を計算
    mean = np.mean(similarity_values) if similarity_values else 0.0
    var = np.var(similarity_values) if similarity_values else 0.0

    return {
        "file": f"slow_{target_id}",
        "cos_similarity": [similarities],
        "mean": float(mean),
        "var": float(var),
    }


def main():
    config = PathConfig()

    """メイン処理"""
    # feature_idの指定
    """
    feature_id 1: for-in
    feature_id 5: forEach
    feature_id 14: for-in_if_hasOwnProperty
    feature_id 84: apply_map
    feature_id 92: parse_stringify
    feature_id 139: for-of_push
    """
    feature_ids = [1, 5, 14, 84, 92, 139]

    MB_pattern = f"{config.output}/pattern/sigse-bachelor/MB_slow_patterns_id.json"

    for pattern_id, feature_id in enumerate(feature_ids):
        # patternIDの読み込み
        pattern_ids = load_pattern_ids(MB_pattern, feature_id)

        # vectorsディレクトリのパス
        vectors_dir = f"{config.output}/ql_analysis/vector/id_{pattern_id + 1}/vectors"

        if not os.path.exists(vectors_dir):
            continue

        # vectorsディレクトリ内の全てのvectorファイルを取得
        all_vector_files = sorted([os.path.join(vectors_dir, f) for f in os.listdir(vectors_dir) if f.endswith(".vector")])

        if not all_vector_files:
            continue

        # pattern_idsに含まれるvectorファイルのみを取得
        pattern_vector_files = []
        for vector_file in all_vector_files:
            filename = os.path.basename(vector_file)
            file_id = extract_id_from_filename(filename)
            if file_id and int(file_id) in pattern_ids:
                pattern_vector_files.append(vector_file)

        # 結果を格納するリスト
        results = []

        # 各vectorファイルに対して処理
        for target_vector_path in all_vector_files:
            target_filename = os.path.basename(target_vector_path)
            target_id = extract_id_from_filename(target_filename)

            if not target_id:
                continue

            # コサイン類似度を計算（pattern_idsのvectorファイルとのみ）
            result = calculate_cosine_similarities(
                target_vector_path,
                pattern_vector_files,
                target_id,
            )

            results.append(result)

        # JSON出力
        output_data = {
            "total_count": len(results),
            "results": results,
        }

        output_path = f"{config.output}/ql_analysis/cosine_sim/cosine_sim_id_{pattern_id + 1}.json"
        hayalab.write_json(output_path, output_data)


if __name__ == "__main__":
    main()
