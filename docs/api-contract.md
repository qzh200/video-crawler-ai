# FastAPI API Contract

所有业务接口位于 `/api/v1`。启用固定 API Key 时，请求头为 `X-API-Key`。

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

同一 `Idempotency-Key` 在 24 小时内返回相同任务，状态码 `200`。

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

Profile API 不返回 Cookie 或文件内容。

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
- `page_size`。

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

至少定义：

- `VALIDATION_ERROR`；
- `UNAUTHORIZED`；
- `JOB_NOT_FOUND`；
- `JOB_NOT_CANCELLABLE`；
- `JOB_NOT_RESUMABLE`；
- `PROFILE_NOT_FOUND`；
- `PROFILE_EXPIRED`；
- `ADAPTER_NOT_FOUND`；
- `TARGET_RESOLUTION_FAILED`；
- `STORAGE_UNAVAILABLE`；
- `UPSTREAM_ERROR`。
