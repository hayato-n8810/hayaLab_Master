from pathlib import Path

from pydantic import BaseModel, Field

# Hayalabモジュール内
HAYALAB = Path(__file__).parents[1]
UTILS = HAYALAB / "utils"


class PathConfig(BaseModel):
    """パス関連の設定"""

    root: Path = Field(default_factory=lambda: Path(__file__).parents[3])

    @property
    def repository(self) -> Path:
        """リポジトリディレクトリのパスを返す"""
        return self.root.parent / "repository"

    @property
    def experiments(self) -> Path:
        """実験コードディレクトリのパスを返す"""
        return self.root / "experiments"

    @property
    def data(self) -> Path:
        """データディレクトリのパスを返す"""
        return self.root / "data"

    @property
    def raw(self) -> Path:
        """生データディレクトリのパスを返す"""
        return self.data / "raw"

    @property
    def processed(self) -> Path:
        """処理済みデータディレクトリのパスを返す"""
        return self.data / "processed"

    @property
    def output(self) -> Path:
        """結果出力先ディレクトリのパスを返す"""
        return self.root / "outputs"

    @property
    def codeql(self) -> Path:
        """CodeQL関連ディレクトリのパスを返す"""
        return self.root / "codeql"
