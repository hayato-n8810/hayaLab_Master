import argparse
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


def parse_args() -> argparse.Namespace:
    """引数解決

    Returns:
        argparse.Namespace: コマンドライン引数
    """
    parser = argparse.ArgumentParser(
        description=(
            "Run CodeQL analysis for id_1.ql to id_6.ql against all databases under /works/targets/github/codeql-dbs and output SARIF files into ../outputs/github/sarif/id_{i}/{db_name}.sarif."
        )
    )
    # 並列処理のジョブ数を指定するオプション
    parser.add_argument(
        "-j",
        "--jobs",
        type=int,
        default=1,
        help="Number of projects to analyze in parallel for each query (default: 1)",
    )
    return parser.parse_args()


def run_analyze(db_dir: Path, query_path: Path, output_path: Path) -> bool:
    """codeQLのクエリを発行する

    Args:
            db_dir (Path): 対象プロジェクトのcodeQLDBのパス
            query_path (Path): 実行するクエリのパス
            output_path (Path): 出力するSARIFファイルのパス

    Returns:
            bool: 分析結果
    """
    cmd = [
        "codeql",
        "database",
        "analyze",
        str(db_dir),
        "--format=sarifv2.1.0",
        f"--output={output_path}",
        "--rerun",
        str(query_path),
    ]
    try:
        subprocess.run(cmd, check=True)
        return True
    except subprocess.CalledProcessError:
        return False


if __name__ == "__main__":
    args = parse_args()

    if shutil.which("codeql") is None:
        print("Error: 'codeql' command not found in PATH.", file=sys.stderr)
        sys.exit(1)

    dbs_root = Path("/works/targets/github/codeql-dbs")
    if not dbs_root.exists() or not dbs_root.is_dir():
        print(f"Error: DB root does not exist: {dbs_root}", file=sys.stderr)
        sys.exit(1)

    if args.jobs < 1:
        print("Error: --jobs must be >= 1", file=sys.stderr)
        sys.exit(1)

    script_dir = Path(__file__).resolve().parent
    query_dir = script_dir.parent / "QL" / "query"
    output_root = script_dir.parent / "outputs" / "github" / "sarif"

    db_dirs = sorted(p for p in dbs_root.iterdir() if p.is_dir())
    if not db_dirs:
        print(f"No DB folders found under: {dbs_root}")
        sys.exit(0)

    failed = []
    total = len(db_dirs) * 6
    current = 0

    for i in range(1, 7):
        query_path = query_dir / f"id_{i}.ql"
        output_dir = output_root / f"id_{i}"
        output_dir.mkdir(parents=True, exist_ok=True)

        if not query_path.is_file():
            print(f"Error: Query file not found: {query_path}", file=sys.stderr)
            sys.exit(1)

        with ThreadPoolExecutor(max_workers=args.jobs) as executor:
            future_to_meta = {}
            for db_dir in db_dirs:
                db_name = db_dir.name
                output_path = output_dir / f"{db_name}.sarif"
                future = executor.submit(run_analyze, db_dir, query_path, output_path)
                future_to_meta[future] = (db_name, i)

            for future in as_completed(future_to_meta):
                current += 1
                db_name, query_id = future_to_meta[future]
                print(f"[{current}/{total}] codeql database analyze ({db_name}, id_{query_id})")
                if not future.result():
                    failed.append((db_name, query_id))
                    print(f"Failed: {db_name} (id_{query_id})", file=sys.stderr)

    if failed:
        print("\nCompleted with failures:", file=sys.stderr)
        for db_name, query_id in failed:
            print(f"- {db_name} (id_{query_id})", file=sys.stderr)
        sys.exit(1)

    print("\nDone. Outputs: ../outputs/github/sarif/id_{i}/{DB名}.sarif")
    sys.exit(0)
