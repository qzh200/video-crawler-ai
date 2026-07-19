# Codex 交接入口

将整个目录复制到新的 Git 仓库根目录，然后让 Codex 从 `CODEX_PROMPT.md` 开始。

## 必读顺序

1. `AGENTS.md`
2. `CONSTRAINTS.md`
3. `README.md`
4. `docs/specs/2026-07-19-video-crawler-design.md`
5. `docs/architecture/adapter-contract.md`
6. `docs/architecture/database-schema.md`
7. `docs/api-contract.md`
8. `docs/state-machines.md`
9. `docs/security-and-compliance.md`
10. `docs/testing-strategy.md`
11. `docs/superpowers/plans/2026-07-19-video-crawler-platform.md`
12. `CODEX_PROMPT.md`

## 推荐给 Codex 的首条消息

```text
阅读 CODEX_PROMPT.md 和其中列出的全部文件，严格按实现计划从 Task 1 开始，以 TDD 和原子提交方式完成。不要增加前端、用户体系、定时任务、多 Worker，也不要把 Bilibili 逻辑放入通用 Core。
```

## 当前交付状态

这是规格和实现脚手架，不包含采集业务实现。`compose.yaml`、`Dockerfile` 和 `pyproject.toml` 是约束模板；Codex 必须在 Task 21 按官方文档验证并固定镜像与浏览器依赖。
