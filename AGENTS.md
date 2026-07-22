# AGENTS.md

本文件是仓库内所有自动化编码代理（包括 Codex）的最高优先级项目约束。开始任何修改前，必须先阅读本文件、`README.md`、`CONSTRAINTS.md`、设计文档和实现计划。

## 1. 项目目标

实现一个无前端、无用户体系的视频网站数据采集服务：

- FastAPI 提供任务创建、查询、强制取消、手动续跑和结果查询接口；
- 单个常驻 Worker 从 MySQL 领取任务；
- 每个采集任务在独立子进程和独立进程组中运行；
- Crawl4AI 管理 Chromium、持久化浏览器 Profile、页面加载和网络捕获；
- MySQL 保存结构化数据；
- MinIO 保存原始响应和可重新解析的采集材料；
- 底层链路完全通用，站点差异只能存在于 Adapter；
- Bilibili 是第一个 Adapter，首个列表入口为 `https://www.bilibili.com/v/popular/all`。

## 2. 允许采集的数据

只实现以下数据，不扩展范围：

1. 视频互动指标：
   - 播放量；
   - 点赞量；
   - 收藏量；
   - 分享/转发量；
   - 评论总数；
   - 弹幕/时间评论总数；
   - 平台特有指标，例如 `bilibili.coins`。
2. 评论区：
   - 一级评论；
   - 二级及更深回复（统一按父子关系保存）；
   - 评论文本、作者平台标识、作者展示名、点赞数、回复数、发布时间和必要状态。
3. 时间文本：
   - 弹幕；
   - 字幕；
   - 两者使用统一存储模型，通过 `content_type` 区分。

除定位、关联和调度所必需的字段外，不采集标题、简介、封面、标签、UP 主资料、粉丝量、视频文件、音频文件、推荐数据或 AI 分析结果。

## 3. 架构硬约束

### 3.1 通用 Core

Core 可以实现：

- 任务调度；
- 子进程与进程组生命周期；
- 强制取消；
- Crawl4AI 浏览器网关；
- Chromium Profile 管理和租约；
- 通用 HTTP 网关；
- 限速、超时、重试；
- 网络捕获；
- MySQL Repository；
- MinIO Raw Artifact Writer；
- 数据标准化校验；
- 结构化日志和敏感信息脱敏；
- 游标分页；
- 原始对象清理。

Core、API、Worker、Repository 和 Domain 中禁止出现以下站点细节：

- `bvid`、`aid`、`cid`；
- Bilibili API 路径、选择器、协议和字段名；
- 投币的业务解释；
- Bilibili 弹幕或字幕解析规则；
- Bilibili 热门页特有逻辑。

站点内部标识必须通过通用字段保存，例如 `platform_video_id`、`platform_unit_id` 和 `platform_ids: dict[str, str | int]`。

### 3.2 Adapter

Adapter 只负责：

- URL 匹配；
- 目标解析；
- 列表页目标发现；
- 平台请求编排；
- 平台响应解析；
- 平台字段到标准模型的映射；
- 平台特有指标声明；
- 登录态验证规则。

Adapter 禁止：

- 直接连接 MySQL；
- 直接连接 MinIO；
- 自行创建浏览器或持久化 Profile；
- 自行实现任务状态机；
- 自行创建任务子进程；
- 绕过统一限速、超时、取消和日志模块；
- 输出 Cookie、Authorization 或完整敏感请求头。

### 3.3 依赖方向

只允许以下依赖方向：

```text
API / Worker
    -> Application Services
    -> Domain Interfaces
    -> Infrastructure Gateways / Adapter Implementations
```

`domain` 不得依赖 FastAPI、SQLAlchemy、MinIO、Crawl4AI 或具体 Adapter。

## 4. 运行模型

- 只部署一个常驻 Worker；
- Worker 同时只执行一个采集任务；
- 每个任务启动独立子进程和独立 Unix 进程组；
- 取消时先发送 `SIGTERM`，宽限期后发送 `SIGKILL`；
- 必须终止整个进程组，避免遗留 Chromium 子进程；
- Worker 主进程不得长期持有 Crawl4AI 浏览器实例；
- 强制取消后保留已经提交的 MySQL 数据和已经完整写入的 MinIO 对象；
- 未提交事务必须回滚；
- 临时 MinIO 对象必须可回收；
- 后续只允许通过 API 手动续跑，不做自动无限续跑。

## 5. 任务与失败语义

逻辑任务状态：

```text
pending -> running -> success
                   -> partial
                   -> failed
                   -> cancelling -> cancelled
pending -------------------------> cancelled
```

- 指标、评论、弹幕或字幕任一模块失败：保存其他成功数据，视频任务标记为 `partial`；
- 目标身份无法解析或登录态完全失效：标记为 `failed`；
- 手动续跑跳过已成功模块，只执行失败、取消或未开始的模块；
- 手动续跑创建新的 `crawl_run`，不创建新的逻辑 `crawl_job`；
- 达到重试上限后停止，等待人工调用 `resume`；
- `resume` 可以覆盖部分策略，但必须保存新的完整有效策略快照。

## 6. 默认采集策略

- 热门列表默认发现 100 个视频；允许 API 覆盖，范围 `1..500`；
- 一级评论默认最多 1000 条；`0` 表示不限；
- 对已采集一级评论，默认抓取全部可访问回复；
- 默认抓取所有可访问弹幕；
- 默认抓取所有可访问字幕轨道；
- 弹幕/字幕分批写入 MySQL，每批默认 1000 条；
- 单 Worker、单 Profile 并发均固定为 1；
- 接口覆盖项必须经过服务端边界校验；
- 最终生效策略完整写入 `crawl_jobs.effective_strategy`；
- 保存 `strategy_version`，首版值为 `1`。

## 7. 存储约束

### 7.1 MySQL

- MySQL 8；
- InnoDB；
- `utf8mb4`；
- 应用时间统一使用 UTC；
- 数据库时间使用 `DATETIME(3)`；
- UUID 使用 `BINARY(16)`，应用层提供双向转换；
- 大量文本使用 `TEXT` 或 `MEDIUMTEXT`；
- 平台扩展字段使用 `JSON`；
- 使用 Alembic 管理迁移；
- 指标使用命名空间键，例如 `standard.views`、`bilibili.coins`；
- 指标缺失不能写成 `0`，必须区分 `available`、`unsupported`、`not_public`、`fetch_failed`；
- 评论、弹幕和字幕必须可幂等 Upsert；
- 指标每次采集生成新快照。

### 7.2 MinIO

- Bucket 默认名为 `crawler-raw`；
- 只保存原始响应、二进制弹幕、字幕源文件、诊断捕获和解析失败材料；
- 对象路径包含平台、日期、视频标识、运行 ID 和 artifact 类型；
- 数据库保存 bucket、object_key、etag、sha256、size、content_type 和 compression，不保存预签名 URL；
- 默认保留 30 天，`0` 表示永久；
- 清理只删除原始对象，不删除结构化数据；
- 正式对象必须在上传完成并校验后才可标记 `available`；
- 中断上传使用临时对象前缀并由清理器回收。

## 8. API 约束

- 不实现前端；
- 不实现用户、角色、注册、登录或 JWT；
- 可以实现可选固定 API Key：`X-API-Key`；
- `/health/live`、`/health/ready` 可公开；
- `/api/v1/*` 在启用 API Key 时必须鉴权；
- 任务只允许通过 FastAPI 手动创建；
- 不实现 Cron 或定时采集；
- 创建任务支持可选 `Idempotency-Key`，有效期 24 小时；
- 评论和时间文本查询使用游标分页；
- 默认 `page_size=100`，最大 `1000`；
- 禁止深分页 OFFSET；
- API 错误使用稳定的结构化错误码。

## 9. 登录态与安全

- 首版仅支持 Worker 挂载持久化 Chromium Profile；
- 不提供 Cookie JSON 上传接口；
- MySQL 不保存 Cookie、Local Storage 或登录令牌；
- Profile 路径只能是根目录下的安全相对目录名，必须防止路径穿越；
- API 容器不得挂载浏览器 Profile；
- Worker 独占 Profile；
- 登录失效时标记 Profile 为 `expired`，暂停相关任务；
- 不实现验证码绕过、DRM 绕过、付费墙绕过、访问控制绕过或签名对抗；
- 只处理用户凭自己的登录态正常可访问的数据；
- 所有日志必须脱敏。

## 10. 工程规范

- Python 3.12；
- FastAPI；
- Pydantic v2；
- SQLAlchemy 2.x async API；
- Alembic；
- MySQL 异步驱动；
- Crawl4AI；
- MinIO Python SDK；
- pytest + pytest-asyncio；
- Ruff；
- mypy；
- structlog 或等价结构化日志方案。

必须采用测试驱动开发：

1. 先写失败测试；
2. 运行并确认失败原因正确；
3. 写最小实现；
4. 运行测试；
5. 通过后提交；
6. 每个计划任务形成独立、可审查的提交。

CI 中禁止依赖 Bilibili 实时网络。Adapter 测试必须使用本地 fixture 或 mock gateway。真实登录态测试只能作为显式手动测试。

## 11. Definition of Done

一个功能只有在以下条件全部满足时才算完成：

- 单元测试通过；
- 集成测试通过；
- `ruff check` 通过；
- `ruff format --check` 通过；
- `mypy` 通过；
- Alembic 可从空库升级到最新版本；
- Docker Compose 健康检查通过；
- 日志中不存在敏感值；
- Core 中不存在站点特有逻辑；
- 文档同步更新；
- 强制取消不会遗留 Chromium 进程；
- 重复采集不会重复插入评论、弹幕或字幕；
- 部分失败能够保留成功数据并手动续跑。

## 12. Codex 工作方式

- 严格按 `docs/superpowers/plans/2026-07-19-video-crawler-platform.md` 顺序执行；
- 每个任务开始前确认依赖接口与前序任务一致；
- 当前环境不可使用 `rg`；文件发现和文本检索必须使用 PowerShell 的 `Get-ChildItem -Recurse` 与 `Select-String`，不得调用或推荐 `rg` 命令；
- 禁止使用子智能体、多智能体或并行代理进行开发，不得通过 spawn、dispatch 或 delegate 将实现、测试、审查等工作交给其他智能体；所有仓库工作必须由当前智能体独立完成。实现计划中关于子智能体驱动开发的建议不适用于本仓库；
- 不自行扩大数据采集范围；
- 不自行引入 Redis、Celery、Kafka、前端或用户系统；
- 不改变单 Worker 约束；
- 发现文档矛盾时，优先级为：`AGENTS.md` > `CONSTRAINTS.md` > 设计文档 > 实现计划 > README；
- 需要偏离硬约束时必须停止并请求人工决策；
- 不把任何真实 Cookie、账号、Profile 数据或站点响应提交到 Git。
