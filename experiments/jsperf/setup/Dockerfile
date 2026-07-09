# Setup 用イメージ。 Node と uv 管理 Python を同居させ、
# npm ワークスペースを /workspace/experiments/jsperf/setup/step3 に固定する。
# Node.js v24 系（LTS）
# Python v3.14（LTS） 

FROM python:3.14-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends curl gnupg ca-certificates && \
    curl -fsSL https://deb.nodesource.com/setup_24.x | bash - && \
    apt-get install -y --no-install-recommends nodejs && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /workspace
ENV PYTHONUNBUFFERED=1
ENV UV_LINK_MODE=copy
ENV NODE_PATH=/workspace/experiments/jsperf/setup/step3/node_modules
