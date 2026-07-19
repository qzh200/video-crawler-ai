# 通用视频网站采集服务设计规格

日期：2026-07-19

## 1. 目标

构建一个无前端、无用户体系的 API 服务。调用方通过 FastAPI 手动提交视频网站 URL 和浏览器 Profile 引用。单个 Worker 使用 Crawl4AI 采集指定范围的数据，结构化结果存入 MySQL，原始响应存入 MinIO。

首个站点适配器为 Bilibili，首个列表入口为综合热门页。系统必须保证后续增加其他平台时，只新增 Adapter，不复制或修改通用底层链路。

## 2. 范围

### 2.1 采集数据

- 标准指标：播放、点赞、收藏、分享、评论总数、时间评论总数；
- 平台指标：例如 `bilibili.coins`；
- 评论和回复；
- 弹幕和字幕。

### 2.2 非目标

- 前端；
- 用户和权限模型；
- 定时调度；
- 多 Worker；
- 视频、音频下载；
- 额外元数据；
- AI 分析；
- 访问控制或风控绕过。

## 3. 架构

### 3.1 API

FastAPI 只做：

- 请求验证；
- API Key 验证；
- 创建逻辑任务；
- 幂等请求处理；
- 查询任务；
- 设置取消请求；
- 手动续跑；
- 查询指标、评论、弹幕和字幕；
- 生成原始对象短期预签名 URL。

API 不运行 Crawl4AI，不挂载 Profile，不直接执行长任务。

### 3.2 Worker

常驻 Worker：

- 每次只领取一个任务；
- 使用 MySQL `FOR UPDATE SKIP LOCKED` 领取任务；
- 获取 Profile 租约；
- 创建独立任务子进程和进程组；
- 监督心跳、取消和退出码；
- 负责最终任务状态转换；
- 回收过期任务和 Profile 租约；
- 定期执行 MinIO 原始对象清理。

任务子进程：

- 创建 Crawl4AI 浏览器；
- 根据 URL 从注册表选择 Adapter；
- 执行统一采集管线；
- 分模块提交结果；
- 周期检查取消令牌；
- 退出时关闭浏览器和数据库连接。

### 3.3 Adapter

Adapter 是唯一允许理解站点协议的模块。统一接口详见 `docs/architecture/adapter-contract.md`。

### 3.4 存储

MySQL 保存：

- 平台；
- Profile 引用；
- 视频和内容单元定位；
- 指标定义、快照和值；
- 评论；
- 时间文本流和条目；
- 任务、运行、模块状态和租约；
- 原始对象元数据；
- 幂等请求记录。

MinIO 保存：

- 指标原始响应；
- 评论分页响应；
- 弹幕原始二进制/XML/JSON；
- 字幕原始 JSON/VTT/SRT；
- 网络捕获诊断；
- 解析失败材料。

## 4. 通用数据模型

### 4.1 视频目标

`videos` 只保存定位字段：平台、平台视频 ID、标准 URL、平台 ID JSON 和时间戳。

`video_units` 表示分 P、章节或平台内容单元。时间文本挂到内容单元，不直接挂到视频。

### 4.2 指标

指标由命名空间键表示：

```text
standard.views
standard.likes
standard.favorites
standard.shares
standard.comments
standard.timed_comments
bilibili.coins
```

值必须带状态，不能把不支持或不可见写成零。

### 4.3 评论

评论使用 `platform_comment_id`、`root_platform_comment_id` 和 `parent_platform_comment_id` 进入标准模型。Repository 在 Upsert 后解析内部 `root_comment_id` 和 `parent_comment_id`。

### 4.4 时间文本

弹幕和字幕共用两层模型：

- `timed_text_streams`：弹幕流或字幕轨道；
- `timed_text_items`：具体时间轴条目。

通过 `content_type=danmaku|subtitle` 区分。

## 5. 列表任务和视频任务

输入 URL 可解析为：

- `single_video`；
- `video_list`。

列表任务仅发现标准视频目标并创建带 `video_id` 的子任务。子任务逐个执行指标、评论和时间文本模块。父任务根据子任务汇总为 `success`、`partial`、`failed` 或 `cancelled`。

## 6. 失败和续跑

模块状态独立保存：

- `metrics`；
- `comments`；
- `timed_text`。

任一模块失败不回滚其他模块。手动续跑读取模块状态，只重跑非成功模块。续跑可覆盖策略，系统合并并验证后保存完整策略快照。

## 7. 强制取消

API 只设置取消标志。Worker 监督进程发现标志后：

1. 将任务转为 `cancelling`；
2. 向进程组发送 SIGTERM；
3. 等待宽限期；
4. 仍未退出则 SIGKILL；
5. 回滚未提交事务；
6. 标记当前模块 `cancelled`；
7. 回收租约和临时对象；
8. 任务转为 `cancelled`。

## 8. 登录 Profile

首版只支持持久化 Chromium Profile：

- Profile 通过 Docker Volume 挂到 Worker；
- API 只保存安全相对目录名；
- API 不挂载 Profile；
- MySQL 不保存 Cookie；
- Adapter 提供 `verify_auth`；
- 失效 Profile 标记为 `expired`；
- 用户在外部或专用 login 命令中重新登录后，再调用 verify 和 resume。

## 9. 查询

评论游标：`published_at + id`。

时间文本游标：`start_ms + id`。

指标按 `captured_at DESC`。

默认页大小 100，最大 1000，不做深 OFFSET。

## 10. 运维

Docker Compose 包含 MySQL、MinIO、MinIO 初始化、Alembic 迁移、API 和 Worker。MySQL 与 MinIO 数据使用 Volume。Worker 使用 `init: true` 回收孤儿进程。

原始对象默认保留 30 天。结构化数据永久保留。
