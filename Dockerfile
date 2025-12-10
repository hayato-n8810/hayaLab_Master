FROM python:3.14-slim
WORKDIR /opt

RUN apt-get update && apt-get install -y \
    wget \
    unzip \
    curl \
    openjdk-21-jre \
    && wget "https://github.com/GumTreeDiff/gumtree/releases/download/v4.0.0-beta2/gumtree-4.0.0-beta2.zip" \
    && unzip "gumtree-4.0.0-beta2.zip" \
    && mv "gumtree-4.0.0-beta2" "gumtree" \
    && rm gumtree-4.0.0-beta2.zip \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

ENV PATH=$PATH:/opt/gumtree/bin

# Node と pnpm のインストール
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y nodejs \
    && npm install -g pnpm@10.24.0

WORKDIR /works
COPY package.json pnpm-lock.yaml .npmrc ./
RUN pnpm install --frozen-lockfile

# hayalabパッケージをインストール
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install -e .

EXPOSE 4567