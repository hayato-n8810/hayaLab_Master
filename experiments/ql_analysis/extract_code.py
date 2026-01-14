# CodeQLが検出したコードブロックを元のプログラムファイルから抽出する
import hayalab
from hayalab.config import PathConfig

config = PathConfig()

base_path = str(config.root.parent / "jsPerf" / "no_setup_slow")
for i in range(0, 6):
    ql_csv = hayalab.codeql_csv(f"{config.codeql}/output/bachelorQL/id_{i + 1}.csv")
    for result in ql_csv:
        extract_code_block = hayalab.extract_code_block(result, base_path=base_path)
        hayalab.write_file(f"{config.codeql}/output/bachelorQL/id_{i + 1}/block_{result.path.strip('/')}", extract_code_block)
