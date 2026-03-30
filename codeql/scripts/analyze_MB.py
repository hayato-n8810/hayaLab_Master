import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    """引数解決

    Returns:
        argparse.Namespace: コマンドライン引数
    """
    parser = argparse.ArgumentParser(description=("Run CodeQL analysis for id_1.ql to id_6.ql against a given database and output SARIF files into ../outputs/microbenchmark/sarif/."))
    parser.add_argument(
        "db_path",
        nargs="?",
        default="/works/targets/microbenchmark/codeql-db",
        help="Path to CodeQL database (default: /works/targets/microbenchmark/codeql-db)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    if shutil.which("codeql") is None:
        print("Error: 'codeql' command not found in PATH.", file=sys.stderr)
        sys.exit(127)

    db_path = Path(args.db_path)
    if not db_path.exists():
        print(f"Error: DB path does not exist: {db_path}", file=sys.stderr)
        sys.exit(1)

    script_dir = Path(__file__).resolve().parent
    query_dir = script_dir.parent / "QL" / "query"
    output_dir = script_dir.parent / "outputs" / "microbenchmark" / "sarif"
    output_dir.mkdir(parents=True, exist_ok=True)

    for i in range(1, 7):
        query_path = query_dir / f"id_{i}.ql"
        output_path = output_dir / f"id_{i}.sarif"

        if not query_path.is_file():
            print(f"Error: Query file not found: {query_path}", file=sys.stderr)
            sys.exit(1)

        print(f"[{i}/6] codeql database analyze (id_{i})")
        cmd = [
            "codeql",
            "database",
            "analyze",
            str(db_path),
            "--format=sarifv2.1.0",
            f"--output={output_path}",
            "--rerun",
            str(query_path),
        ]
        subprocess.run(cmd, check=True)

    print("Done. Outputs: ../outputs/microbenchmark/sarif/")
