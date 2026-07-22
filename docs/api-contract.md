# FastAPI API Contract

本文描述 0.1.0 实际发布接口。所有业务接口位于 `/api/v1`；启用固定 API Key 时，请求头为 `X-API-Key`。`/health/live` 和 `/health/ready` 始终公开。除本文列出的路径外，0.1.0 不提供其他业务接口。

## 1. 创建任务

```http
POST /api/v1/crawl-jobs
Idempotency-Key: optional-string
```

请求：

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
    "timed_text_batch_size": 1000,
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

响应 `202`：

```json
{
  "job_id": "01900000-0000-7000-8000-000000000002",
  "status": "pending",
  "strategy_version": 1,
  "effective_strategy": {}
}
```

同一 `Idempotency-Key` 和相同请求在 24 小时内返回原任务，状态码 `200`；同一键对应不同请求时返回 `409 IDEMPOTENCY_CONFLICT`。

## 2. 查询任务

```http
GET /api/v1/crawl-jobs/{job_id}
```

响应包含：

- 状态；
- source URL；
- 父任务 ID；
- root 任务 ID；
- 进度；
- 模块状态；
- 生效策略；
- 创建、开始、结束时间；
- 脱敏错误。

## 3. 取消任务

```http
POST /api/v1/crawl-jobs/{job_id}/cancel
```

- `pending` 直接变为 `cancelled`；
- `running` 变为 `cancelling`，Worker 强制终止进程组；
- 已终态返回 `409 JOB_NOT_CANCELLABLE`。

## 4. 手动续跑

```http
POST /api/v1/crawl-jobs/{job_id}/resume
```

请求可以为空，也可以覆盖部分策略：

```json
{
  "strategy": {
    "max_retries": 2,
    "request_timeout_seconds": 60
  }
}
```

- 仅允许 `partial`、`failed`、`cancelled`；
- 重置需要执行的模块为 `pending`；
- 已成功模块保持成功；
- 创建新的 `crawl_run`；
- 逻辑 job ID 不变。

## 5. Profile

```http
POST /api/v1/auth-profiles
GET /api/v1/auth-profiles
GET /api/v1/auth-profiles/{profile_id}
POST /api/v1/auth-profiles/{profile_id}/verify
GET /api/v1/auth-profiles/{profile_id}/verifications/{verification_id}
POST /api/v1/auth-profiles/{profile_id}/enable
POST /api/v1/auth-profiles/{profile_id}/disable
```

创建请求：

```json
{
  "platform": "bilibili",
  "profile_name": "bilibili-main",
  "profile_directory": "bilibili-main"
}
```

Profile API 不返回 Cookie 或文件内容。新 Profile 初始状态为 `expired`。调用 `verify` 返回
HTTP 202，并创建或复用一个异步验证请求：

```json
{
  "verification_id": "01900000-0000-7000-8000-000000000002",
  "profile_id": "01900000-0000-7000-8000-000000000001",
  "status": "pending",
  "profile_status": "expired",
  "requested_at": "2026-07-22T12:30:00Z",
  "started_at": null,
  "finished_at": null,
  "error_code": null,
  "error_message": null
}
```

验证请求状态为 `pending`、`running`、`succeeded` 或 `failed`。客户端使用 Profile 范围内的
查询接口轮询；只有 `status=succeeded` 且 `profile_status=active` 才表示登录态有效。Worker
未运行时请求保持 `pending`，API 不会自行读取 Profile 或把等待误判为 `expired`。重复调用
`verify` 会复用尚未终态的请求；终态后再次调用会创建新请求。

创建任务前必须确认 Profile 存在且状态为 `active`。Profile 不存在时返回 HTTP 404
`PROFILE_NOT_FOUND`；状态为 `expired` 或 `disabled` 时返回 HTTP 409
`PROFILE_NOT_ACTIVE`。已经进入 `pending` 的任务在 Profile 变为非 active 后暂停领取；Profile
重新登录并验证为 active 后可以继续领取。

## 6. 指标

```http
GET /api/v1/videos/{video_id}/metrics?cursor=&page_size=100
GET /api/v1/videos/{video_id}/metrics/latest
```

快照响应：

```json
{
  "snapshot_id": 1,
  "captured_at": "2026-07-19T12:00:00Z",
  "metrics": {
    "standard.views": {"value": 100000, "status": "available"},
    "bilibili.coins": {"value": 1200, "status": "available"}
  }
}
```

列表按 `captured_at DESC, id DESC` 排序，使用不透明 `cursor` 继续 keyset 分页；`page_size` 默认 100、最大 1000。`latest` 没有快照时返回 `404 RESULT_NOT_FOUND`。

## 7. 评论

```http
GET /api/v1/videos/{video_id}/comments
```

参数：

- `cursor`；
- `page_size`，默认 100，最大 1000；
- `root_only`；
- `root_comment_id`；
- `order=asc|desc`。

排序键：`published_at, id`。

## 8. 时间文本

```http
GET /api/v1/video-units/{unit_id}/timed-text
```

参数：

- `content_type=danmaku|subtitle`；
- `language_code`；
- `start_ms`；
- `end_ms`；
- `cursor`；
- `page_size`，默认 100，最大 1000。

排序键：`start_ms, id`。

## 9. 健康检查

```http
GET /health/live
GET /health/ready
```

`ready` 检查：

- MySQL 连接；
- 当前 Alembic revision；
- MinIO 可访问；
- Bucket 存在。

## 10. 错误格式

```json
{
  "error": {
    "code": "JOB_NOT_FOUND",
    "message": "crawl job was not found",
    "request_id": "019...",
    "details": {}
  }
}
```

0.1.0 API 会返回：

- `VALIDATION_ERROR`；
- `UNAUTHORIZED`；
- `IDEMPOTENCY_CONFLICT`；
- `JOB_NOT_FOUND`；
- `JOB_NOT_CANCELLABLE`；
- `JOB_NOT_RESUMABLE`；
- `PROFILE_NOT_FOUND`；
- `PROFILE_VERIFICATION_NOT_FOUND`；
- `PROFILE_NOT_ACTIVE`；
- `DISCOVERY_EMPTY`；
- `STORAGE_UNAVAILABLE`；
- `INVALID_CURSOR`；
- `RESULT_NOT_FOUND`。

Bilibili 热门列表在捕获响应、DOM 和公开 HTTP 回退均未发现有效目标时，`discovery` 模块及
根任务失败，任务/run 错误码为 `DISCOVERY_EMPTY`。该错误通过现有任务错误字段返回，不新增
API 端点；诊断详情只包含各来源的响应数和候选数，不包含 Cookie、Authorization 或完整响应头。
