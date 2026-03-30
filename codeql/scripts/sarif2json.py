import argparse
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import hayalab
from hayalab.config import PathConfig

# ロギングの設定
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def process_single_detection(sarif, target_path: Path) -> dict:
    """単一のSARIFファイルからコードを抽出

    Args:
        sarif (hayalab.Sarif): SARIFの検出結果オブジェクト
        target_path (Path): 対象プロジェクトのパス

    Returns:
        dict: コードスニペットを含む検出結果の辞書形式
    """
    sarif.code_snippet = hayalab.extract_code_sarif(sarif, target_path)
    return asdict(sarif)


def analyze_sarif(sarif_path: Path, target_path: Path) -> dict:
    """SARIFファイルを解析し，コードスニペットを抽出したうえでJSON形式で返す

    Args:
        sarif_path (Path): SARIFファイルのパス
        target_path (Path): 対象プロジェクトのパス

    Returns:
        dict: 抽出されたコードスニペットを含む検出結果
    """

    logger.info(f"Starting extraction from: {sarif_path}")

    try:
        # 1. SARIFファイルのパース
        sarifs = hayalab.parse_sarif(sarif_path)

        # 2. 各検出結果を並列処理してコードを抽出・整形
        with ThreadPoolExecutor() as executor:
            results = list(executor.map(lambda s: process_single_detection(s, target_path), sarifs))

        # 3. メタデータの作成（mb-scanner の出力構造を参考にメタデータを含める）
        output_data = {
            "metadata": {
                "sarif_path": str(sarif_path.absolute()),
                "repository_path": str(target_path.absolute()),
                "total_results": len(results),
                "extraction_date": datetime.now().isoformat(),
            },
            "results": results,
        }

        return output_data

    except Exception as e:
        logger.error(f"Extraction failed: {e}")
        raise


def resolve_jobs(args: argparse.Namespace, parser: argparse.ArgumentParser, config: hayalab.PathConfig) -> list[tuple[Path, Path, Path]]:
    """実行対象ジョブを解決する

    Args:
        args (argparse.Namespace): コマンドライン引数
        parser (argparse.ArgumentParser): 引数パーサー（エラー出力のため）
        config (hayalab.PathConfig): デフォルトパスを含む設定オブジェクト

    Returns:
        list[tuple[Path, Path, Path]]: (sarif_file, target_dir, output_file) のジョブ一覧
    """
    provided_flags = [
        args.sarif_file is not None,
        args.output_file is not None,
        args.target_dir is not None,
    ]
    provided_count = sum(provided_flags)

    if provided_count not in (0, 3):
        parser.error("Specify either all of -f/--sarif-file, -o/--output-file, -t/--target-dir, or none of them to use defaults.")

    jobs = []
    # 全ての引数が存在する場合はそのファイルのみを対象とする
    if provided_count == 3:
        sarif_file = Path(args.sarif_file)
        output_file = Path(args.output_file)
        target_dir = Path(args.target_dir)

        if not sarif_file.exists() or not sarif_file.is_file():
            parser.error(f"SARIF file not found: {sarif_file}")
        if not target_dir.exists() or not target_dir.is_dir():
            parser.error(f"Target directory not found: {target_dir}")

        jobs.append((sarif_file, target_dir, output_file))
        return jobs

    # デフォルト設定（リポジトリに対する結果の解析）
    if provided_count == 0:
        sarif_root = config.outputs / "github" / "sarif"
        output_root = config.outputs / "github" / "code"
        targets_root = config.root / "targets" / "github" / "repositories"
        if not sarif_root.exists() or not sarif_root.is_dir():
            parser.error(f"SARIF root not found: {sarif_root}")
        if not targets_root.exists() or not targets_root.is_dir():
            parser.error(f"Target repositories root not found: {targets_root}")

        sarif_files = sorted(sarif_root.rglob("*.sarif"))
        for sarif_file in sarif_files:
            project_name = sarif_file.stem
            query_id = sarif_file.parent.name
            target_dir = targets_root / project_name
            output_file = output_root / query_id / f"{project_name}_code.json"
            jobs.append((sarif_file, target_dir, output_file))

    return jobs


if __name__ == "__main__":
    config = PathConfig()

    # コマンドライン引数の受付
    parser = argparse.ArgumentParser(description=("Analyze all {project}.sarif files under the specified path and write {project}_code.json files."))
    parser.add_argument(
        "-f",
        "--sarif-file",
        default=None,
        help="Single SARIF file path",
    )
    parser.add_argument(
        "-o",
        "--output-file",
        default=None,
        help="Single JSON output file path",
    )
    parser.add_argument(
        "-t",
        "--target-dir",
        default=None,
        help="Single target project directory",
    )
    args = parser.parse_args()

    # 入力・出力・対象プロジェクトを全て指定するか、全てデフォルトを使用するかのどちらか
    jobs = resolve_jobs(args, parser, config)
    if not jobs:
        logger.info("No .sarif files found under default SARIF root")
        raise SystemExit(0)

    # SARIFファイルを逐次処理してコード抽出 → JSON出力
    failed = []
    total = len(jobs)
    for idx, (sarif_file, target_dir, output_file) in enumerate(jobs, start=1):
        logger.info(f"[{idx}/{total}] Processing: {sarif_file}")
        if not target_dir.exists() or not target_dir.is_dir():
            logger.error(f"Failed to process {sarif_file}: target_not_found")
            failed.append((str(sarif_file), "target_not_found"))
            continue

        try:
            analyzed = analyze_sarif(sarif_file, target_dir)
            hayalab.write_json(output_file, analyzed)
            logger.info(f"Wrote: {output_file}")
        except Exception as e:
            logger.error(f"Failed to process {sarif_file}: {e}")
            failed.append((str(sarif_file), str(e)))

    if failed:
        logger.error("Completed with failures:")
        for sarif_file, reason in failed:
            logger.error(f"- {sarif_file}: {reason}")
        raise SystemExit(1)

    logger.info("Done. All SARIF files were converted successfully.")
