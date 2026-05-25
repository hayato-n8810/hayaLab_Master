r"""粒度判定スクリプト: sibling_completeness ベース

各ターゲット ID のスコープ候補から

    score = diff_ratio × sibling_completeness（調和平均）

が最大となるスコープを選択する

## スコープ候補

候補は以下の4種類を包含順（小さい順）に評価する：

    DIFF ⊆ BROTHER ⊆ EXCL ⊆ INCL

## 選択スコア

    diff_ratio
        = |diff_nodes| / |scope_nodes|
        スコープ内に占める差分ノードの割合
        スコープが小さいほど高く 大きくするほど低下する
        要素数を減らす方向の重み

    sibling_completeness
        = diff の各ノードの直接親について
          その親の全直接子のうち scope に含まれる割合を平均したもの
          スコープが大きいほど高くなる傾向がある
          要素数を増やす方向の重み

    score = 2 * diff_ratio * sibling_completeness / (diff_ratio + sibling_completeness)
        調和平均により両者の圧力を組み合わせることで
        「差分が密で かつ差分周辺の兄弟ノードが揃っている」スコープを選ぶ

## Hard Constraint

    str_R = 1
        スコープの全終端トークン値を \\s* で連結した正規表現が
        対象プログラムの base_ast.code にマッチすること
        これを満たさない候補はスコープ選択の対象外とする
        目的：処理断片として元コード上に成立していることを確認する

## 出力

    outputs/pattern/granularity_decided_all.json
        各 ID の粒度判定結果（選択スコープ・全候補スコア）

    outputs/pattern/candidate_bone.json
        フィルタリング後の全候補について 終端トークン値を連結した program_born_full
"""

from __future__ import annotations

import re
from concurrent.futures import ProcessPoolExecutor, as_completed

from tqdm import tqdm

import hayalab
from hayalab.config import PathConfig

# ── 定数 ─────────────────────────────────────────────────────────────────────

# 抽象化変数のプレフィックス（VAR_0, FUNCTION_1, KEY_2 など）
_ABSTRACT_VALUE_PREFIXES: tuple[str, ...] = ("VAR_", "FUNCTION_", "KEY_")

# 記号のみ候補フィルタリング：終端ノードのうち有意なトークンとみなさない node name
_MEANINGLESS_NODE_NAMES: frozenset[str] = frozenset({"string_fragment", "escape_sequence", "number"})

# 記号のみ候補フィルタリング：有意なトークンとみなさない終端 value
# （構文記号・算術演算子・宣言キーワード）
_MEANINGLESS_TERMINAL_VALUES: frozenset[str] = frozenset(
    {
        "(",
        ")",
        ",",
        ";",
        "{",
        "}",
        "[",
        "]",
        '"',
        "'",
        '\\"',
        "+",
        "-",
        "*",
        "/",
    }
)


# ── 文字列軸（正規表現）検索 ──────────────────────────────────────────────────


def build_token_regex(nodes: list[dict]) -> str | None:
    r"""スコープの全終端トークン値を \s* で連結した正規表現を生成する.

    終端ノード（label が "name: value" 形式のノード）の value を出現順に取り出し
    \s*（空白文字 0 個以上）で連結する 空白のみの value は除外する

    \s* を採用する理由：JavaScriptコードではトークン間にスペース・タブ・改行が
    任意に入るため \s* が最も自然なセパレータとなる（.* はノイズが多すぎる）

    Args:
        nodes: ASTノードのリスト

    Returns:
        正規表現文字列 生成できる終端トークンがなければ None
    """
    terminal_values: list[str] = []
    for node in nodes:
        # "name: value" 形式のラベルを持つノードが終端ノード
        if not re.match(r"([^ ]+): (.+)", node["label"]):
            continue
        value = node["value"]
        if not value.strip():
            continue
        terminal_values.append(re.escape(value))

    if not terminal_values:
        return None
    return r"\s*".join(terminal_values)


def matches_source_code(regex: str, source_code: str) -> bool:
    r"""正規表現がソースコードにマッチするか判定する（re.DOTALL）.

    Args:
        regex: build_token_regex で生成した正規表現
        source_code: 対象プログラムの base_ast.code

    Returns:
        マッチすれば True しなければ False（正規表現エラーも False）
    """
    try:
        return bool(re.compile(regex, re.DOTALL).search(source_code))
    except re.error:
        return False


# ── 候補前処理 ────────────────────────────────────────────────────────────────


def collect_candidates(
    cutouts: dict[str, dict] | None,
) -> list[dict]:
    """新スキーマ cutouts (Stage 1 出力 outputs/scam/approach/01_cutouts.json の cutouts) を
    スコープ候補リストに展開する.

    包含関係の小さい順（Diff → Brother → ExParent → Parent）で展開することで
    後続の deduplicate_candidates が小さいスコープを優先して残す.

    Args:
        cutouts: {"Diff": {"diff_node_indices": [...], "nodes": [...]}, ...} の dict
            None または該当キー無しのスコープはスキップする

    Returns:
        [{name: "merged_diff" | "merged_brother" | ..., nodes: [...]}] の候補リスト
    """
    if cutouts is None:
        return []
    # 旧名 (merged_diff / merged_brother / merged_excl / merged_incl) を保持して
    # 後段の get_diff_nodes(name == "merged_diff") との互換を維持する
    name_map: tuple[tuple[str, str], ...] = (
        ("Diff", "merged_diff"),
        ("Brother", "merged_brother"),
        ("ExParent", "merged_excl"),
        ("Parent", "merged_incl"),
    )
    candidates: list[dict] = []
    for scope_key, legacy_name in name_map:
        cut = cutouts.get(scope_key)
        if cut is None:
            continue
        nodes = cut.get("nodes", [])
        if not nodes:
            continue
        candidates.append({"name": legacy_name, "nodes": nodes})
    return candidates


def _is_single_trivial_terminal(nodes: list[dict]) -> bool:
    """ノードリストが単一の trivial terminal のみで構成されるか判定する.

    終端ノード（label が "name: value" 形式のノード）の個数を数え，
    ちょうど 1 個で，かつそれが以下のいずれかに該当する場合のみ True を返す：
      - node name が _MEANINGLESS_NODE_NAMES に含まれる
      - value が抽象化変数プレフィックス（VAR_*, FUNCTION_*, KEY_*）で始まる
      - value が _MEANINGLESS_TERMINAL_VALUES に含まれる
      - value が空白のみ

    終端ノードが 2 個以上ある候補は，たとえ全てが上記に該当しても False を返す
    （= 除外しない）．
    終端ノードが 0 個の候補も False（= 除外しない）．
    """
    # 終端ノードのみ抽出
    terminals: list[dict] = []
    for node in nodes:
        if re.match(r"([^ ]+): (.+)", node["label"]):
            terminals.append(node)

    # トークンが1つのみの場合フィルタリング対象あれば除外対象外
    if len(terminals) != 1:
        return False

    node = terminals[0]
    if node["name"] in _MEANINGLESS_NODE_NAMES:
        return True
    value = node["value"]
    if value.startswith(_ABSTRACT_VALUE_PREFIXES):
        return True
    if value in _MEANINGLESS_TERMINAL_VALUES:
        return True
    if not value.strip():
        return True
    return False


def filter_symbolic_candidates(candidates: list[dict]) -> list[dict]:
    """単一の trivial terminal のみで構成される候補を除外する.

    終端ノードが 1 個だけで，かつそれがフィルタ定数のいずれか
    （_MEANINGLESS_NODE_NAMES / _ABSTRACT_VALUE_PREFIXES /
    _MEANINGLESS_TERMINAL_VALUES / 空白）に該当する候補のみを排除する．
    複数の終端ノードを持つ候補は全て保持される．

    Args:
        candidates: collect_candidates の結果

    Returns:
        フィルタ後の候補リスト
    """
    return [c for c in candidates if not _is_single_trivial_terminal(c["nodes"])]


def deduplicate_candidates(candidates: list[dict]) -> list[dict]:
    """ノード集合が同一の候補を重複除去し 小さいスコープ側を残す.

    origin_index の frozenset が一致する候補を同一とみなす
    collect_candidates を包含順（小→大）で呼んでいれば
    先に出現した（小さい）スコープが残る

    per_action が1件しかない ID では DIFF と BROTHER が同一ノード集合になるケースがある

    Args:
        candidates: collect_candidates（またはフィルタ後）の候補リスト

    Returns:
        重複除去後の候補リスト
    """
    seen_node_sets: dict[frozenset[int], dict] = {}
    for candidate in candidates:
        node_index_set = frozenset(node["origin_index"] for node in candidate["nodes"])
        if node_index_set not in seen_node_sets:
            seen_node_sets[node_index_set] = candidate
    return list(seen_node_sets.values())


# ── str_R 評価 ────────────────────────────────────────────────────────────────


def evaluate_str_r(
    candidates: list[dict],
    target_source_code: str,
) -> list[dict]:
    r"""各候補の str_R（処理断片として元コードに成立するか）を評価する.

    全終端トークン値を \s* で連結した正規表現が target_source_code にマッチすれば
    str_R = 1 しなければ str_R = 0 とする

    str_R はスコープ選択の Hard Constraint として使う

    Args:
        candidates: 前処理済みの候補リスト
        target_source_code: 対象プログラムの base_ast.code

    Returns:
        各候補に str_R と regex_query を追加したリスト
    """
    evaluated: list[dict] = []
    for candidate in candidates:
        regex_query = build_token_regex(candidate["nodes"])
        str_r: int = 0
        if regex_query and matches_source_code(regex_query, target_source_code):
            str_r = 1

        evaluated.append(
            {
                "name": candidate["name"],
                "nodes": candidate["nodes"],
                "str_R": str_r,
                "regex_query": regex_query,
            }
        )
    return evaluated


# ── スコアリング ──────────────────────────────────────────────────────────────


def get_diff_nodes(candidates: list[dict]) -> list[dict]:
    """候補リストから diff スコープのノードリストを返す.

    deduplicate_candidates によって merged_diff が除去された場合は
    ノード数が最小の候補で代用する（包含順に渡しているため最も小さいスコープ）

    Args:
        candidates: 前処理済みの候補リスト

    Returns:
        diff_nodes のノードリスト（候補が空なら []）
    """
    diff_candidate = next((c for c in candidates if c["name"] == "merged_diff"), None)
    if diff_candidate is not None:
        return diff_candidate["nodes"]
    # merged_diff が重複除去で消えた場合は最小スコープで代用
    return min(candidates, key=lambda c: len(c["nodes"]))["nodes"] if candidates else []


def calc_diff_ratio(scope_nodes: list[dict], diff_nodes: list[dict]) -> float:
    """スコープ内に占める差分ノードの割合（diff_ratio）を返す.

    値が大きいほどスコープが小さい（差分ノードが密）
    スコープノードが空のときは 0.0 を返す

    Args:
        scope_nodes: 評価対象スコープのノードリスト
        diff_nodes: DIFF スコープのノードリスト（分子の基準）

    Returns:
        diff_ratio ∈ [0.0, 1.0]
    """
    if not scope_nodes:
        return 0.0
    return len(diff_nodes) / len(scope_nodes)


def calc_sibling_completeness(
    scope_nodes: list[dict],
    diff_nodes: list[dict],
    full_tree: list[dict],
) -> float:
    """差分ノードの直接親について 兄弟ノードがスコープに揃っている割合の平均を返す.

    算出手順：
      1. diff_nodes の各ノードから直接親のインデックス（parent[-1]）を収集し
         重複を除いた diff_parent_indices を作る
      2. 各親について full_tree 全体から「直接子ノード」（parent[-1] == 親インデックス）
         を全て列挙する
      3. その直接子のうち scope_nodes に含まれるものの割合を計算する
      4. 全ての親にわたる割合の平均を返す

    NOTE: full_tree を走査することでスコープ外の兄弟も分母に含める
    これにより スコープが兄弟を取りこぼしている場合に値が下がる

    Args:
        scope_nodes: 評価対象スコープのノードリスト
        diff_nodes: DIFF スコープのノードリスト（直接親の基準）
        full_tree: 対象プログラムの full AST ノード列

    Returns:
        sibling_completeness ∈ [0.0, 1.0]
    """
    scope_index_set: set[int] = {node["origin_index"] for node in scope_nodes}

    # diff_nodes の各ノードから直接親インデックスを収集する
    # parent が空のノード（ルートノード等）はスキップ
    diff_parent_indices: set[int] = {node["parent"][-1] for node in diff_nodes if node.get("parent")}
    if not diff_parent_indices:
        return 0.0

    per_parent_ratios: list[float] = []
    for parent_idx in diff_parent_indices:
        # full_tree から parent[-1] == parent_idx の全直接子インデックスを取得する
        all_direct_children: list[int] = [i for i, node in enumerate(full_tree) if node.get("parent") and node["parent"][-1] == parent_idx]
        if not all_direct_children:
            continue

        children_in_scope = sum(1 for i in all_direct_children if i in scope_index_set)
        per_parent_ratios.append(children_in_scope / len(all_direct_children))

    if not per_parent_ratios:
        return 0.0
    return sum(per_parent_ratios) / len(per_parent_ratios)


# ── 選択 ──────────────────────────────────────────────────────────────────────


def select_best_scope(
    evaluated_candidates: list[dict],
    diff_nodes: list[dict],
    full_tree: list[dict],
) -> dict | None:
    """str_R=1 を満たす候補から score が最大のものを返す.

    score = 2 * diff_ratio * sibling_completeness / (diff_ratio + sibling_completeness)
    （調和平均）

    Hard Constraint として str_R=1 を満たすもののみを対象とする
    viable な候補がなければ None を返す

    Args:
        evaluated_candidates: evaluate_str_r の結果リスト
        diff_nodes: calc_diff_ratio / calc_sibling_completeness の基準となる差分ノード列
        full_tree: calc_sibling_completeness で使う full AST ノード列

    Returns:
        score が最大の候補 dict または None
    """
    # Hard Constraint：処理断片として元コードに成立する候補のみ
    viable_candidates = [c for c in evaluated_candidates if c["str_R"] == 1]
    if not viable_candidates:
        return None

    def score(candidate: dict) -> float:
        d_ratio = calc_diff_ratio(candidate["nodes"], diff_nodes)
        sib_comp = calc_sibling_completeness(candidate["nodes"], diff_nodes, full_tree)
        return 2 * d_ratio * sib_comp / (d_ratio + sib_comp) if (d_ratio + sib_comp) > 0 else 0.0

    return max(viable_candidates, key=score)


# ── program_born_full 生成 ──────────────────────────────────────────────────────


def build_program_born_full(nodes: list[dict]) -> str:
    """終端ノードの value をスペース区切りで連結した文字列を生成する.

    get_label_bone.py の target_gularity にならい label が "name: value" 形式の
    終端ノードの value のみを収集してスペース区切りで連結する

    Args:
        nodes: ASTノードのリスト

    Returns:
        終端トークン値を空白区切りで連結した文字列
    """
    parts: list[str] = []
    for node in nodes:
        if re.match(r"([^ ]+): (.+)", node["label"]):
            parts.append(node["value"])
    return " ".join(parts)


# ── 並列ワーカー ──────────────────────────────────────────────────────────────


def _process_single_id(args: tuple) -> tuple[dict, dict]:
    """1つのプログラム ID について粒度判定を実行する（並列ワーカー）.

    ProcessPoolExecutor から呼ばれるためモジュールレベルの関数として定義する

    Args:
        args: (program_id, cutouts, full_tree, source_code)
            cutouts: Stage 1 (01_cutouts.json) の 1 MB 分の "cutouts" dict

    Returns:
        (output_record, bone_entry)
            output_record: 粒度判定結果（全候補スコア・選択スコープ）
            bone_entry: フィルタリング後の全候補の program_born_full
    """
    program_id, cutouts, full_tree, source_code = args

    # ── 候補の収集・前処理 ──
    candidates = collect_candidates(cutouts)

    # フィルタリング前（重複除去前）の全候補の bone
    all_candidates_bones: list[dict] = [
        {
            "scope_name": c["name"],
            "bone": build_program_born_full(c["nodes"]),
        }
        for c in candidates
    ]

    candidates = deduplicate_candidates(candidates)
    candidates = filter_symbolic_candidates(candidates)

    # ── str_R 評価・スコープ選択 ──
    diff_nodes = get_diff_nodes(candidates)
    evaluated_candidates = evaluate_str_r(candidates, source_code)
    best_candidate = select_best_scope(evaluated_candidates, diff_nodes, full_tree)

    # ── 全候補の詳細スコアを記録 ──
    candidate_details: list[dict] = []
    for cand in evaluated_candidates:
        d_ratio = calc_diff_ratio(cand["nodes"], diff_nodes)
        sib_comp = calc_sibling_completeness(cand["nodes"], diff_nodes, full_tree)
        harmonic = 2 * d_ratio * sib_comp / (d_ratio + sib_comp) if (d_ratio + sib_comp) > 0 else 0.0

        candidate_details.append(
            {
                "scope_name": cand["name"],
                "node_count": len(cand["nodes"]),
                "bone": build_program_born_full(cand["nodes"]),
                "str_R": cand["str_R"],
                "regex_query": cand["regex_query"],
                "diff_ratio": round(d_ratio, 4),
                "sibling_completeness": round(sib_comp, 4),
                "score": round(harmonic, 4),
            }
        )

    # 選択されたスコープ
    output_record: dict = {"id": program_id, "scope_name": best_candidate["name"] if best_candidate else None, "nodes": best_candidate["nodes"] if best_candidate else []}

    # 候補に関する情報
    instruction_entry: dict = {"id": program_id, "all_candidates": all_candidates_bones, "after_filter_candidates": candidate_details, "selected": best_candidate["name"] if best_candidate else None}

    return output_record, instruction_entry


# ── メイン ────────────────────────────────────────────────────────────────────


def main() -> None:
    """全ターゲット ID の粒度判定を並列実行し 結果を JSON に保存する."""
    config = PathConfig()

    # ── コーパスの読み込み ──
    print("loading data...", flush=True)
    corpus_entries: list[dict] = hayalab.read_json(str(config.processed / "MBDiff.json"))

    # sibling_completeness 計算用の full AST（対象 ID のみ後で参照する）
    corpus_full_trees: dict[int, list[dict]] = {entry["id"]: entry["diff"]["base_ast"]["tree"] for entry in corpus_entries}
    # str_R 判定用のソースコード
    corpus_source_codes: dict[int, str] = {entry["id"]: entry["diff"]["base_ast"]["code"] for entry in corpus_entries}

    # ── Stage 1 統合 cutouts (新スキーマ) の読み込み ──
    cutouts_path = config.outputs / "scam" / "approach" / "01_cutouts.json"
    if not cutouts_path.exists():
        raise FileNotFoundError(f"Stage 1 cutouts が見つかりません: {cutouts_path} (先に 01_cutout.py を実行)")
    cutouts_entries: list[dict] = hayalab.read_json(str(cutouts_path))
    cutouts_by_id: dict[int, dict] = {e["id"]: e["cutouts"] for e in cutouts_entries}

    all_program_ids = sorted(cutouts_by_id.keys())
    total = len(all_program_ids)
    print(f"processing {total} entries in parallel...", flush=True)

    # ── 並列実行 ──
    # 各 ID の処理は独立しているため ProcessPoolExecutor で並列化する
    # args タプルをジェネレータで生成することで 大量の全データを一度にメモリ展開せずに submit できる
    def _iter_worker_args():
        for pid in all_program_ids:
            yield (pid, cutouts_by_id[pid], corpus_full_trees.get(pid, []), corpus_source_codes.get(pid, ""))

    results_map: dict[int, tuple[dict, dict]] = {}
    with ProcessPoolExecutor() as executor:
        futures = {executor.submit(_process_single_id, args): args[0] for args in _iter_worker_args()}
        with tqdm(total=total, unit="id") as pbar:
            for future in as_completed(futures):
                pid = futures[future]
                results_map[pid] = future.result()
                pbar.update(1)

    # ── ID 順に結果を収集 ──
    output_records: list[dict] = []
    instruction_records: list[dict] = []
    for pid in all_program_ids:
        output_record, instruction_entry = results_map[pid]
        output_records.append(output_record)
        instruction_records.append(instruction_entry)

    # ── 結果の保存 ──
    # 全データ版slow
    output_path = config.outputs / "pattern" / "granularity_decided_all.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    hayalab.write_json(str(output_path), output_records)
    print(f"wrote {len(output_records)} entries -> {output_path}")

    bone_path = config.outputs / "pattern" / "instruction_granularity_decided_all.json"
    hayalab.write_json(str(bone_path), instruction_records)
    print(f"wrote {len(instruction_records)} entries -> {bone_path}")

    # ターゲットデータ版 slow
    # output_path = config.outputs / "pattern" / "granularity_decided_targets.json"
    # output_path.parent.mkdir(parents=True, exist_ok=True)
    # hayalab.write_json(str(output_path), output_records)
    # print(f"wrote {len(output_records)} entries -> {output_path}")

    # bone_path = config.outputs / "pattern" / "instruction_granularity_decided_targets.json"
    # hayalab.write_json(str(bone_path), instruction_records)
    # print(f"wrote {len(instruction_records)} entries -> {bone_path}")


if __name__ == "__main__":
    main()
