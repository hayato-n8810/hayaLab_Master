# ==============================================================================
# Base Image (Python 3.14 ベース)
# ==============================================================================
FROM python:3.14-slim

# ==============================================================================
# Arguments & Environment Variables
# ==============================================================================
ARG UID=100
ARG GID=100
ARG USERNAME=developer
ARG CODEQL_VERSION=latest

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/codeql:${PATH}"

# ==============================================================================
# System Setup & Node.js & pnpm Install
# ==============================================================================
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates wget zip unzip git build-essential \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y nodejs \
    && npm install -g pnpm@10.24.0 \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# ==============================================================================
# CodeQL CLI Setup
# ==============================================================================
RUN if [ "$CODEQL_VERSION" = "latest" ]; then \
        CODEQL_URL="https://github.com/github/codeql-cli-binaries/releases/latest/download/codeql-linux64.zip"; \
    else \
        CODEQL_URL="https://github.com/github/codeql-cli-binaries/releases/download/v${CODEQL_VERSION}/codeql-linux64.zip"; \
    fi && \
    wget -q "$CODEQL_URL" -O /tmp/codeql.zip && \
    unzip -q /tmp/codeql.zip -d /opt && \
    rm /tmp/codeql.zip && \
    chmod -R 755 /opt/codeql

# ==============================================================================
# hayalab Package Setup
# ==============================================================================
WORKDIR /tmp/hayalab
COPY hayalab/package.json hayalab/pnpm-lock.yaml hayalab/.npmrc ./
RUN pnpm install --frozen-lockfile
COPY hayalab/pyproject.toml hayalab/README.md ./
COPY hayalab/src/ ./src/
RUN pip install -e .

# ==============================================================================
# User Setup
# ==============================================================================
RUN groupadd -g ${GID} ${USERNAME} || true && \
    useradd --uid ${UID} --gid ${GID} --create-home --shell /bin/bash ${USERNAME}


WORKDIR /works

# 全ファイルの所有権をユーザーに変更
RUN mkdir -p /works && chown -R ${USERNAME}:${GID} /home/${USERNAME} /works

USER ${USERNAME}
CMD ["/bin/bash"]