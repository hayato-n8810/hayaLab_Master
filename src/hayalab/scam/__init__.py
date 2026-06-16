"""SCAM2026 論文用の純粋処理ユニット群。

実験エントリ（CLI・パス決定・I/O・並列化・繋ぎロジック）は ``experiments/scam/``
側に置き、 本パッケージは「引数を取り値を返す単体処理」のみを提供する。

サブモジュール:
    ast_nav         フラット AST ナビゲーション純関数
    diff_link       diff 連動フィルタ (is_base_covered, apply_diff_link)
    match           低速パターン matcher 群 (10 パターン)
    abstract        slot 方式抽象化 (level1, level2)
    cluster         bigram + Jaccard + complete-linkage クラスタリング
    representative  代表値選択 (mode/medoid)
"""
