"""Representative_value 共通ユーティリティ.

`integrate.py` のクラスタ結果と `show_label.py` の label を入力に、各クラスの
「代表 value」を算出するための共有 I/O 処理を提供する。

純粋ロジック（normalize_value / tokens_from_nodes / bigrams_from_nodes / jaccard /
member_to_mb_id / NGRAMS_CACHE_*）は `integrate.py` 側に集約し、本モジュールは
そこから re-export する。 path 解決・cache 読み込み・並列実行制御だけが本モジュール
固有の責務。

データ前提:
    入力 cluster: ``outputs/scam/approach/integrate/{tau_dir}/level{L}/{depth}/{depth}.json``
        ``{"meta": {...}, "classes": {class_id: ["{id}_{depth}", ...]}}``
    入力 label:   ``outputs/scam/approach/integrate/{tau_dir}/level{L}/{depth}/{depth}_label.json``
        ``{class_id: [{"id": int, "value": str}, ...]}``
    入力 abstract: ``outputs/scam/approach/abstract/abstract_level{L}.json``
        ``[{"id": int, "cutouts": {depth: {"nodes": [...]}}}]``

cutout_id は ``"{mb_id}_{depth}"`` 形式（integrate.py と同様）。
"""

from __future__ import annotations

import pickle
import sys
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import hayalab
from hayalab.config import PathConfig

# integrate.py を sibling import で読み込み（実験スクリプト同士の参照は許容）。
_APPROACH_DIR = Path(__file__).resolve().parent.parent
if str(_APPROACH_DIR) not in sys.path:
    sys.path.insert(0, str(_APPROACH_DIR))

from integrate import (  # noqa: E402  -- sys.path 操作後の sibling import
    DEPTHS,
    NGRAMS_CACHE_SCHEMA,
    NGRAMS_CACHE_VERSION,
    bigrams_from_nodes,
    is_cache_fresh,
    jaccard,
    member_to_mb_id,
    node_token,
    normalize_value,
    tokens_from_nodes,
)

__all__ = [
    # integrate.py からの re-export（純粋ロジック）
    "DEPTHS",
    "NGRAMS_CACHE_SCHEMA",
    "NGRAMS_CACHE_VERSION",
    "bigrams_from_nodes",
    "is_cache_fresh",
    "jaccard",
    "member_to_mb_id",
    "node_token",
    "normalize_value",
    "tokens_from_nodes",
    # I/O ヘルパー（このモジュール固有）
    "abstract_path",
    "bigrams_cache_path",
    "integrate_dir",
    "iter_targets",
    "load_id_to_bigrams",
    "load_id_to_bigrams_cached",
    "load_id_to_tokens",
    "read_inputs",
    "run_parallel",
    "write_output",
]


def load_id_to_bigrams(records: list[dict[str, Any]], depth: str) -> dict[int, frozenset]:
    """指定 depth について、各 mb_id の bigram frozenset を返す."""
    out: dict[int, frozenset] = {}
    for entry in records:
        cutout = entry.get("cutouts", {}).get(depth)
        nodes = cutout.get("nodes", []) if cutout else []
        out[entry["id"]] = bigrams_from_nodes(nodes)
    return out


def load_id_to_tokens(
    config: PathConfig,
    level: int,
) -> dict[str, dict[int, list[tuple[str, str]]]] | None:
    """Abstract JSON から ``{depth: {mb_id: [(name, normalized_value), ...]}}`` を作る.

    bigram 構築の元となる **AST node token 列**（``tokens_from_nodes``）をそのまま
    位置情報付きで保持する。 bigram cache は順序を捨てて frozenset 化しているため
    位置情報が必要な用途では abstract JSON を直接読む必要がある。

    Returns:
        各 depth の ``{mb_id: [(name, normalized_value), ...]}``。
        abstract JSON が無ければ ``None``。
    """
    abs_p = abstract_path(config, level)
    if not abs_p.exists():
        return None
    print(f"[TOKENS] reading abstract: {abs_p}", flush=True)
    records = hayalab.read_json(str(abs_p))
    table: dict[str, dict[int, list[tuple[str, str]]]] = {d: {} for d in DEPTHS}
    for entry in records:
        mb_id = entry["id"]
        cutouts = entry.get("cutouts", {})
        for depth in DEPTHS:
            cutout = cutouts.get(depth)
            if not cutout:
                continue
            table[depth][mb_id] = tokens_from_nodes(cutout.get("nodes", []))
    return table


def integrate_dir(config: PathConfig, tau_dir: str) -> Path:
    """``outputs/scam/approach/integrate/{tau_dir}`` を返す."""
    return config.outputs / "scam" / "approach" / "integrate" / tau_dir


def abstract_path(config: PathConfig, level: int) -> Path:
    """``abstract_level{L}.json`` のパスを返す."""
    return config.outputs / "scam" / "approach" / "abstract" / f"abstract_level{level}.json"


def bigrams_cache_path(config: PathConfig, level: int, n_value: int = 2) -> Path:
    """``abstract/bigrams_level{L}_n{N}.pkl`` のパスを返す.

    ``integrate.py`` が同じパス・スキーマで書き出す。Representative_value 側は
    consumer として読むのみ。
    """
    return abstract_path(config, level).with_name(f"bigrams_level{level}_n{n_value}.pkl")


def load_id_to_bigrams_cached(
    config: PathConfig,
    level: int,
    n_value: int = 2,
) -> dict[str, dict[int, frozenset]] | None:
    """1 レベル分の n-gram テーブルをロードする.

    1. ``bigrams_level{L}_n{N}.pkl`` が abstract JSON より新しければ pickle を
       読む（[BIGRAMS] cache hit）。
    2. pickle がなければ abstract JSON を読み、 ``bigrams_from_nodes`` で計算して
       返す（[BIGRAMS] cache miss → fallback (json)）。 cache の書き出しは行わない
       （producer は ``integrate.py`` に一本化）。
    3. cache も abstract JSON も無ければ ``None`` を返す。

    Args:
        config: パス解決用。
        level: 抽象化レベル。
        n_value: n-gram の n（既定 2）。

    Returns:
        ``{depth: {mb_id: frozenset(n-grams)}}`` または ``None``。
    """
    cache_p = bigrams_cache_path(config, level, n_value)
    abs_p = abstract_path(config, level)

    if is_cache_fresh(cache_p, abs_p):
        with cache_p.open("rb") as f:
            payload = pickle.load(f)  # noqa: S301 -- 自己生成のローカル cache
        if payload.get("version") == NGRAMS_CACHE_VERSION and payload.get("schema") == NGRAMS_CACHE_SCHEMA:
            # producer (integrate.py) は v2 スキーマで bigram を ``bigrams``
            # キーに格納する。 unigram-only / excluded は別キーだが、 medoid は
            # bigram のみ参照し、 利用側が ``.get(id, frozenset())`` で空集合を
            # 補うため bigrams だけ返せば fallback と等価。
            bigrams = payload.get("bigrams")
            if isinstance(bigrams, dict):
                print(f"[BIGRAMS] cache hit: {cache_p}", flush=True)
                # 防御的コピー: depth キーが想定外でも欠落キーは空辞書を返したい。
                return {d: bigrams.get(d, {}) for d in DEPTHS}
            print(
                "[BIGRAMS] cache missing 'bigrams' field, falling back to JSON",
                flush=True,
            )
        else:
            print(
                f"[BIGRAMS] cache version mismatch ({payload.get('version')!r}), falling back to JSON",
                flush=True,
            )

    if not abs_p.exists():
        return None

    print(f"[BIGRAMS] cache miss → fallback to {abs_p}", flush=True)
    records = hayalab.read_json(str(abs_p))
    table: dict[str, dict[int, frozenset]] = {d: {} for d in DEPTHS}
    for entry in records:
        mb_id = entry["id"]
        cutouts = entry.get("cutouts", {})
        for depth in DEPTHS:
            cutout = cutouts.get(depth)
            if not cutout:
                continue
            table[depth][mb_id] = bigrams_from_nodes(cutout.get("nodes", []))
    return table


def read_inputs(
    config: PathConfig,
    tau_dir: str,
    level: int,
    depth: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Cluster と label を読み、片方でも欠けていれば ``(None, None)`` を返す.

    パス: ``integrate/{tau_dir}/level{L}/{depth}/{depth}.json`` および
    ``..._label.json``。 これは ``integrate.py`` と ``show_label.py`` の
    出力規約と一致（depth 名のサブディレクトリにネストする）。
    """
    base = integrate_dir(config, tau_dir) / f"level{level}" / f"{depth}"
    cluster_p, label_p = base / f"{depth}.json", base / f"{depth}_label.json"

    if not cluster_p.exists() or not label_p.exists():
        return None, None
    return hayalab.read_json(str(cluster_p)), hayalab.read_json(str(label_p))


def write_output(
    config: PathConfig,
    tau_dir: str,
    level: int,
    depth: str,
    strategy: str,
    payload: dict[str, Any],
) -> Path:
    """戦略別出力 JSON を書き出してパスを返す."""
    out = integrate_dir(config, tau_dir) / f"level{level}" / f"{depth}" / f"{depth}_pattern_{strategy}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    hayalab.write_json(str(out), payload)
    return out


def iter_targets(
    tau_dir: str,
    levels: list[int],
    depths: tuple[str, ...] = DEPTHS,
):
    """``(level, depth, tau_dir)`` の列挙イテレータ."""
    for level in levels:
        for depth in depths:
            yield level, depth, tau_dir


def run_parallel(
    items: list[Any],
    worker_fn: Callable[[Any], Any],
    workers: int,
    initializer: Callable[..., None] | None = None,
    initargs: tuple = (),
    chunksize: int = 64,
) -> list[Any]:
    """``items`` を ``worker_fn`` で並列処理し、入力順を保った結果リストを返す.

    ``workers <= 1`` または ``len(items) < 2`` のときは逐次実行（このときも
    ``initializer`` を呼んでワーカーグローバルを整え、逐次経路と並列経路の
    挙動を揃える）。

    ``ProcessPoolExecutor.map(items, chunksize)`` を用いるため、結果は入力
    ``items`` と同順で並ぶ。これにより並列実行でも byte-identical な出力を
    保証する（呼び出し側が ``dict(results)`` する際の class_id 順が安定する）。

    Args:
        items: 1 タスクに渡す入力の列。各要素は pickle 可能であること。
        worker_fn: module-level の callable（pickle 可能、ローカル関数不可）。
        workers: 並列ワーカー数。``<= 1`` なら逐次。
        initializer: 各ワーカープロセス起動時に 1 回呼ばれる初期化関数。
        initargs: ``initializer`` への引数。
        chunksize: ``ProcessPoolExecutor.map`` のチャンクサイズ。

    Returns:
        ``[worker_fn(item) for item in items]`` と同順の結果リスト。
    """
    if workers <= 1 or len(items) < 2:
        if initializer is not None:
            initializer(*initargs)
        return [worker_fn(it) for it in items]

    with ProcessPoolExecutor(
        max_workers=workers,
        initializer=initializer,
        initargs=initargs,
    ) as ex:
        return list(ex.map(worker_fn, items, chunksize=chunksize))
