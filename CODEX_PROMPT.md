# Codex 启动提示

你正在实现一个通用视频网站数据采集服务。请先完整阅读：

- `AGENTS.md`
- `CONSTRAINTS.md`
- `README.md`
- `docs/specs/2026-07-19-video-crawler-design.md`
- `docs/architecture/adapter-contract.md`
- `docs/architecture/database-schema.md`
- `docs/api-contract.md`
- `docs/state-machines.md`
- `docs/security-and-compliance.md`
- `docs/testing-strategy.md`
- `docs/superpowers/plans/2026-07-19-video-crawler-platform.md`

## 执行要求

1. 严格按实现计划的任务顺序执行；
2. 每个任务先写失败测试，再实现最小代码，再运行完整相关测试；
3. 每个任务形成独立 Git 提交；
4. 不实现前端、用户体系、定时任务、Redis、Celery、Kafka 或多 Worker；
5. Core、Domain、API、Worker 和 Repository 不得包含 Bilibili 特有字段或逻辑；
6. Bilibili 差异必须全部位于 `src/video_crawler/adapters/bilibili/`；
7. CI 不访问真实 Bilibili；使用 mock gateway 和脱敏 fixture；
8. 不实现验证码、DRM、付费墙、访问控制或风控绕过；
9. 不提交 Cookie、Profile、真实账号、真实密钥和未脱敏响应；
10. 实现过程中发现规格冲突时，遵循 `AGENTS.md` 中的优先级并停止请求人工决策。

## 第一条指令

从实现计划 Task 1 开始。完成 Task 1 的测试、实现、静态检查和提交后，再进入 Task 2。不要一次性生成整个项目后才测试。

## 每个任务结束时输出

- 修改文件；
- 新增或修改的公共接口；
- 执行的测试和结果；
- 静态检查结果；
- 提交哈希；
- 下一任务依赖检查。
