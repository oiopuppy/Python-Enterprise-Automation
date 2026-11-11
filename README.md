# 保险理赔数据自动化审计系统

> 读取理赔台账 Excel，按合同规则重算应赔金额，与原表「实际赔付金额」逐条对账，输出带差异明细与数据质量报告的审计工作簿。

[![CI](https://github.com/oiopuppy/Python-Enterprise-Automation/actions/workflows/ci.yml/badge.svg)](https://github.com/oiopuppy/Python-Enterprise-Automation/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.9%20%7C%203.12-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

这是一个个人项目，用来解决「理赔金额靠人工核对、差异说不清」的问题。没有 Web 界面、没有数据库，就是一个可以塞进流水线、也可以本地一条命令跑完的 CLI。

---

## 它能做什么

给定一份包含 6 列的 Excel：

| 保单号 | 客户姓名 | 报案金额 | 免赔额 | 赔付比例 | 实际赔付金额 |
| --- | --- | --- | --- | --- | --- |
| CL9900100 | 客户1 | 1234.56 | 500 | 0.80 | 587.65 |

它会：

1. **重算** `应赔 = (报案金额 - 免赔额) × 赔付比例`，全程 `Decimal`，`ROUND_HALF_UP` 保留两位；
2. **对账** 把重算结果与原表「实际赔付金额」比较（默认容差 0.01 元）；
3. **出报告** 一个 Excel，四个 sheet：
   - `审计摘要`：读取行数、成功解析、无法解析、一致/异常、一致率、金额合计；
   - `对账明细`：逐条列出重算值、原始值、差异、状态，金额是**数值**，可直接求和；
   - `异常数据`：只保留 `异常` 与 `解析失败` 的行；
   - `数据质量问题`：字段级校验问题（空值、精度、比例越界、保单号格式、跨字段矛盾）。
4. **给退出码**：全部一致 `0`，有差异或解析失败 `1`，系统异常 `2`——可以直接当流水线闸门用。
5. **可选 JSON**：加 `--json` 把机器可读摘要打到 stdout（日志走 stderr，可直接管道），`--json-out summary.json` 同时落盘。
6. **审计留痕**：加 `--manifest manifest.json` 输出输入文件 SHA256、字节数、工具版本与关键配置；同一输入两次运行，清单除时间外完全一致。

## 安装

```bash
git clone https://github.com/oiopuppy/Python-Enterprise-Automation.git
cd Python-Enterprise-Automation

python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate

pip install -e ".[dev]"
cp .env.example .env
```

要求 Python 3.9+。CI 在 3.9 和 3.12 上各跑一遍。

## 使用

```bash
# 生成 50 条模拟数据（默认注入约 10% 的赔付差异）并立刻审计
insurance-audit --generate-mock

# 审计已有文件，报告写到指定位置
insurance-audit --input data/claims.xlsx --output reports/2026-11.xlsx

# 审计并把机器可读摘要输出到 stdout（接调度/看板用）
insurance-audit --input data/claims.xlsx --output reports/2026-11.xlsx --json > reports/2026-11.json

# 或者让工具直接把摘要落盘
insurance-audit --input data/claims.xlsx --output reports/2026-11.xlsx --json-out reports/2026-11.json

# 同时输出审计清单（输入哈希/版本/配置，便于归档）
insurance-audit --input data/claims.xlsx --output reports/2026-11.xlsx --manifest reports/2026-11.manifest.json

# 不带参数：读 .env 里的 DATA_INPUT_FILE，写 reports/DATA_OUTPUT_FILE
insurance-audit

# 只看参数
insurance-audit --help
```

也可以当库用：

```python
from insurance_audit.core.engine import AuditEngine

summary = AuditEngine(input_file="claims.xlsx", output_file="report.xlsx").run()
print(summary.match_rate, summary.unmatched_records, summary.parse_error_records)
```

### 退出码

| 退出码 | 含义 |
| --- | --- |
| `0` | 审计完成，全部一致 |
| `1` | 审计完成，但存在对账异常 / 解析失败 / 输入文件缺失 |
| `2` | 系统异常（IO、配置等） |
| `3` | 安全异常 |
| `9` | 其他业务异常 |
| `99` | 未预期异常 |

### 模拟数据

`--generate-mock` 生成的是**可用于验收的脏数据**，不是「自己算自己」的假一致：

- 按 `anomaly_ratio=0.1` 注入 3~20 元的赔付差异（0 赔付行不注入）；
- 可用 `seed` 复现；`--generate-mock` 之后仍然会完整跑一遍审计，所以正常情况下退出码是 `1`。

## 配置

所有配置都有代码内默认值，`.env` 或环境变量可覆盖，优先级：**环境变量 > `.env` > 默认值**。

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `PROJECT_ROOT` | 源码根目录 | 项目根；容器内必须设为 `/app` |
| `APP_ENV` | `development` | `development` / `production` |
| `APP_LOG_LEVEL` | `INFO` | 日志级别 |
| `APP_LOG_FILE` | `logs/audit.log` | 运行日志（10MB 轮转，保留 30 份） |
| `AUDIT_LOG_FILE` | `logs/audit_trail.log` | 审计追溯日志 |
| `AUDIT_ENABLED` | `true` | 是否写审计追溯日志 |
| `DATA_INPUT_FILE` | `sample_claim_data.xlsx` | 默认输入文件 |
| `DATA_OUTPUT_FILE` | `final_settlement_report.xlsx` | 默认报告文件名 |
| `DATA_OUTPUT_DIR` | `reports` | 默认报告目录 |
| `INSURANCE_DEFAULT_DEDUCTIBLE` | `500` | 默认免赔额 |
| `INSURANCE_DEFAULT_RATIO` | `0.80` | 默认赔付比例 |
| `INSURANCE_DECIMAL_PLACES` | `2` | 金额精度 |
| `INSURANCE_POLICY_PREFIX` | `CL` | 保单号前缀 |
| `INSURANCE_MIN_CLAIM_AMOUNT` | `0.01` | 最小报案金额 |
| `INSURANCE_MAX_CLAIM_AMOUNT` | `99999999.99` | 最大报案金额 |

日志文件不可写时不会崩：自动降级为仅控制台输出，并打一条 warning。

## Docker

```bash
docker build -t insurance-audit:2.0.0 .

docker run --rm \
  -v "$PWD/data:/app/data" \
  -v "$PWD/reports:/app/reports" \
  insurance-audit:2.0.0 --generate-mock
```

镜像里 `PROJECT_ROOT=/app`，以非 root 用户 `auditor` 运行，healthcheck 会真实加载 CLI。

## 开发

```bash
ruff check src/ tests/ scripts/      # 静态检查
ruff format --check src/ tests/ scripts/
mypy --strict src/ --ignore-missing-imports
pytest -q                            # 63 个用例

# 文档与元数据检查（CI 里也会跑）
python scripts/check_markdown_links.py
python scripts/check_env_example.py
python scripts/check_version_consistency.py
```

CI（`.github/workflows/ci.yml`）按顺序跑：代码质量 → 安全扫描 → 测试矩阵（3.9 / 3.12）→ 构建。

分支模型很简单：`main` 是可发布版本，`develop` 是集成分支，所有改动从 `develop` 拉 `fix/`、`feat/`、`docs/` 分支，PR 合回 `develop`；到下个版本再合 `main`。详见 [docs/05-研发流程.md](docs/05-研发流程.md)。

## 项目结构

```
src/insurance_audit/
├── main.py              # CLI：参数、退出码、日志初始化
├── core/
│   ├── calculator.py    # 赔付公式（唯一实现）
│   ├── validator.py     # 列校验 + 逐行质量校验
│   └── engine.py        # AuditEngine：读 → 校验 → 对账 → 报告
├── data/
│   ├── reader.py        # Excel 读取
│   ├── writer.py        # Excel 写出 + 列宽
│   └── generator.py     # 模拟数据（可注入差异）
├── models/
│   └── claim.py         # ClaimRecord / AuditSummary
├── audit/
│   ├── reconciler.py    # 对账、解析失败收集、汇总
│   └── reporter.py      # 四表报告
└── utils/
    ├── config.py        # 三级配置
    ├── logger.py        # 惰性日志 + 审计日志
    └── exceptions.py    # 业务/数据/系统/安全四类异常
```

## 文档

| 文档 | 内容 |
| --- | --- |
| [docs/00-README.md](docs/00-README.md) | 文档索引与阅读路径 |
| [docs/01-产品与范围.md](docs/01-产品与范围.md) | 背景、目标、需求、验收标准、不做什么 |
| [docs/02-架构与设计.md](docs/02-架构与设计.md) | 分层、模块、数据流、关键决策 |
| [docs/03-详细设计.md](docs/03-详细设计.md) | 数据契约、接口、错误码、退出码 |
| [docs/04-质量与测试.md](docs/04-质量与测试.md) | 测试策略、用例、质量门禁、已知限制 |
| [docs/05-研发流程.md](docs/05-研发流程.md) | 分支、提交、PR、版本、发布 |
| [docs/06-项目记录.md](docs/06-项目记录.md) | 决策记录、风险、路线图 |
| [CHANGELOG.md](CHANGELOG.md) | 版本变更 |

## License

MIT，见 [LICENSE](LICENSE)。
