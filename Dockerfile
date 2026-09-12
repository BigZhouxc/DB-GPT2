# 智能问数 Agent 服务镜像
# 用 py3.10-slim（aiohttp 有现成 wheel，无需编译）
FROM docker.m.daocloud.io/library/python:3.10-slim

# 国内 PyPI 镜像
ENV PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
ENV PIP_PROGRESS_BAR=off
# 清除宿主机代理（容器内访问不到 127.0.0.1 代理）
ENV HTTP_PROXY=
ENV HTTPS_PROXY=
ENV http_proxy=
ENV https_proxy=
ENV NO_PROXY=*
ENV no_proxy=*

WORKDIR /app

# --- 第一层：安装运行时依赖 ---
COPY requirements.txt .
RUN unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy && \
    pip install --no-cache-dir -r requirements.txt

# --- 第二层：从本地源码安装 dbgpt-core + dbgpt-ext（--no-deps 避免依赖解析风暴）---
COPY dbgpt-core-pkg/ /tmp/dbgpt-core-pkg/
COPY dbgpt-ext-pkg/ /tmp/dbgpt-ext-pkg/
RUN unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy && \
    pip install --no-cache-dir --no-deps /tmp/dbgpt-core-pkg && \
    pip install --no-cache-dir --no-deps /tmp/dbgpt-ext-pkg && \
    rm -rf /tmp/dbgpt-core-pkg /tmp/dbgpt-ext-pkg

# --- 第三层：安装 dbgpt-client（--no-deps）---
RUN unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy && \
    pip install --no-cache-dir --no-deps dbgpt-client==0.8.2

# --- 第四层：业务代码 ---
COPY core/ ./core/
COPY modules/ ./modules/
COPY app.py .
COPY static/ ./static/

EXPOSE 8080

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
