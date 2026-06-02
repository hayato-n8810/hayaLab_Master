"""Representative_value 共通ユーティリティ.

integrate.py のクラスタ結果と show_label.py の label を入力に、各クラスの
「代表 value」をいくつかの戦略で算出するための共有処理を提供する。

* ``integrate.py`` の bigram トークン化と互換な ``bigrams_from_nodes`` を持つ
  ことで、Jaccard 由来の medoid / 共通 bigram 計算がクラスタ生成と整合する。
* path 解決は ``hayalab.config.PathConfig`` に従い、 ``experiments`` 側で
  決定する（ライブラリは I/O パスを決定しない原則）。

データ前提:
    入力 cluster: ``outputs/scam/approach_minimum/integrate/{tau_dir}/level{L}/{depth}.json``
        ``{"meta": {...}, "classes": {class_id: ["{id}_{depth}", ...]}}``
    入力 label:   ``outputs/scam/approach_minimum/integrate/{tau_dir}/level{L}/{depth}_label.json``
        ``{class_id: [{"id": int, "value": str}, ...]}``
    入力 abstract: ``outputs/scam/approach_minimum/abstract/abstract_level{L}.json``
        ``[{"id": int, "cutouts": {depth: {"nodes": [...]}}}]``

cutout_id は ``"{mb_id}_{depth}"`` 形式（integrate.py と同様）。
"""

from __future__ import annotations

import pickle
import re
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import hayalab
from hayalab.config import PathConfig

DEPTHS: tuple[str, ...] = ("Diff", "Brother", "ExParent", "Parent")

# integrate.py と同じ slot 番号正規化（``$v0`` → ``$v``）。
_SLOT_NUM_RE = re.compile(r"^\$([vfkns])\d+$")

# integrate.py の ``NGRAMS_CACHE_VERSION`` と整合させる。
NGRAMS_CACHE_VERSION = 1


def normalize_value(value: str | None) -> str:
    """Slot 番号を捨てて slot タイプのみに正規化する（integrate.py と同義）."""
    if value is None:
        return ""
    m = _SLOT_NUM_RE.match(value)
    if m:
        return f"${m.group(1)}"
    return value


def _node_token(node: dict[str, Any]) -> tuple[str, str]:
    return (node["name"], normalize_value(node.get("value")))


def tokens_from_nodes(nodes: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """``variadic=True`` を除外した ``(name, normalized_value)`` トークン列."""
    return [_node_token(n) for n in nodes if not n.get("variadic", False)]


def bigrams_from_nodes(nodes: list[dict[str, Any]]) -> frozenset[tuple[tuple[str, str], tuple[str, str]]]:
    """integrate.py の bigram と同一の集合を返す（クラスタ定義と整合）."""
    toks = tokens_from_nodes(nodes)
    if len(toks) < 2:
        return frozenset()
    return frozenset(tuple(toks[i : i + 2]) for i in range(len(toks) - 1))


def jaccard(a: frozenset, b: frozenset) -> float:
    """Frozenset の Jaccard 係数（両者空のとき 1.0）."""
    if not a and not b:
        return 1.0
    inter = len(a & b)
    union = len(a) + len(b) - inter
    return inter / union if union else 0.0


def member_to_mb_id(member: str) -> int:
    """cutout_id ``"{mb_id}_{depth}"`` → ``mb_id``（int）."""
    mb_id_str, _depth = member.rsplit("_", 1)
    return int(mb_id_str)


def load_id_to_bigrams(records: list[dict[str, Any]], depth: str) -> dict[int, frozenset]:
    """指定 depth について、各 mb_id の bigram frozenset を返す."""
    out: dict[int, frozenset] = {}
    for entry in records:
        cutout = entry.get("cutouts", {}).get(depth)
        nodes = cutout.get("nodes", []) if cutout else []
        out[entry["id"]] = bigrams_from_nodes(nodes)
    return out


def integrate_dir(config: PathConfig, tau_dir: str) -> Path:
    """``outputs/scam/approach_minimum/integrate/{tau_dir}`` を返す."""
    return config.outputs / "scam" / "approach_minimum" / "integrate" / tau_dir


def abstract_path(config: PathConfig, level: int) -> Path:
    """``abstract_level{L}.json`` のパスを返す."""
    return config.outputs / "scam" / "approach_minimum" / "abstract" / f"abstract_level{level}.json"


def bigrams_cache_path(config: PathConfig, level: int, n_value: int = 2) -> Path:
    """``abstract/bigrams_level{L}_n{N}.pkl`` のパスを返す.

    ``integrate.py`` が同じパス・スキーマで書き出す。Representative_value 側は
    consumer として読むのみ。
    """
    return abstract_path(config, level).with_name(f"bigrams_level{level}_n{n_value}.pkl")


def _is_cache_fresh(cache_path: Path, source_path: Path) -> bool:
    """Cache が存在し source より新しければ ``True``.

    どちらかが欠けていれば ``False``。 source が将来時刻を持っているなど
    異常時も新鮮ではないとして fallback に倒す。
    """
    if not cache_path.exists():
        return False
    if not source_path.exists():
        # source 無し & cache あり: cache は陳腐化判定不能。とりあえず新鮮として
        # 扱う（integrate が古い state で書いた cache を使うリスクは低い）。
        return True
    return cache_path.stat().st_mtime >= source_path.stat().st_mtime


def load_id_to_bigrams_cached(
    config: PathConfig,
    level: int,
    n_value: int = 2,
) -> dict[str, dict[int, frozenset]] | None:
    """1 レベル分の n-gram テーブルをロードする.

    1. ``bigrams_level{L}_n{N}.pkl`` が abstract JSON より新しければ pickle を
       読む（[BIGRAMS] cache hit）。
    2. pickle がなければ abstract JSON を読み、 ``build_id_to_bigrams_table``
       で計算して返す（[BIGRAMS] cache miss → fallback (json)）。
       cache の書き出しは行わない（producer は ``integrate.py`` に一本化）。
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

    if _is_cache_fresh(cache_p, abs_p):
        with cache_p.open("rb") as f:
            payload = pickle.load(f)  # noqa: S301 -- 自己生成のローカル cache
        if payload.get("version") == NGRAMS_CACHE_VERSION and payload.get("schema") == "abst_id_to_ngrams":
            print(f"[BIGRAMS] cache hit: {cache_p}", flush=True)
            data = payload["data"]
            # 防御的コピー: depth キーが想定外でも欠落キーは空辞書を返したい。
            return {d: data.get(d, {}) for d in DEPTHS}
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


def cluster_paths(
    config: PathConfig,
    tau_dir: str,
    level: int,
    depth: str,
) -> tuple[Path, Path]:
    """``({depth}.json, {depth}_label.json)`` のペアを返す."""
    base = integrate_dir(config, tau_dir) / f"level{level}"
    return base / f"{depth}.json", base / f"{depth}_label.json"


def output_path(
    config: PathConfig,
    tau_dir: str,
    level: int,
    depth: str,
    strategy: str,
) -> Path:
    """戦略別の出力パスを返す（``{depth}_pattern_{strategy}.json``）."""
    return integrate_dir(config, tau_dir) / f"level{level}" / f"{depth}_pattern_{strategy}.json"


def read_inputs(
    config: PathConfig,
    tau_dir: str,
    level: int,
    depth: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Cluster と label を読み、片方でも欠けていれば ``(None, None)`` を返す."""
    cluster_p, label_p = cluster_paths(config, tau_dir, level, depth)
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
    out = output_path(config, tau_dir, level, depth, strategy)
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
