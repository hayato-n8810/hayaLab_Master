# Playwright 等価性検証環境 (experiments/jsperf/measure/Playwright/Dockerfile を土台とする)
# Playwright 公式 Python イメージ (Chromium + 依存ライブラリ同梱) + uv に、
# 決定化・計測コード生成用の Node と Babel、変数名収集用の GumTree (Java) を追加する。
# Babel はビルド時に /opt/npm へインストールし (バインドマウント外)、NODE_PATH でそこを参照する。
FROM mcr.microsoft.com/playwright/python:v1.61.0-noble

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Node.js v24 系（LTS） / OpenJDK 21 / GumTree 4.0.0-beta2
WORKDIR /opt
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl gnupg ca-certificates unzip wget && \
    curl -fsSL https://deb.nodesource.com/setup_24.x | bash - && \
    apt-get install -y --no-install-recommends nodejs openjdk-21-jre-headless && \
    wget "https://github.com/GumTreeDiff/gumtree/releases/download/v4.0.0-beta2/gumtree-4.0.0-beta2.zip" && \
    unzip "gumtree-4.0.0-beta2.zip" && \
    mv "gumtree-4.0.0-beta2" "gumtree" && \
    rm gumtree-4.0.0-beta2.zip && \
    apt-get clean && rm -rf /var/lib/apt/lists/*
ENV PATH=$PATH:/opt/gumtree/bin

COPY package.json /opt/npm/package.json
RUN cd /opt/npm && npm install --no-audit --no-fund
ENV NODE_PATH=/opt/npm/node_modules

WORKDIR /workspace

# uv sync はコンテナ内で初回に実行する (リポジトリを volume マウントするため)
CMD ["sleep", "infinity"]
