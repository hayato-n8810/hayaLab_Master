import shutil
import subprocess
import sys
from pathlib import Path

REPOS_ROOT = Path("/works/targets/github/repositories")
DBS_ROOT = Path("/works/targets/github/codeql-dbs")


if __name__ == "__main__":
    if shutil.which("codeql") is None:
        print("Error: 'codeql' command not found in PATH.", file=sys.stderr)
        sys.exit(127)

    if not REPOS_ROOT.exists() or not REPOS_ROOT.is_dir():
        print(f"Error: repositories root not found: {REPOS_ROOT}", file=sys.stderr)
        sys.exit(1)

    DBS_ROOT.mkdir(parents=True, exist_ok=True)

    repo_dirs = sorted(p for p in REPOS_ROOT.iterdir() if p.is_dir())
    if not repo_dirs:
        print(f"No repository folders found under: {REPOS_ROOT}")
        sys.exit(0)

    failed = []
    total = len(repo_dirs)

    for index, repo_dir in enumerate(repo_dirs, start=1):
        # 全てのリポジトリについてDBを構築する
        repo_name = repo_dir.name
        output_db = DBS_ROOT / repo_name

        cmd = [
            "codeql",
            "database",
            "create",
            str(output_db),
            f"-s={repo_dir}",
            "--no-run-unnecessary-builds",
            "--language=javascript-typescript",
        ]

        print(f"[{index}/{total}] Creating DB for: {repo_name}")
        try:
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL)
        except subprocess.CalledProcessError:
            failed.append(repo_name)
            print(f"Failed: {repo_name}", file=sys.stderr)

    if failed:
        print("\nCompleted with failures:", file=sys.stderr)
        for name in failed:
            print(f"- {name}", file=sys.stderr)
        sys.exit(1)

    print("\nDone. All repository databases were created successfully.")
    sys.exit(0)
