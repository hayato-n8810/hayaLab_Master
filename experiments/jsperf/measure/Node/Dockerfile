# Node 計測用イメージ。 Node と uv 管理 Python を同居させる。
# npm 版ハーネスの require 依存はビルド時に /opt/npm へインストールし (バインドマウント外)、
# NODE_PATH でそこを参照する。 実行時は measure/Node が ro バインドされてもこの node_modules
# はイメージ側にそのまま残る。
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

# npm 版ハーネスの require 依存をビルド時にインストールする (完全な package.json 前提)。
COPY package.json /opt/npm/package.json
RUN cd /opt/npm && npm install
ENV NODE_PATH=/opt/npm/node_modules
