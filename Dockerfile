# =============================================================================
# Dockerfile — 保险理赔审计系统 企业级部署镜像
# 
# 采用多阶段构建：
#   1. build: 安装依赖
#   2. runtime: 最小化运行镜像
# =============================================================================

# ---- Stage 1: Build ----
FROM python:3.11-slim AS build

WORKDIR /build

# 安装系统依赖（编译一些Python包需要）
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libc6-dev \
    && rm -rf /var/lib/apt/lists/*

# 复制项目文件
COPY pyproject.toml .
COPY src/ ./src/

# 安装依赖到指定目录
RUN pip install --no-cache-dir --prefix=/install . && \
    pip install --no-cache-dir --prefix=/install .[prod]

# ---- Stage 2: Runtime ----
FROM python:3.11-slim AS runtime

WORKDIR /app

# 运行时元数据
LABEL maintainer="Senior Developer Team"
LABEL description="保险理赔数据自动化审计系统 Enterprise Edition"
LABEL version="2.0.0"

# 安装运行时系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# 从 build 阶段复制安装好的依赖
COPY --from=build /install /usr/local

# 复制应用代码
COPY src/ ./src/
COPY pyproject.toml .
COPY .env.example ./.env

# 创建必要目录
RUN mkdir -p logs reports data

# 非root用户运行（安全最佳实践）
RUN useradd -m -s /bin/bash auditor && \
    chown -R auditor:auditor /app
USER auditor

# 健康检查
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import insurance_audit; print('OK')" || exit 1

# 容器默认入口
ENTRYPOINT ["python", "-m", "insurance_audit.main"]
CMD []
