# CausalChat Docker 镜像构建文件

FROM python:3.11-slim

WORKDIR /app

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

# 再安装所有依赖（包括新增的）
COPY requirements.txt .
# 使用官方PyPI源避免哈希验证问题（torch等大包从官方源下载更可靠）
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

EXPOSE 5001

CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:5001 --workers ${WEB_WORKERS:-1} --threads ${WEB_THREADS:-12} --timeout ${WEB_TIMEOUT:-120} Causalchat:app"]

