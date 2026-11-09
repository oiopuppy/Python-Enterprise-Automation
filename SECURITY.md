# 安全策略

## 支持范围

安全修复针对 `develop` 与最新发布的主版本（当前 2.x）。旧版本不单独维护。

## 报告漏洞

**不要**用公开 issue 报告安全问题。请通过以下方式私下联系：

- GitHub 仓库的「Security → Report a vulnerability」入口（Security Advisories）；
- 或直接私信维护者 [@oiopuppy](https://github.com/oiopuppy)。

请在报告里说明：影响版本、复现步骤、可能的后果。确认后会尽快修复并在 CHANGELOG 中致谢（如果你愿意留名）。

## 数据处理注意

本项目在本地处理 Excel 台账，不联网、没有服务端，但台账本身包含客户姓名、保单号等个人信息：

- 建议只在受控机器上运行，处理完的台账与审计报告不要上传到公开位置；
- `.env` 与 `logs/` 已在 `.gitignore` 中，不要把真实台账、报告或密钥提交进仓库；
- 日志只记录操作与统计信息，不记录客户姓名等业务字段。

## 依赖安全

CI 的安全扫描使用 bandit（`bandit -r src/ -ll`）检查常见模式问题；第三方依赖的漏洞通过 GitHub Dependabot 提醒（如已启用）。
