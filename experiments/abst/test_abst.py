import hayalab

abst_code = hayalab.abst(f"{hayalab.EXPERIMENTS}/abst/test.js")

hayalab.write_file(f"{hayalab.OUTPUT}/abst/test_abst.js", abst_code)
