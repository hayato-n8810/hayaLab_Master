"""jsPerf 実行時間計測のシャード割当ユニット群。

計測対象ベンチをシャード (= 専有 CPU コア) へ振り分ける純粋関数を提供する。
ファイルの列挙や結果の読み込みは呼び出し側 (experiments/jsperf/measure/**) に閉じる。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

__all__ = ["assign_shard_slugs", "incomplete_slugs"]


def assign_shard_slugs(slugs: Iterable[str], num_shards: int, shard: int) -> set[str]:
    """ベンチ (slug_id) をシャードへ均等に振り分け、指定シャードの担当分を返す.

    同一 slug_id は必ず単一のシャードへ入るため、ペア (同一ベンチ内の test 群) は
    同一シャード = 同一コアで計測され、ペア内の相対比較の妥当性が保たれる。

    Args:
        slugs: 割当対象の slug_id 群。順序が割当を決めるため、呼び出し側でソート済みを渡す。
        num_shards: 総シャード数。
        shard: 担当シャード番号 (0-based)。

    Returns:
        指定シャードが担当する slug_id の集合。

    Raises:
        ValueError: num_shards が 1 未満、または shard が範囲外のとき。
    """
    if num_shards < 1:
        raise ValueError(f"num_shards must be >= 1: {num_shards}")
    if not (0 <= shard < num_shards):
        raise ValueError(f"shard out of range: shard={shard} num_shards={num_shards}")
    return {s for idx, s in enumerate(slugs) if idx % num_shards == shard}


def incomplete_slugs(tests_by_slug: Mapping[str, Iterable[int]], done_keys: set[tuple[str, int]]) -> list[str]:
    """1 つでも未計測の test を含むベンチ (slug_id) をソート順で返す.

    ベンチ単位で未完了を判定するため、部分的に計測済みのベンチは全 test が再計測対象になる。
    これによりペア内の全 test が同一シャード・同一セッションで計測される状態を保てる。

    Args:
        tests_by_slug: slug_id -> その配下に存在する test_idx 群。
        done_keys: 計測済みの (slug_id, test_idx) 集合。

    Returns:
        未完了ベンチの slug_id を昇順に並べたリスト。
    """
    return sorted(slug for slug, idxs in tests_by_slug.items() if any((slug, i) not in done_keys for i in idxs))
