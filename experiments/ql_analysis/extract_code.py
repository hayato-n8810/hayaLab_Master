# CodeQLが検出したコードブロックを元のプログラムファイルから抽出する
import hayalab
from hayalab.config import PathConfig

config = PathConfig()

ql_csv = hayalab.codeql_csv(f"{config.codeql}/output/bachelorQL/id_3.csv")

base_path = str(config.root.parent / "jsPerf" / "no_setup_slow")
for result in ql_csv:
    extract_code_block = hayalab.extract_code_block(result, base_path=base_path)

    hayalab.write_file(f"{config.codeql}/output/bachelorQL/id_3/block_{result.path.strip('/')}", extract_code_block)
