# 系统架构文档 — Architecture Document

## 1. 设计原则

### 1.1 分层架构

```
┌──────────────────────────────────────────────┐
│               main.py (入口层)                │
│    CLI / 编程式调用 / Docker EntryPoint       │
├──────────────────────────────────────────────┤
│           audit/ (审计引擎层)                 │
│    reconciler.py  reporter.py                │
├──────────────────────────────────────────────┤
│           core/ (核心业务层)                  │
│    calculator.py  validator.py  engine.py    │
├──────────────────────────────────────────────┤
│           data/ (数据访问层)                  │
│    reader.py  writer.py  generator.py        │
├──────────────────────────────────────────────┤
│          models/ (数据模型层)                 │
│    claim.py  audit.py (Pydantic v2)         │
├──────────────────────────────────────────────┤
│         utils/ (基础设施层)                   │
│  config.py  logger.py  exceptions.py         │
└──────────────────────────────────────────────┘
```

### 1.2 分层职责

| 层级 | 职责 | 技术选型 |
|------|------|----------|
| **入口层** | CLI参数解析、工作流编排、异常捕获 | Python argparse |
| **审计引擎层** | 对账、差异分析、报告生成 | Pandas |
| **核心业务层** | 赔付计算、数据校验、业务规则 | Decimal / Pydantic |
| **数据访问层** | Excel读写、数据生成 | Pandas / openpyxl |
| **数据模型层** | 领域模型定义、类型校验 | Pydantic v2 |
| **基础设施层** | 配置、日志、异常体系 | python-dotenv + logging |

### 1.3 核心改进对比

| 维度 | 原版 v1 | 重构版 v2 |
|------|---------|-----------|
| 金额类型 | `float` → 精度丢失 | `decimal.Decimal` → 精确计算 |
| 四舍五入 | Python默认（银行家舍入） | `ROUND_HALF_UP`（中国财务规范） |
| 配置管理 | 代码硬编码 | `.env` + 环境变量 + 默认值三级覆盖 |
| 日志 | 仅控制台 | 控制台+文件轮转（30天）+ 独立审计日志 |
| 数据校验 | 无 | Pydantic v2 + 可配置约束 |
| 项目结构 | 散落根目录 | 标准 src 布局 + pyproject.toml |
| 测试 | 4个测试用例 | 50+测试用例，单元+集成 |
| CI/CD | 无 | GitHub Actions全流程自动化 |
| 部署 | 无 | Docker多阶段构建 |
| 代码质量 | 无 | Ruff + MyPy + Pre-commit |

## 2. 数据流

```
Excel文件 → reader.py → DataFrame → validator.py
                                         ↓
                                    校验通过？
                                    /        \
                                  是          否 → 记录错误日志
                                   ↓
                              calculator.py (批量计算)
                                   ↓
                              reconciler.py (对账比较)
                                   ↓
                              reporter.py (生成报告)
                                   ↓
                              writer.py → Excel报告
```

## 3. 异常处理策略

```
InsuranceAuditError (基类)
├── BusinessException (业务异常，需人工介入)
│   ├── ClaimAmountExceedsLimitError
│   ├── NegativeClaimAmountError
│   ├── InvalidDeductibleError
│   ├── InvalidRatioError
│   └── ReconciliationMismatchError
├── DataException (数据异常，需数据治理)
│   ├── FileNotFoundError
│   ├── InvalidColumnError
│   └── DataValidationError
├── SystemException (系统异常，可重试)
│   ├── IOFailure
│   └── ConfigurationError
└── SecurityException (安全异常，需审计)
```

## 4. 配置优先级

```
1. 环境变量（最高优先级）
        ↑
2. .env 文件
        ↑
3. 代码默认值（最低优先级，兜底）
```

## 5. 技术债务与后续规划

- [ ] 数据库存储支持（SQLite/PostgreSQL）
- [ ] Web管理界面（Flask/FastAPI）
- [ ] 消息队列异步处理（Celery）
- [ ] 多数据源支持（CSV/数据库/API）
- [ ] 权限管理系统
- [ ] 审计结果可视化仪表盘
- [ ] 定时任务调度
