import hayalab
from hayalab.config import PathConfig

config = PathConfig()

abst_code = hayalab.abst(f"{config.experiments}/abst/test.js")

hayalab.write_file(f"{config.output}/abst/test_abst.js", abst_code)
