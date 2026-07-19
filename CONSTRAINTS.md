# 项目硬约束

本文档将讨论结果转换为不可随意修改的工程约束。Codex 实现过程中不得以“更方便”为由绕过这些约束。

## 产品边界

- 无前端；
- 无用户体系；
- 无定时采集；
- 只有手动 API 触发；
- 只有一个 Worker；
- 首个 Adapter 为 Bilibili；
- 首个列表入口为 Bilibili 综合热门页；
- 底层链路必须支持后续新增其他视频网站 Adapter。

## 数据范围

只保存：

- 播放、点赞、收藏、分享、评论总数、弹幕总数；
- 平台特有互动指标，例如 Bilibili 投币；
- 评论和回复；
- 弹幕和字幕。

最少定位字段可以保存：

- platform；
- platform_video_id；
- platform_unit_id；
- canonical_url；
- captured_at；
- 平台内部 ID JSON。

不保存与上述目标无关的业务字段。

## 通用链路不变量

```text
Create Job
  -> Claim Job
  -> Select Adapter
  -> Acquire Profile Lease
  -> Spawn Task Process Group
  -> Resolve Target
  -> Discover Child Targets when needed
  -> Fetch Metrics
  -> Fetch Comments
  -> Fetch Timed Text
  -> Validate and Normalize
  -> Store Raw Artifact in MinIO
  -> Store Structured Data in MySQL
  -> Update Module and Job Status
  -> Release Lease
```

每个平台都必须通过同一条链路。新增站点只能新增 Adapter 和 fixture，不能复制 Worker、API、任务状态机或 Repository。

## Adapter 输出

Adapter 必须输出标准化模型：

- `ResolvedTarget`；
- `DiscoveredTarget`；
- `MetricResult`；
- `NormalizedComment`；
- `TimedTextStreamDescriptor`；
- `NormalizedTimedText`；
- `AuthVerificationResult`。

平台特有信息只能进入：

- 命名空间指标键；
- `platform_ids`；
- `attributes`；
- `extra`。

## 任务规则

- `pending` 任务由单 Worker 领取；
- Worker 主进程只负责调度和监督；
- 任务子进程负责 Crawl4AI 和当前采集；
- API 取消将任务设为 `cancelling`；
- Worker 强制杀死任务进程组；
- 完整提交的数据保留；
- 手动 `resume` 只补未完成模块；
- 没有自动无限重试；
- 没有后台周期采集。

## 默认策略与边界

| 参数 | 默认值 | 边界 |
|---|---:|---:|
| `video_limit` | 100 | 1–500 |
| `max_root_comments` | 1000 | 0–100000 |
| `fetch_all_replies` | true | boolean |
| `fetch_all_danmaku` | true | boolean |
| `fetch_all_subtitles` | true | boolean |
| `timed_text_batch_size` | 1000 | 100–5000 |
| `max_retries` | 3 | 0–5 |
| `video_delay_min_seconds` | 1.0 | >=0.5 |
| `video_delay_max_seconds` | 3.0 | >= min |
| `comment_page_delay_min_seconds` | 0.8 | >=0.5 |
| `comment_page_delay_max_seconds` | 1.5 | >= min |
| `request_timeout_seconds` | 30 | 5–120 |
| `page_timeout_seconds` | 60 | 10–300 |
| `task_terminate_grace_seconds` | 5 | 1–30 |
| `raw_artifact_retention_days` | 30 | 0–3650 |

## 数据状态

指标状态只允许：

- `available`；
- `unsupported`；
- `not_public`；
- `fetch_failed`。

任务状态只允许：

- `pending`；
- `running`；
- `partial`；
- `success`；
- `failed`；
- `cancelling`；
- `cancelled`。

Profile 状态只允许：

- `active`；
- `expired`；
- `disabled`。

Raw Artifact 状态只允许：

- `uploading`；
- `available`；
- `missing`；
- `expired`；
- `delete_failed`。

## 数据库规则

- 迁移是唯一 schema 来源；
- `sql/reference_schema.sql` 仅用于审阅，不得替代 Alembic；
- 所有时间写 UTC；
- 所有外键显式定义；
- 删除 Profile 不级联删除历史任务和结果；
- 删除视频不作为首版 API；
- 评论树通过平台 ID 入库后再解析内部父子 ID；
- 时间文本以 `stream_id + dedup_key` 唯一；
- 评论以 `video_id + platform_comment_id` 唯一；
- 指标快照不可覆盖历史快照。

## 安全规则

- 不记录 Cookie；
- 不返回 Cookie；
- 不把 Cookie 存入 MySQL；
- API 容器不挂载 Profile；
- MinIO Bucket 不公开；
- 只生成短时预签名 URL；
- 禁止路径穿越；
- 禁止把真实响应 fixture 提交到公开仓库，除非已脱敏且获得授权；
- 不实现反验证码、反风控、访问控制绕过。
