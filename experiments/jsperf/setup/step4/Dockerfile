# Step 4: Playwright (headless Chromium) 実行環境
# Playwright 公式 Python イメージ (Chromium + 依存ライブラリ同梱) + uv
FROM mcr.microsoft.com/playwright/python:v1.61.0-noble

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /workspace

# uv sync はコンテナ内で初回に実行する (リポジトリを volume マウントするため)
CMD ["sleep", "infinity"]
