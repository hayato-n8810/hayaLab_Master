"""パターン抽出パイプライン用データモデル。

切り出し（Cutout）、抽象化済みパターン（Pattern）、同値類（EquivalenceClass）、
スコア（SizeScore）、選択結果（SelectionResult）、抽象化観測量（AbstractionObservation）、
識別子 slot（IdentifierSlot）を定義する。

すべて pydantic.BaseModel で JSON シリアライズ可能。`set` 型のフィールドは
JSON 出力時には呼び出し側で sorted(list(...)) として書き出すこと（再現性のため）。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Cutout(BaseModel):
    """単一の切り出し結果。

    Attributes:
        mb_id: 由来 MB の id（MBDiff の id フィールドそのもの）。
        depth: 切り出し depth (1, 2, 3, 4)。
        root_index: 元 AST における切り出し根ノードの配列インデックス。
        node_indices: 切り出し部分木に含まれる AST ノードの配列インデックスを昇順に並べたリスト。
        diff_node_indices: 上記のうち差分ノード（GumTree が変更点として検出したノード）に
            該当するインデックスの集合。
    """

    mb_id: int
    depth: int
    root_index: int
    node_indices: list[int]
    diff_node_indices: set[int] = Field(default_factory=set)


class IdentifierSlot(BaseModel):
    """識別子の slot 情報。

    同一値（例: VAR_1）の複数出現を結びつけるため、Cutout 内で一意の通し番号を付与する。

    Attributes:
        slot_id: Cutout 内で一意の通し番号（出現順に 1, 2, ...）。
        prefix: "VAR" / "KEY" / "FUNCTION" / "CLASS"。
        original_value: 元値（例: "VAR_1"）。A0–A2 で完全一致比較に用いる。
    """

    slot_id: int
    prefix: str
    original_value: str


class Pattern(BaseModel):
    """検出可能なパターン表現。

    Attributes:
        mb_id: 由来 MB の id（複数 MB から生成された同一パターンは別オブジェクト）。
        depth: 切り出し depth。
        abst_level: 抽象化レベル (0..3)。
        ast_template: 抽象化適用後の AST テンプレート。各要素は
            {"name": str, "value": str, "parent_relative": list[int],
             "slot_id": int | None, "prefix": str | None, "original_value": str | None,
             "variadic": bool, "is_terminal": bool}。
            識別子ノードは slot_id を持ち、同一識別子の複数出現を結びつける。
        signature: パターン同一性判定用のハッシュ文字列（決定論的、ast_template から計算）。
            同じ AST テンプレートを持つパターンは同じ値を取る、内部キー。
    """

    mb_id: int
    depth: int
    abst_level: int
    ast_template: list[dict] = Field(default_factory=list)
    signature: str = ""


class ClassMember(BaseModel):
    """同値類のメンバ：パターン由来情報。

    同一 signature が複数 MB から生成される場合があるため、由来 MB id を保持して
    member ごとに区別する。同一 (mb_id, signature, depth) は重複排除する。

    Attributes:
        mb_id: パターンの元となった MB の id。
        signature: パターン同一性判定用ハッシュ。
        depth: 由来 depth。
    """

    mb_id: int
    signature: str
    depth: int


class EquivalenceClass(BaseModel):
    """同値類（データセットに対する検出結果が一致するパターン群）。

    abst_level 別に集約する現行実装では、メンバの abst_level は同一。
    代表パターンが必要な箇所は `members` の signature を辿って Pattern を引く。

    Attributes:
        class_id: 同値類の識別用ハッシュ文字列（決定論的に割り当て、内部キー）。
        members: クラスに含まれるメンバ情報のリスト
            （由来 MB id × signature × depth、(mb_id, signature, depth) の昇順）。
        detect_id: そのクラスに属するパターンが検出される MB id の集合（検出結果）。
    """

    class_id: str
    members: list[ClassMember]
    detect_id: set[int]


class SizeScore(BaseModel):
    """サイズスコア成分。

    Attributes:
        rho: Diff Density Ratio = |diff_nodes| / |all_nodes_in_cutout| ∈ [0, 1]。
        sigma: Normalized Node Count = |N(L)| / N_max ∈ [0, 1]。
        score: 統合スコア = w * rho + (1 - w) * sigma ∈ [0, 1]。
        weight_w: 統合重み w（参照のために保持）。
    """

    rho: float
    sigma: float
    score: float
    weight_w: float


class SelectionResult(BaseModel):
    """MB ごとの最適 (L*, A*) 選択結果。

    Attributes:
        mb_id: 対象 MB の id。
        optimal_depth: 選択された depth (1..4) または None。
        optimal_abst_level: 選択された抽象化レベル (0..3) または None。
        status: "selected" | "unrepresentable"。
        equivalence_class_id: 帰属する同値類 ID（status == "selected" のとき）。
    """

    mb_id: int
    optimal_depth: int | None
    optimal_abst_level: int | None
    status: str
    equivalence_class_id: str | None = None


class AbstractionObservation(BaseModel):
    """抽象化レベル別の集約観測量。

    Attributes:
        abst_level: 抽象化レベル (0..3)。
        n_classes: 同値類の総数。
        n_aggregated: 検出結果のサイズが 2 以上の同値類の数（複数 MB をカバーするパターン）。
        n_just_match: 検出結果のサイズが 1 の同値類の数（自分自身しかヒットしないパターン）。
        mb_in_aggregated: 集約済み同値類に属する MB の総数。
        max_class_size: 同値類内の最大検出結果サイズ。
        migration_to_next: A → A+1 で所属同値類が変わる MB 数（最終レベルは None）。
    """

    abst_level: int
    n_classes: int
    n_aggregated: int
    n_just_match: int
    mb_in_aggregated: int
    max_class_size: int
    migration_to_next: int | None = None
