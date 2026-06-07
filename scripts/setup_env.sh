#!/bin/bash
# =============================================================================
# 环境初始化脚本 — 央企部署环境准备
# =============================================================================
# 使用方法:
#   chmod +x scripts/setup_env.sh
#   ./scripts/setup_env.sh
# =============================================================================

set -euo pipefail

echo "=========================================="
echo " 保险理赔审计系统 — 环境初始化"
echo " Enterprise Edition v2.0.0"
echo "=========================================="

# --- 1. 检查 Python 版本 ---
echo ""
echo "[1/5] 检查 Python 环境..."
PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
REQUIRED_VERSION="3.11"

if [ "$(printf '%s\n' "$REQUIRED_VERSION" "$PYTHON_VERSION" | sort -V | head -n1)" != "$REQUIRED_VERSION" ]; then
    echo "❌ Python $REQUIRED_VERSION+ 必需，当前版本: $PYTHON_VERSION"
    exit 1
fi
echo "✅ Python $PYTHON_VERSION"

# --- 2. 创建虚拟环境 ---
echo ""
echo "[2/5] 创建 Python 虚拟环境..."
if [ -d ".venv" ]; then
    echo "   虚拟环境已存在，跳过创建"
else
    python3 -m venv .venv
    echo "✅ 虚拟环境创建完成"
fi

# --- 3. 安装依赖 ---
echo ""
echo "[3/5] 安装项目依赖..."
source .venv/bin/activate
pip install --upgrade pip -q
pip install -e . -q
pip install -e ".[dev]" -q
echo "✅ 依赖安装完成"

# --- 4. 创建必要目录 ---
echo ""
echo "[4/5] 创建运行目录..."
mkdir -p logs reports data
echo "✅ 目录结构就绪"

# --- 5. 配置 .env ---
echo ""
echo "[5/5] 环境变量配置..."
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo "✅ 已从 .env.example 创建 .env"
    echo "⚠️  请根据实际环境修改 .env 中的配置"
else
    echo "✅ .env 文件已存在"
fi

echo ""
echo "=========================================="
echo " ✅ 环境初始化完成!"
echo "=========================================="
echo ""
echo "快速开始:"
echo "  source .venv/bin/activate"
echo "  insurance-audit                      # 运行审计"
echo "  insurance-audit --generate-mock      # 生成模拟数据后运行"
echo ""
echo "运行测试:"
echo "  pytest -v"
echo "  pytest --cov=insurance_audit         # 带覆盖率"
echo ""
