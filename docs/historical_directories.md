# 历史目录说明

仓库主线仅为当前 `A-LLM-` worktree，日常开发分支为 `main`。原同级目录 `A-LLM-data-engineering-publish`、`A-LLM-engineering-quality` 和 `A-LLM-portfolio-backtest-only` 已于 2026-07-19 安全移除，不再作为运行入口。

历史提交由以下本地标签保留：

- `archive/data-engineering-module-20260708`
- `archive/engineering-quality-ci-cli-20260708`
- `archive/portfolio-backtest-local-main-20260708`
- `archive/llm-event-module-implementation-20260708`

完整历史 worktree 快照和 Git bundle 位于上级工作区的 `repository_backups/20260719-122849/`。如需检查旧实现，应从标签临时创建 worktree；不要恢复为长期并行开发目录，也不要把历史目录加入 `PYTHONPATH`。
