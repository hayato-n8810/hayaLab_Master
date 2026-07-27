echo "=== Running Step 1 ==="
uv run python experiments/jsperf/setup/step1_integrate.py
echo "=== Running Step 2 ==="
uv run python experiments/jsperf/setup/step2_node.py
echo "=== Running Step 3 ==="
uv run python experiments/jsperf/setup/step3/step3_inject.py