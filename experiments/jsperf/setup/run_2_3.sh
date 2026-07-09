nohup bash -c '
    uv run python experiments/jsperf/setup/step2_node.py > outputs/jsperf/setup/step2/step2_20260708.log 2>&1 && \
    uv run python experiments/jsperf/setup/step3/step3_inject.py > outputs/jsperf/setup/step3/step3_20260708.log 2>&1
' &