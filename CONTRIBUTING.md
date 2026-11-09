# 参与开发

这是个单人维护的个人项目，文档尽量精简；下面写清楚「改代码前后要做什么」，方便未来的自己（和偶尔的贡献者）少踩坑。

## 环境

- Python **3.9+**（CI 同时跑 3.9 与 3.12）；
- 安装开发依赖：`pip install -e ".[dev]"`；
- 日志目录不可写时，用 `APP_LOG_FILE` / `AUDIT_LOG_FILE` 指向可写路径（比如临时目录）。

## 改代码前

1. 从 `develop` 拉分支，不要直接改 `main` 或 `develop`；
2. 分支名：`feat/`、`fix/`、`chore/`、`docs/` 前缀，例如 `fix/parse-error-tracking`；
3. 一个 PR 只做一件事，控制在 600 行以内，超过就拆。

## 门禁（提交前必须全绿）

```bash
ruff check src/ tests/ scripts/
ruff format --check src/ tests/ scripts/
mypy --strict src/ --ignore-missing-imports
pytest
python scripts/check_markdown_links.py
python scripts/check_env_example.py
python scripts/check_version_consistency.py
```

新增行为要有测试；改接口要同步改文档（README、`docs/03`、CHANGELOG）。

## 提交信息

用 Conventional Commits，一句话说清做了什么：

```
fix(reconciler): 解析失败的行不再静默丢弃
docs(readme): 补充 --input/--output 说明
ci: 增加 concurrency 避免重复跑流水线
```

## PR 流程

1. push 分支，开 PR，**base 选 `develop`**，先转 Draft；
2. 按 `.github/pull_request_template.md` 填动机、改动、验证、风险、不在本 PR 的范围；
3. 等 CI 全绿，自己按模板逐项自查；
4. 留审查评论，写下 GO 记录（`GO / HEAD=<完整 SHA> / CI=GREEN / REVIEW=... / DOD=PASS`），再合并；
5. 合并后删分支，`develop` 保持随时可发布。

`main` 只在发版时从 `develop` 合并，平时不动。

## 代码约定

- 金额一律 `Decimal`，禁止用 `float` 参与计算；
- 异常按层级抛：`BusinessException` / `DataException` / `SystemException` / `SecurityException`，不要吞掉原始 `except`；
- 解析失败的行必须保留在报告里，不能静默丢弃（这是审计目标的一部分）；
- 模块依赖只能向下：`models` 不 import `core`，`utils` 不 import 业务模块，`main` 只做参数与退出码。
