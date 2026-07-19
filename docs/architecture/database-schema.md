# MySQL 数据库结构

## 1. 原则

- MySQL 8、InnoDB、utf8mb4；
- UTC `DATETIME(3)`；
- UUID 使用 `BINARY(16)`；
- 迁移由 Alembic 管理；
- `sql/reference_schema.sql` 是设计参考，不是迁移来源；
- 标准字段关系化，平台扩展使用 JSON；
- 原始大响应保存在 MinIO。

## 2. 表清单

### 平台与认证

- `platforms`
- `auth_profiles`
- `auth_profile_leases`

### 内容定位

- `videos`
- `video_units`
- `target_discoveries`

### 指标

- `metric_definitions`
- `metric_snapshots`
- `metric_values`

### 评论

- `comments`

### 时间文本

- `timed_text_streams`
- `timed_text_items`

### 任务

- `crawl_jobs`
- `crawl_runs`
- `crawl_module_runs`
- `idempotency_keys`

### 原始对象

- `raw_artifacts`

## 3. 关键唯一约束

```text
platforms(platform_key)
auth_profiles(platform_id, profile_directory)
videos(platform_id, platform_video_id)
video_units(video_id, platform_unit_id)
metric_values(snapshot_id, metric_key)
comments(video_id, platform_comment_id)
timed_text_streams(video_unit_id, content_type, stream_key, language_code_normalized)
timed_text_items(stream_id, dedup_key)
idempotency_keys(idempotency_key)
```

## 4. 指标种子

```text
standard.views
standard.likes
standard.favorites
standard.shares
standard.comments
standard.timed_comments
bilibili.coins
```

## 5. 评论树解析

Adapter 输出平台父子 ID。Repository 在同一批次内：

1. Upsert 所有评论；
2. 查询平台 ID 到内部 ID 映射；
3. 更新 `root_comment_id` 和 `parent_comment_id`；
4. 对暂未出现的父节点保留内部字段为空，但保留平台父 ID；
5. 后续批次补齐关系。

## 6. 时间文本去重

`dedup_key` 由 Domain 服务生成：

- 有平台条目 ID：`sha256(platform_item_id)`；
- 字幕无 ID：`sha256(start_ms|end_ms|text)`；
- 弹幕无 ID：`sha256(start_ms|published_at|sender_ref|text)`。

## 7. 指标快照

每个成功或部分成功的指标抓取都创建一个快照。失败指标仍可写入 `metric_values`，状态为 `fetch_failed`，值为空。

## 8. 原始对象

`raw_artifacts` 保存：

- `bucket`；
- `object_key`；
- `artifact_type`；
- `content_type`；
- `compression`；
- `etag`；
- `sha256`；
- `size_bytes`；
- `storage_status`；
- `captured_at`；
- `expires_at`；
- `deleted_at`。

正式对象写入流程：

```text
create row(uploading)
-> upload temporary object
-> verify size/hash
-> copy to final key
-> delete temporary object
-> update row(available)
```
