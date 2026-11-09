# 更新日志

本项目遵循 [SemVer](https://semver.org/lang/zh-CN/)；记录格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

## [Unreleased]

## [2.0.0] - 2026-11-10

v2 是对 v1 的重写：把「能跑」变成「结论可信、失败可见、能在真实环境跑」。命令行接口、配置项、报告结构相对 v1 均不兼容。

### 新增

- `--input` / `--output` 参数，不再只能读项目根下的固定文件；`--help` 在只读环境可用。
- 报告第 4 个 sheet「数据质量问题」：字段级问题（小数位、比例越界、保单号格式、实际赔付异常）逐条列出，不阻断对账。
- `AuditSummary` 新增 `source_records`（读取总行数）、`parse_error_records`、`parse_errors`（行号/保单号/原因），满足恒等式 `读取总行数 = 成功解析 + 无法解析`。
- `PROJECT_ROOT` 环境变量，容器内可显式指定项目根。
- `setup_logging()` / `get_audit_logger()`：日志配置与实例获取分离，导入包不再产生文件副作用。
- `auto_adjust_column_width()` 供所有 Excel 输出复用。
- 测试从 0 增至 58 个用例，覆盖率 87%。

### 变更

- 金额计算全程 `Decimal`，`ROUND_HALF_UP` 保留两位；对账容差 `0.01`。
- 退出码语义固定：`0` 正常 / `1` 审计问题 / `2` 系统错误 / `3` 安全错误 / `9` 业务错误 / `99` 未捕获异常。
- `claim_record` 模型层只做字段级校验；跨字段规则（实际赔付 > 报案金额等）改为质量问题提示。
- `run_audit()` 改为调用 `AuditEngine`，删除重复的编排逻辑；赔付公式只保留 `core/calculator.py` 一份实现。
- `generate_mock_data()` 默认写入配置的输入路径（不再落到当前工作目录），并默认注入约 10% 的差异行，`seed` 可复现。
- `pyproject.toml` 统一 ruff / mypy / pytest 配置，删除 `pytest.ini`；`ruff.target-version` 为 `py39`，`mypy.python_version` 为 `3.10`。
- CI 测试矩阵为 Python `3.9` 与 `3.12`；lint job 安装完整依赖（否则 `pydantic` 缺失导致 mypy 假阳性）。

### 修复

- 解析失败的行不再被 `continue` 静默丢弃：保留在明细、计入「无法解析」、不一致率分母里混入脏数据。
- `main()` 环境检查失败时提前 `return` 导致进程退出码恒为 `0`（流水线永远绿）。
- 从非项目目录运行时，mock 生成位置与审计读取位置不一致，导致读到旧数据或报「文件不存在」。
- 中文 Windows（GBK）控制台输出 `¥`（U+00A5）抛 `UnicodeEncodeError`；日志正文混入 ANSI 转义序列。
- 模块导入即创建 `logs/audit_trail.log`，只读目录/容器挂载下启动崩溃；文件不可写时改为降级为仅控制台。
- Docker 内 `parents[3]` 指向 Python 安装目录，配置/日志/报告路径全部跑偏；健康检查只 `import insurance_audit`，查不出启动崩溃。
- `ruff` 81 个错误、`ruff format` 13 个文件、`mypy --strict` 16 个错误清零。
- 删除 `json_encoders`（Pydantic v2.13 弃用），消除 5 条弃用警告。

### 删除

- `pytest.ini`（与 `pyproject.toml` 冲突）。
- `prod` 依赖组中的 `gunicorn`、`supervisor`（本项目是 CLI，无常驻服务）。
- `secret_key` / `data_encryption_enabled` 配置项（从未有实现，留着误导人）。
- `docs/ARCHITECTURE.md`（内容并入 `docs/02-架构与设计.md`，原文件的模块清单不实）。
- `sample_claim_data.xlsx` 取消版本跟踪（生成物不入库）。

## [1.0.0] - 早期

首个可用版本：读取 Excel、按 `(报案金额 - 免赔额) × 赔付比例` 重算、输出单 sheet 报告。实现细节见 git 历史。
