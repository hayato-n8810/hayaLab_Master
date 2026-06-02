# uv run python experiments/scam/approach_minimum/cutout.py
# python3 experiments/scam/approach_minimum/abstract.py --workers 40 --server
for level in 0 1 2 3; do
    python3 experiments/scam/approach_minimum/integrate.py --server --output-dir "outputs/scam/approach_minimum/integrate" --levels $level --n 2 --taus 0.7 0.9 0.5 --workers 40
done
