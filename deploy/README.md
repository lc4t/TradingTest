# deploy/

这里存放**外部私有仓库** `lc4t/github-action` 里用到的 workflow 的参考副本，
方便版本管理与 review（真正生效的文件在那个私有仓库的 `.github/workflows/` 下）。

## github-action.trading-v2.yml

每个交易日 0:00（北京时间）跑的"回测 + 部署"流水线。设计要点：

- **主流程（数据同步 + 8 个单标的回测 + 当日信号汇总）跑在已验证的
  `ghcr.io/lc4t/trading-1.0:latest` 镜像上**——保持稳定，行为零变化。
- **动量轮动是独立的、`continue-on-error: true` 的步骤**，跑在
  `ghcr.io/lc4t/trading-2.0.0.dev:latest` 上，挂了也不影响日报和部署。
- 前端从 `2.0.0.dev` 分支 checkout（含 `/rotation` 页面），构建后部署到
  Cloudflare Pages。
- **部署用 `--branch=dev`**：Cloudflare Pages 项目 `trading` 的「生产分支」是
  `dev`，自定义域名 `trading.sakanano.moe` 只服务生产部署。wrangler 必须显式
  `--branch=dev` 才会更新生产域名；传别的分支名（如 `1.0`/`2.0.0.dev`）只会生成
  预览别名（`<branch>.trading-6kg.pages.dev`），不更新生产站。
- `--commit-message="ci deploy" --commit-dirty=true`：固定 ASCII 提交信息，
  绕开 wrangler 自动读取 git 提交信息时触发的 CF API UTF-8 校验报错（code 8000111）。

### 应用方式

修改 `.github/workflows/*` 需要 token 带 `workflow` scope：

```bash
gh auth refresh -h github.com -s workflow
# 然后把本文件内容覆盖到 lc4t/github-action 的 .github/workflows/trading-v2.yml
```
