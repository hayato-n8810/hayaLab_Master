"""RQ2 post-processing scripts.

`outputs/scam/approach_temp_v2_jaccard_tau{0.5,0.7,0.9}/` の集約結果に対し、
論文 RQ2 で報告する以下の集計を行う。

- α × σ クロス表 (singleton 比率・平均クラス規模)
- mb_id ごとの "最小有効サイズ" 分布
- RQ1 既知パターン検出結果との突き合わせ
"""
