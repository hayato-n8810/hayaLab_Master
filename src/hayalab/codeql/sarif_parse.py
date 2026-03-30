from pathlib import Path
from urllib.parse import unquote

from hayalab.classes.codeql import Sarif, SarifReport


def parse_sarif(sarif_path: Path) -> list[Sarif]:
    """SARIFファイルをパースして、検出結果のリストを返す

    Args:
        sarif_path (Path): SARIFファイルへのパス

    Raises:
        FileNotFoundError: SARIFファイルが見つからない場合

    Returns:
        list[Sarif]: 検出結果のリスト
    """
    if not sarif_path.exists():
        raise FileNotFoundError(f"SARIF file not found: {sarif_path}")

    with sarif_path.open("rb") as f:
        sarif_data = SarifReport.model_validate_json(f.read())

    results = []
    if not sarif_data.runs:
        return results

    for idx, result in enumerate(sarif_data.runs[0].results):
        if not result.locations:
            continue

        phys = result.locations[0].physicalLocation
        region = phys.region
        if not region:
            continue

        results.append(
            Sarif(
                id=idx,
                file_path=unquote(phys.artifactLocation.uri),
                start_line=region.startLine,
                end_line=region.endLine or region.startLine,
                start_column=region.startColumn,
                end_column=region.endColumn,
                message=result.message.text,
                severity=result.level or "warning",
            )
        )
    return results
