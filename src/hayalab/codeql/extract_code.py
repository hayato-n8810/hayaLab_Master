from pathlib import Path

from hayalab.classes.codeql import Sarif


def extract_code_sarif(sarif: Sarif, target_path: Path) -> str:
    """Sarifの一つの検出結果からコードブロックを抽出し整形して返す

    Args:
        sarif (Sarif): sarifの一つの検出結果
        target_path (Path): 検出対象プロジェクトのルートディレクトリへのパス

    Returns:
        str: 抽出されたコードブロック
    """
    # 1. ビルド成果物ディレクトリを除外
    excluded_patterns = [
        "build/",
        "dist/",
        "out/",
        ".next/",
        "target/",
        "public/build/",
        "static/build/",
    ]
    if any(sarif.file_path.startswith(pattern) for pattern in excluded_patterns):
        return "[Build artifact - skipped]"

    file_path = target_path / sarif.file_path.lstrip("/")

    # 2. ファイルの存在確認
    if not file_path.exists():
        return "[File not found]"

    try:
        # 3. UTF-8でデコードできない場合はエラーを無視して置換してデコード
        with file_path.open(encoding="utf-8", errors="replace") as f:
            lines = f.readlines()

        # 4. 行番号の変換 (1-indexed -> 0-indexed)
        start_idx = sarif.start_line - 1
        end_idx = sarif.end_line  # end_lineは含むためスライスではそのまま

        # 5. 範囲チェック
        if start_idx < 0 or end_idx > len(lines):
            return "[Line out of range]"

        # 6. 該当行を抽出して結合
        snippet_lines = lines[start_idx:end_idx]

        # MB-Scanner流の結合処理
        if len(snippet_lines) > 1:
            snippet = "\n".join(line.rstrip("\n") for line in snippet_lines)
        else:
            snippet = snippet_lines[0].rstrip("\n") if snippet_lines else ""

        # 7. 整形処理を適用
        # エラーによりコードが出力されない場合があるためコメントアウト
        # snippet = code_clean(snippet)

        return snippet

    except Exception as e:
        return f"[Error: {e}]"
