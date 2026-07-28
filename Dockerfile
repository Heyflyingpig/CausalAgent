# CausalAgent Docker 镜像构建文件

FROM python:3.11-slim AS python-deps

WORKDIR /app

# 容忍部署网络的短时抖动
ENV PIP_DEFAULT_TIMEOUT=300 \
    PIP_RETRIES=5

RUN sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get -o Acquire::Retries=5 update && apt-get -o Acquire::Retries=5 install -y \
    gcc \
    g++ \
    default-libmysqlclient-dev \
    pkg-config \
    libglib2.0-0 \
    libgl1 \
    && rm -rf /var/lib/apt/lists/*

# 先安装基础依赖（很少变化）
COPY requirements-base.txt .
RUN pip install --no-cache-dir -r requirements-base.txt

# 先安装 CPU 版 PyTorch，避免从 PyPI 拉取包含 CUDA 组件的超大 wheel
RUN pip install --no-cache-dir \
    --index-url https://download.pytorch.org/whl/cpu \
    torch==2.7.1+cpu

# 再安装所有依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt


FROM python-deps AS test

COPY requirements-test.txt .
RUN pip install --no-cache-dir -r requirements-test.txt

CMD ["python", "-m", "pytest", "-p", "no:cacheprovider", "tests/unit"]


FROM node:24-alpine AS admin-builder

WORKDIR /frontend

COPY admin-frontend/package.json admin-frontend/package-lock.json ./
RUN npm ci

COPY admin-frontend/ ./
RUN npm run build


FROM python-deps AS runtime

COPY . .
COPY --from=admin-builder /frontend/dist /opt/causalagent-admin

ENV ADMIN_FRONTEND_DIST_DIR=/opt/causalagent-admin

EXPOSE 5001

CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:5001 --workers ${WEB_WORKERS:-1} --threads ${WEB_THREADS:-12} --timeout ${WEB_TIMEOUT:-120} CausalAgent:app"]

