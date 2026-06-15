"""approach_minimum 統合 (complete-linkage 版): クラスタ内全ペアが tau 以上.

[integrate.py](integrate.py) の single-linkage（推移的併合 / Union-Find で候補ペアを
無条件に union）に対し、本モジュールは **complete-linkage** を採る。すなわち
生成される各 bigram クラスタについて以下の不変条件を保証する::

    クラスタ内の任意の 2 メンバー (x, y) は Jaccard(x, y) >= tau

single-linkage との違い::

    A-B = 0.8 (>=tau), B-C = 0.8 (>=tau), A-C = 0.3 (<tau)
      single-linkage   : {A, B, C}        （チェーン効果で A-C が閾値未満でも同居）
      complete-linkage : {A, B} と {C}    （A-C が閾値未満なので併合しない）

実装の要点:

1. **完全一致の事前グルーピング**: bigram 集合 (frozenset) が完全一致する cutout
   は Jaccard=1.0 で自明にクリークを成すため、1 つの「代表」にまとめてから類似度
   計算する（同一集合同士の計算を省く）。
2. **転置インデックス候補**: 代表間の類似度は [integrate._scored_pairs](integrate.py)
   を流用し、共通 n-gram を 1 つ以上持つペアのみ計算する。共通 n-gram が 0 のペアは
   Jaccard=0 で必ず tau 未満のため、候補集合に現れないことをもって「併合不可」と
   判定できる（全ペア O(n^2) を回す必要はない）。
3. **complete-linkage 貪欲併合**: 候補ペアを (類似度降順, pair_hash) 順に走査し、
   2 クラスタの cross ペアが全て候補集合 (s>=tau のペア集合) に含まれるときのみ併合
   する。初期状態（各代表が単独クラスタ）で不変条件は自明に成り立ち、併合時に cross
   全ペアを検査することで不変条件が保たれる。

unigram クラスタは [integrate._group_unigrams](integrate.py) の完全一致 grouping を
そのまま使う（完全一致は complete-linkage と整合する）。

入出力・cache・トークン化規約は integrate.py と共通。出力スキーマ（meta / classes /
class_id prefix ``M2`` / ``U1``）も完全互換に保ち、出力先ディレクトリのみ
``integrate_complete`` に分離する（下流の show_label / Representative_value が
``--tau-dir`` と base ディレクトリ指定だけで complete 版も処理できるようにするため）。

入力:
    outputs/scam/approach_minimum/abstract/abstract_level{0,1,2,3}.json
    （cache: bigrams_level{L}_n{N}.pkl を integrate.py と共有）

出力:
    outputs/scam/approach_minimum/integrate_complete/jaccard{NN}/level{L}/{depth}/{depth}.json

実行例:
    uv run python experiments/scam/approach_minimum/integrate_complete.py --taus 0.7 0.9 --workers 40
    uv run python experiments/scam/approach_minimum/integrate_complete.py --levels 0 --taus 0.7
"""

from __future__ import annotations

import argparse
import os
import pickle
from pathlib import Path

import integrate

import hayalab

# 共通定数を integrate から借りる（トークン化・cache 規約の単一情報源を維持）。
DEPTHS = integrate.DEPTHS
ROOT = integrate.ROOT


# ---------------------------------------------------------------------------
# 完全一致の事前グルーピング
# ---------------------------------------------------------------------------


def _group_identical(
    ids: list[str],
    sets: dict[str, frozenset],
) -> tuple[list[str], dict[str, frozenset], dict[str, list[str]]]:
    """bigram 集合が完全一致する cutout を 1 代表にまとめる。

    完全一致集合同士は Jaccard=1.0 で自明にクリークを成すため、代表だけで類似度
    計算・併合判定を行えば計算量を削減できる（同一集合同士の計算を省く）。

    Args:
        ids: cutout_id のリスト。
        sets: ``cutout_id -> bigram frozenset``。

    Returns:
        ``(rep_ids, rep_sets, rep_members)``。

        * ``rep_ids``: 代表 cutout_id のリスト（決定的順序）。各グループの
          メンバーのうち辞書順最小を代表に採る。
        * ``rep_sets``: ``代表 -> bigram frozenset``。
        * ``rep_members``: ``代表 -> グループ全メンバー（代表自身を含む、ソート済み）``。
    """
    groups: dict[frozenset, list[str]] = {}
    for cid in ids:
        groups.setdefault(sets[cid], []).append(cid)

    rep_ids: list[str] = []
    rep_sets: dict[str, frozenset] = {}
    rep_members: dict[str, list[str]] = {}
    for key, members in groups.items():
        members_sorted = sorted(members)
        rep = members_sorted[0]
        rep_ids.append(rep)
        rep_sets[rep] = key
        rep_members[rep] = members_sorted
    rep_ids.sort()
    return rep_ids, rep_sets, rep_members


# ---------------------------------------------------------------------------
# complete-linkage 貪欲併合
# ---------------------------------------------------------------------------


def _ekey(a: str, b: str) -> tuple[str, str]:
    """順序非依存のクラスタペアキー（辞書順で正規化）。"""
    return (a, b) if a < b else (b, a)


def _complete_merge_bigrams(
    level: int,
    rep_ids: list[str],
    rep_members: dict[str, list[str]],
    scored: list[tuple[float, str, str]],
    n_value: int,
    tau: float,
) -> dict[str, list[str]]:
    """代表間の候補から complete-linkage で bigram クラスタを生成する。

    候補ペアを (類似度降順, pair_hash) 順に走査し、2 クラスタが「完全二部結合」
    （全頂点ペアが候補辺で結ばれている）であるときのみ併合する。これにより
    「クラスタ内の任意の 2 代表が tau 以上」という不変条件が保たれる。最後に各代表を
    その完全一致メンバーへ展開してクラスタを構成する（展開後も不変条件は維持される）。

    効率化（cross 判定の O(1) 化）:
        単純実装は併合のたびに ``|Ca|*|Cb|`` 個の cross ペアを候補集合と照合するため
        クラスタが育つと二次的に重い。本実装は **クラスタペア間の候補辺数** を
        ``cross[(root_a, root_b)]`` に保持し、併合可能条件を
        ``cross[(Ca, Cb)] == size[Ca] * size[Cb]`` の O(1) 比較で判定する
        （完全二部結合 ⟺ cross 辺数が頂点ペア数に一致）。併合時は吸収される側の
        隣接クラスタへの辺数を残す側へ加算するだけ（``O(deg)``）で、走査全体は
        候補辺が疎な限り高速。

    Args:
        level: 抽象化レベル。
        rep_ids: 代表 cutout_id のリスト（クラスタ初期化に使用）。
        rep_members: ``代表 -> 完全一致メンバー列``（展開に使用）。
        scored: ``(s, id_a, id_b)`` の候補（``s >= min(taus)`` 済み、代表間のみ）。
        n_value: n-gram の n（class_id content 用）。
        tau: Jaccard 閾値。

    Returns:
        ``{class_id: sorted member cutout_ids}``（決定的順序）。
    """
    # tau でフィルタし、高類似度優先で走査する（同点は pair_hash で決定的に
    # タイブレーク。 integrate.py と同方針）。
    filtered = [(s, a, b) for s, a, b in scored if s >= tau]
    filtered.sort(key=lambda x: (-x[0], integrate._pair_hash(x[1], x[2])))

    # クラスタ管理: Union-Find（経路圧縮）+ サイズ + 代表メンバー列。
    parent: dict[str, str] = {r: r for r in rep_ids}
    size: dict[str, int] = {r: 1 for r in rep_ids}
    members_of: dict[str, list[str]] = {r: [r] for r in rep_ids}

    def find(x: str) -> str:
        root = x
        while parent[root] != root:
            root = parent[root]
        while parent[x] != root:
            parent[x], x = root, parent[x]
        return root

    # cross[(root_a, root_b)] = 2 クラスタ間の候補辺数。adj[root] = 隣接 root 集合。
    # 初期は各代表が単独クラスタなので、候補辺 (a, b) はそのまま頂点ペアの辺 1 本。
    cross: dict[tuple[str, str], int] = {}
    adj: dict[str, set[str]] = {r: set() for r in rep_ids}
    for _s, a, b in filtered:
        k = _ekey(a, b)
        if k not in cross:
            cross[k] = 0
            adj[a].add(b)
            adj[b].add(a)
        cross[k] += 1

    for _s, a, b in filtered:
        ra, rb = find(a), find(b)
        if ra == rb:
            continue
        # 完全二部結合のときのみ併合可能。
        if cross.get(_ekey(ra, rb), 0) != size[ra] * size[rb]:
            continue
        # 大きいクラスタを残して吸収（同サイズは辞書順で決定的に）。
        if size[ra] < size[rb] or (size[ra] == size[rb] and rb < ra):
            ra, rb = rb, ra
        # 吸収される rb の隣接辺を ra 側へ付け替え・加算する。
        for x in list(adj[rb]):
            if x == ra:
                continue
            cnt = cross.pop(_ekey(rb, x))
            kx = _ekey(ra, x)
            cross[kx] = cross.get(kx, 0) + cnt
            adj[x].discard(rb)
            adj[x].add(ra)
            adj[ra].add(x)
        # ra-rb 間の辺・隣接を掃除して union する。
        adj[ra].discard(rb)
        cross.pop(_ekey(ra, rb), None)
        del adj[rb]
        parent[rb] = ra
        size[ra] += size[rb]
        members_of[ra].extend(members_of[rb])
        del members_of[rb]

    # 代表クラスタを完全一致メンバーへ展開し、決定的順序で class 化する。
    expanded: list[list[str]] = []
    for reps in members_of.values():
        cutouts: list[str] = []
        for rep in reps:
            cutouts.extend(rep_members[rep])
        expanded.append(sorted(cutouts))
    expanded.sort()

    classes: dict[str, list[str]] = {}
    for members_sorted in expanded:
        content = f"jaccard_complete:n{n_value}:{','.join(members_sorted)}"
        class_id = integrate._make_class_id(level, content, prefix="M2")
        classes[class_id] = members_sorted
    return classes


# ---------------------------------------------------------------------------
# Level 処理（complete-linkage, 複数 tau 一括）
# ---------------------------------------------------------------------------


def process_level_complete(
    level: int,
    bigrams_table: dict[str, dict[int, frozenset]],
    unigrams_table: dict[str, dict[int, tuple[tuple[str, str], ...]]],
    excluded_table: dict[str, int],
    output_dir: Path,
    n_value: int,
    taus: list[float],
    workers: int,
) -> None:
    """1 レベル分を depth ごと・複数 tau で complete-linkage 統合し JSON を書き出す。

    完全一致グルーピングと候補類似度計算は tau 非依存のため depth ごとに 1 回行い、
    complete-linkage 併合のみ tau ごとに繰り返す（候補集合の構築・cross 判定は
    各 tau で再実行する）。 unigram クラスタは tau 非依存で全 tau 共有する。
    """
    min_tau = min(taus)
    for depth in DEPTHS:
        ids, sets = integrate._build_bigram_patterns(bigrams_table, depth)
        unigrams_d = unigrams_table.get(depth, {})
        excluded_d = excluded_table.get(depth, 0)

        # tau 非依存パート
        unigram_classes = integrate._group_unigrams(level, depth, unigrams_d)
        rep_ids, rep_sets, rep_members = _group_identical(ids, sets)
        scored = integrate._scored_pairs(rep_ids, rep_sets, min_tau, workers)
        print(
            f"[GROUP] level{level} {depth}: patterns={len(ids)} reps={len(rep_ids)} scored_pairs={len(scored)}",
            flush=True,
        )

        for tau in taus:
            bigram_classes = _complete_merge_bigrams(level, rep_ids, rep_members, scored, n_value, tau)
            out_path = output_dir / integrate._tau_dirname(tau) / f"level{level}" / f"{depth}" / f"{depth}.json"
            integrate._write_result(
                out_path,
                level,
                depth,
                n_value,
                tau,
                len(ids),
                len(unigrams_d),
                excluded_d,
                bigram_classes,
                unigram_classes,
            )


# ---------------------------------------------------------------------------
# CLI / main
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    """CLI 引数を解析する。"""
    parser = argparse.ArgumentParser(
        description=("approach_minimum integrate (complete-linkage): クラスタ内全ペアが tau 以上を保証する bigram 併合 + unigram 完全一致 grouping (len=0 cutouts は除外)"),
    )
    parser.add_argument("--input-dir", type=Path, default=None, help="abstract_level{L}.json 置き場")
    parser.add_argument("--output-dir", type=Path, default=None, help="integrate_complete 出力ディレクトリ")
    parser.add_argument(
        "--levels",
        type=int,
        nargs="+",
        default=[0, 1, 2, 3],
        help="処理する抽象化レベル（入力ファイルが存在するもののみ処理）",
    )
    parser.add_argument(
        "--n",
        type=int,
        default=2,
        help="n-gram の n (default: 2 = bigram)。integrate.py と同じ振り分け規約。",
    )
    parser.add_argument(
        "--taus",
        type=float,
        nargs="+",
        default=[0.7, 0.9],
        help="一括処理する Jaccard 閾値群 (default: 0.7 0.9)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="並列ワーカー数 (default: os.cpu_count())。1 で逐次実行",
    )
    parser.add_argument(
        "--create-cache",
        action="store_true",
        help="features cache pickle (integrate.py と共有) を生成・更新する。未指定なら読むのみ。",
    )
    return parser.parse_args()


def main() -> None:
    """全レベル・全 depth の complete-linkage 統合を実行する。"""
    args = parse_args()

    input_dir = args.input_dir or (ROOT / "outputs" / "scam" / "approach_minimum" / "abstract")
    output_dir = args.output_dir or (ROOT / "outputs" / "scam" / "approach_minimum" / "integrate_complete")
    workers = args.workers if args.workers is not None else (os.cpu_count() or 1)

    print(
        f"[CONFIG] MODE=complete-linkage n={args.n} taus={args.taus} workers={workers} levels={args.levels}",
        flush=True,
    )

    for level in args.levels:
        in_path = input_dir / f"abstract_level{level}.json"
        cache_path = integrate._features_cache_path(input_dir, level, args.n)

        features: tuple[dict, dict, dict] | None = None

        # 1. --create-cache 未指定 かつ cache が新鮮なら pickle を load（integrate と共有）
        if not args.create_cache and integrate._is_cache_fresh(cache_path, in_path):
            try:
                features = integrate._load_features_cache(cache_path)
                print(f"[CACHE] fresh, loading from pickle: {cache_path}", flush=True)
            except (ValueError, pickle.UnpicklingError, EOFError) as e:
                print(f"[CACHE] load failed ({e}), falling back to JSON", flush=True)
                features = None

        # 2. cache 不在 / 古い / 破損 / --create-cache 指定: abstract から再構築
        if features is None:
            if not in_path.exists():
                print(f"[SKIP] not found: {in_path}", flush=True)
                continue
            print(f"[INPUT] {in_path}", flush=True)
            records = hayalab.read_json(in_path)
            print(f"[RECORDS] level{level}: {len(records)}", flush=True)
            features = integrate._extract_features(records, DEPTHS, args.n)
            del records
            if args.create_cache:
                integrate._write_features_cache(input_dir, level, args.n, *features)
            else:
                print("[CACHE] no cache write (use --create-cache to persist)", flush=True)

        bigrams_table, unigrams_table, excluded_table = features

        for depth in DEPTHS:
            print(
                f"[FEATURES] level{level} {depth}: bigram={len(bigrams_table.get(depth, {}))}, unigram={len(unigrams_table.get(depth, {}))}, excluded(empty)={excluded_table.get(depth, 0)}",
                flush=True,
            )

        process_level_complete(
            level,
            bigrams_table,
            unigrams_table,
            excluded_table,
            output_dir,
            args.n,
            args.taus,
            workers,
        )


if __name__ == "__main__":
    main()
