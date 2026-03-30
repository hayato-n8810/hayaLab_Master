# codeqlの実行結果を解析する

from dataclasses import dataclass
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict


# ------ SARIF形式 -------
# SARIF 2.1.0 準拠の Pydantic モデル (mb-scannerより)
class SarifTextMessage(BaseModel):
    text: str


class SarifArtifactLocation(BaseModel):
    uri: str
    uriBaseId: Optional[str] = None


class SarifRegion(BaseModel):
    startLine: int
    endLine: Optional[int] = None
    startColumn: Optional[int] = None
    endColumn: Optional[int] = None


class SarifPhysicalLocation(BaseModel):
    artifactLocation: SarifArtifactLocation
    region: Optional[SarifRegion] = None


class SarifLocation(BaseModel):
    physicalLocation: SarifPhysicalLocation


class SarifResult(BaseModel):
    model_config = ConfigDict(extra="allow")
    ruleId: str
    message: SarifTextMessage
    locations: Optional[list[SarifLocation]] = None
    level: Optional[Literal["none", "note", "warning", "error"]] = None


class SarifRun(BaseModel):
    model_config = ConfigDict(extra="allow")
    results: list[SarifResult]


class SarifReport(BaseModel):
    model_config = ConfigDict(extra="allow")
    version: str
    runs: list[SarifRun]


# 解析結果を保持する内部データクラス
@dataclass
class Sarif:
    id: int
    file_path: str
    start_line: int
    end_line: int
    start_column: Optional[int]
    end_column: Optional[int]
    message: str
    severity: str
    code_snippet: str = ""
