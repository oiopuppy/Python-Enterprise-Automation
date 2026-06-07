# 保险理赔数据自动化审计系统

**China Life Insurance Claim Audit Enterprise Edition v2.0**

> 央企级保险理赔数据自动化审计平台 — Enterprise-grade insurance claim data audit automation platform

---

## 🏗️ 架构概览

```
src/insurance_audit/
├── __init__.py          # 包入口 & 版本信息
├── main.py              # 系统主入口（CLI）
├── core/                # 核心业务逻辑层
│   ├── calculator.py    # 赔付金额计算引擎（Decimal精确计算）
│   ├── validator.py     # 数据质量校验层
│   └── engine.py        # 可编程审计引擎
├── data/                # 数据访问层
│   ├── reader.py        # 数据读取（Excel等）
│   ├── writer.py        # 数据写入（报告导出）
│   └── generator.py     # 模拟数据生成器
├── models/              # 数据模型层
│   ├── claim.py         # 理赔记录模型（Pydantic v2）
│   └── audit.py         # 审计结果模型
├── audit/               # 审计引擎层
│   ├── reconciler.py    # 自动对账引擎
│   └── reporter.py      # 审计报告生成器
└── utils/               # 工具层
    ├── config.py        # 配置管理（多层级：默认值→.env→环境变量）
    ├── logger.py        # 日志系统（控制台+文件轮转+审计追溯）
    └── exceptions.py    # 企业级异常体系（业务/数据/系统/安全）
```

---

## ✨ 企业级特性

| 特性 | 说明 |
|------|------|
| **Decimal精度** | 所有金额计算使用 `decimal.Decimal`，ROUND_HALF_UP 四舍五入 |
| **Pydantic校验** | 数据模型自动校验类型、范围、格式 |
| **配置管理** | 支持 `.env` 文件 + 环境变量 + 代码默认值三级覆盖 |
| **日志轮转** | 控制台彩色日志 + 文件日志（按大小轮转，保留30天） |
| **审计追溯** | 独立的审计日志，记录所有操作（生产环境合规要求） |
| **异常体系** | 四类异常：业务(BIZ)、数据(DAT)、系统(SYS)、安全(SEC) |
| **CI/CD** | GitHub Actions 自动化：lint → test(3.11/3.12) → security → build |
| **Docker部署** | 多阶段构建，非root用户运行，健康检查 |
| **测试覆盖** | 单元测试 + 集成测试，支持覆盖率报告 |
| **代码质量** | Ruff风格检查 + MyPy类型检查 + Pre-commit hooks |

---

## 🚀 快速开始

### 安装

```bash
# 1. 克隆仓库
git clone <your-repo-url>
cd Python-Enterprise-Automation

# 2. 安装依赖
pip install -e .

# 3. 复制环境变量配置（可选）
cp .env.example .env
```

### 运行

```bash
# 生成模拟数据
python -m insurance_audit.data.generator

# 执行审计
python -m insurance_audit.main
```

---

## 🧪 测试

```bash
# 运行所有测试
pytest -v

# 仅运行单元测试
pytest -v -m "unit"

# 仅运行集成测试
pytest -v -m "integration"

# 带覆盖率报告
pytest --cov=insurance_audit --cov-report=term-missing
```

---

## 🐳 Docker 部署

```bash
# 构建镜像
docker build -t insurance-audit:2.0 .

# 运行（默认使用容器内的示例数据）
docker run --rm insurance-audit:2.0

# 运行（挂载本地数据目录）
docker run --rm \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/reports:/app/reports \
  -v $(pwd)/logs:/app/logs \
  insurance-audit:2.0
```

---

## 📋 配置说明

通过 `.env` 文件配置（参见 `.env.example`）：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `APP_ENV` | `development` | 运行环境：development/production |
| `APP_LOG_LEVEL` | `INFO` | 日志级别 |
| `INSURANCE_DEFAULT_DEDUCTIBLE` | `500` | 默认免赔额（元） |
| `INSURANCE_DEFAULT_RATIO` | `0.80` | 默认赔付比例 |
| `INSURANCE_ANNUAL_LIMIT` | `500000` | 年度赔付上限（元） |
| `DATA_INPUT_FILE` | `sample_claim_data.xlsx` | 输入数据文件 |
| `DATA_OUTPUT_FILE` | `final_settlement_report.xlsx` | 输出报告文件名 |

---

## 🔒 安全说明

- 非root用户运行（Docker部署默认 `auditor` 用户）
- 敏感配置通过环境变量而非代码硬编码
- 生产环境建议设置 `APP_DEBUG=false` 和 `ENABLE_DATA_ENCRYPTION=true`
- CI pipeline 包含 Bandit 安全扫描

---

## 📄 许可证

MIT License — 详见 [LICENSE](LICENSE) 文件

---

*Enterprise Edition v2.0.0 — Built by Senior Developer Team*
