# 通用视频网站数据采集服务

这是一个面向 Codex 实现的项目规格仓库。项目提供无前端的 FastAPI 服务，通过单个独立 Worker 使用 Crawl4AI 和持久化 Chromium Profile 采集视频网站的互动指标、评论、弹幕和字幕。

Bilibili 是第一个站点适配器，但 API、任务调度、浏览器管理、存储和数据模型必须保持站点无关。

## 当前范围

采集并保存：

- 播放量；
- 点赞量；
- 收藏量；
- 分享/转发量；
- 评论总数；
- 弹幕总数；
- 平台特有指标，例如 Bilibili 投币；
- 一级评论和回复；
- 弹幕；
- 所有可访问字幕轨道。

不做：

- 前端；
- 用户体系；
- 定时调度；
- 多 Worker；
- 视频或音频下载；
- 标题、简介、封面、UP 主资料等额外业务采集；
- 验证码、DRM、付费墙或访问控制绕过。

## 架构

```text
Client
  -> FastAPI API
       -> MySQL: jobs, runs, structured results

Single Worker
  -> claims MySQL job
  -> spawns isolated task process group
  -> Crawl4AI + Chromium persistent profile
  -> selects site Adapter
  -> MinIO: raw artifacts
  -> MySQL: normalized metrics/comments/timed text
```

核心原则：

```text
Core 决定怎么采
Adapter 决定从哪里取以及怎么解析
Domain 决定结果长什么样
Repository 决定怎么存
FastAPI 决定怎么调用
Worker 决定什么时候执行
```

## Docker Compose 服务

- `mysql`：结构化存储和任务队列；
- `minio`：原始响应对象存储；
- `minio-init`：创建 Bucket；
- `migrate`：执行 Alembic；
- `api`：FastAPI；
- `worker`：单个常驻 Worker。

API 与 Worker 使用同一镜像、不同启动命令。API 不挂载浏览器 Profile，Worker 挂载 Profile Volume。

## 主要接口

```text
POST /api/v1/crawl-jobs
GET  /api/v1/crawl-jobs/{job_id}
POST /api/v1/crawl-jobs/{job_id}/cancel
POST /api/v1/crawl-jobs/{job_id}/resume

POST /api/v1/auth-profiles
GET  /api/v1/auth-profiles
GET  /api/v1/auth-profiles/{profile_id}
POST /api/v1/auth-profiles/{profile_id}/verify
POST /api/v1/auth-profiles/{profile_id}/enable
POST /api/v1/auth-profiles/{profile_id}/disable

GET /api/v1/videos/{video_id}/metrics
GET /api/v1/videos/{video_id}/metrics/latest
GET /api/v1/videos/{video_id}/comments
GET /api/v1/video-units/{unit_id}/timed-text

GET /health/live
GET /health/ready
```

## 创建任务示例

```http
POST /api/v1/crawl-jobs
Idempotency-Key: example-20260719-001
X-API-Key: change-me
Content-Type: application/json
```

```json
{
  "source_url": "https://www.bilibili.com/v/popular/all",
  "auth_profile_id": "01900000-0000-7000-8000-000000000001",
  "video_limit": 100,
  "strategy": {
    "max_root_comments": 1000,
    "fetch_all_replies": true,
    "fetch_all_danmaku": true,
    "fetch_all_subtitles": true,
    "max_retries": 3,
    "video_delay_min_seconds": 1.0,
    "video_delay_max_seconds": 3.0,
    "comment_page_delay_min_seconds": 0.8,
    "comment_page_delay_max_seconds": 1.5,
    "request_timeout_seconds": 30,
    "page_timeout_seconds": 60
  }
}
```

## 任务语义

- 列表任务发现视频后创建子任务；
- 指标、评论或时间文本部分失败时保留成功数据，任务为 `partial`；
- 身份解析失败或登录态完全失效时任务为 `failed`；
- 取消采用任务进程组强制终止；
- 手动续跑只补失败或未完成模块；
- 指标每次采集生成新快照；
- 评论、弹幕和字幕通过业务唯一键幂等 Upsert。

## 开始实现

Codex 必须按以下顺序阅读：

1. `AGENTS.md`
2. `CONSTRAINTS.md`
3. `docs/specs/2026-07-19-video-crawler-design.md`
4. `docs/architecture/adapter-contract.md`
5. `docs/architecture/database-schema.md`
6. `docs/api-contract.md`
7. `docs/superpowers/plans/2026-07-19-video-crawler-platform.md`
8. `CODEX_PROMPT.md`

执行命令和验收门槛写在实现计划中。

## 本仓库当前状态

本交接包提供规格、约束、参考 Schema、Compose 模板和实施计划。业务实现代码由 Codex 按计划创建。
