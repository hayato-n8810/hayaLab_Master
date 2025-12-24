"""実行時間の短縮幅の大きい上位{MAX_ITEMS}件のマイクロベンチマーク実装対をjsファイルに書き出す"""

import os

import hayalab
from config import PathConfig

config = PathConfig()

# # SIGSEの対象（ループを含む実装対）
# sigse_data = hayalab.read_json(f"{config.output}/pattern/sigse/MB_loop_method_all.json")
# has_loop_id = []
# for mb_pair in sigse_data:
#     if mb_pair["slow"]["has_loop"] == True or mb_pair["fast"]["has_loop"] == True:
#         has_loop_id.append(mb_pair["id"])

# 11889件
# print(f"ループを含むMBペアの数: {len(has_loop_id)}")


# 入力ファイルと出力先
mb_data = hayalab.read_json(f"{config.processed}/MB_separate.json")
output_dir_slow = f"{config.root.parent}/jsPerf/no_setup_slow"
output_dir_fast = f"{config.root.parent}/jsPerf/no_setup_fast"

# 最大で何件保存するか（Noneなら全件）
MAX_ITEMS = None
# 件数を制限
limited_data = mb_data[:MAX_ITEMS] if MAX_ITEMS is not None else mb_data
print(f"保存するMBペアの数: {len(limited_data)}")

# ファイル保存ループ
saved_count = 0
skipped_count = 0
error_count = 0
empty_slow = 0
empty_fast = 0

for item in limited_data:
    try:
        idx = item["id"]

        # データ構造を確認
        if "separate" not in item:
            print(f"Warning: ID {idx} has no 'separate' key")
            skipped_count += 1
            continue

        slow_code = item["separate"].get("slow", "")
        fast_code = item["separate"].get("fast", "")

        # 空データのカウント
        if not slow_code or slow_code.strip() == "":
            empty_slow += 1
        if not fast_code or fast_code.strip() == "":
            empty_fast += 1

        # if idx not in has_loop_id:
        #     continue

        output_file_slow = os.path.join(output_dir_slow, f"slow_{idx}.js")
        output_file_fast = os.path.join(output_dir_fast, f"fast_{idx}.js")

        hayalab.write_file(output_file_slow, slow_code)
        hayalab.write_file(output_file_fast, fast_code)
        saved_count += 1

    except Exception as e:
        print(f"Error processing ID {idx}: {e}")
        error_count += 1

print(f"Saved JavaScript programs: {saved_count} pairs ({saved_count * 2} files)")
print(f"Empty slow code: {empty_slow}")
print(f"Empty fast code: {empty_fast}")
print(f"Skipped: {skipped_count}")
print(f"Errors: {error_count}")
