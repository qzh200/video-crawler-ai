# 通用视频网站数据采集服务

`video-crawler` 0.1.0 是一个无前端、无用户体系的视频网站数据采集服务。FastAPI 接收人工创建的采集任务，单个常驻 Worker 在独立进程组中运行每个任务，结构化结果写入 MySQL，原始响应写入 MinIO。Bilibili 是首个 Adapter；Core、Domain、API、Worker 与 Repository 保持站点无关。

## 采集范围

服务只采集互动指标、评论与回复、弹幕和字幕。它不采集标题、简介、封面、UP 主资料、视频或音频，不提供定时调度、多 Worker、用户体系、验证码/DRM/付费墙或访问控制绕过。

## 架构与运行约束

```text
Client -> FastAPI -> MySQL
                    ^
Single Worker -> isolated task process group
              -> Crawl4AI + persistent Chromium Profile
              -> Adapter -> MySQL + MinIO
```

- API 不挂载浏览器 Profile，也不运行 Crawl4AI。
- Worker 和每个 Profile 的并发固定为 1。
- 取消任务时先终止整个任务进程组；已提交的 MySQL 数据和完整 MinIO 对象保留。
- 手动续跑沿用逻辑任务，只创建新的 run，并跳过已成功模块。
- CI 只使用 mock gateway 和脱敏 fixture，不访问实时站点。

## 快速开始

需要 Docker Desktop（Compose v2）。先创建本地配置并替换所有示例密钥：

```powershell
Copy-Item .env.example .env
docker compose config --quiet
docker compose build
docker compose up -d mysql minio minio-init migrate api worker
docker compose ps
Invoke-WebRequest http://localhost:8000/health/ready -UseBasicParsing
```

手动执行迁移：

```powershell
docker compose run --rm migrate alembic upgrade head
```

开发环境安装与质量检查：

```powershell
uv sync --extra dev
uv run ruff format --check src tests
uv run ruff check src tests
uv run mypy src
uv run pytest --cov=video_crawler --cov-report=term-missing
```

## 登录并注册 Profile

先启动操作者选择的 X Server，再在容器中打开持久化 Chromium Profile；浏览器中的登录必须由操作者手动完成：

```powershell
docker compose run --rm -e DISPLAY=host.docker.internal:0 profile-login login --platform bilibili --profile bilibili-main
```

注册并验证同一个 Profile 目录：

```powershell
$headers = @{ 'X-API-Key' = '<your-api-key>' }
$profileBody = @{
  platform = 'bilibili'
  profile_name = 'bilibili-main'
  profile_directory = 'bilibili-main'
} | ConvertTo-Json
$profile = Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/v1/auth-profiles -Headers $headers -ContentType 'application/json' -Body $profileBody
$profileId = $profile.profile_id
$verification = Invoke-RestMethod -Method Post -Uri "http://localhost:8000/api/v1/auth-profiles/$profileId/verify" -Headers $headers
$verificationId = $verification.verification_id
$deadline = (Get-Date).AddMinutes(3)
do {
  Start-Sleep -Seconds 2
  $verification = Invoke-RestMethod -Uri "http://localhost:8000/api/v1/auth-profiles/$profileId/verifications/$verificationId" -Headers $headers
} while ($verification.status -in @('pending', 'running') -and (Get-Date) -lt $deadline)
if ($verification.status -ne 'succeeded' -or $verification.profile_status -ne 'active') {
  throw "Profile verification failed: request=$($verification.status), profile=$($verification.profile_status)"
}
```

验证接口返回 HTTP 202，由唯一 Worker 在挂载 Profile 的独立子进程中完成；API 不挂载
Profile，也不运行 Crawl4AI。服务不接收 Cookie JSON，也不会把 Cookie、Local Storage 或
登录令牌写入 MySQL。

## 创建、取消和续跑任务

```powershell
$jobBody = @{
  source_url = 'https://www.bilibili.com/v/popular/all'
  auth_profile_id = $profileId
  video_limit = 100
} | ConvertTo-Json
$job = Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/v1/crawl-jobs -Headers ($headers + @{ 'Idempotency-Key' = 'manual-001' }) -ContentType 'application/json' -Body $jobBody
$jobId = $job.job_id
Invoke-RestMethod -Uri "http://localhost:8000/api/v1/crawl-jobs/$jobId" -Headers $headers
Invoke-RestMethod -Method Post -Uri "http://localhost:8000/api/v1/crawl-jobs/$jobId/cancel" -Headers $headers
Invoke-RestMethod -Method Post -Uri "http://localhost:8000/api/v1/crawl-jobs/$jobId/resume" -Headers $headers -ContentType 'application/json' -Body '{}'
```

`Idempotency-Key` 在 24 小时内对相同请求返回原任务；同一键对应不同请求时返回冲突。

## 查询结果

将任务结果中的 `video_id` 或 `unit_id` 代入以下命令。评论与时间文本使用响应中的 `next_cursor` 继续 keyset 分页，`page_size` 默认 100、最大 1000。

```powershell
Invoke-RestMethod -Uri "http://localhost:8000/api/v1/videos/$videoId/metrics?page_size=100" -Headers $headers
Invoke-RestMethod -Uri "http://localhost:8000/api/v1/videos/$videoId/metrics/latest" -Headers $headers
Invoke-RestMethod -Uri "http://localhost:8000/api/v1/videos/$videoId/comments?page_size=100" -Headers $headers
Invoke-RestMethod -Uri "http://localhost:8000/api/v1/video-units/$unitId/timed-text?page_size=100" -Headers $headers
```

## API 路径

```text
POST /api/v1/crawl-jobs
GET  /api/v1/crawl-jobs/{job_id}
POST /api/v1/crawl-jobs/{job_id}/cancel
POST /api/v1/crawl-jobs/{job_id}/resume

POST /api/v1/auth-profiles
GET  /api/v1/auth-profiles
GET  /api/v1/auth-profiles/{profile_id}
POST /api/v1/auth-profiles/{profile_id}/verify
GET  /api/v1/auth-profiles/{profile_id}/verifications/{verification_id}
POST /api/v1/auth-profiles/{profile_id}/enable
POST /api/v1/auth-profiles/{profile_id}/disable

GET /api/v1/videos/{video_id}/metrics
GET /api/v1/videos/{video_id}/metrics/latest
GET /api/v1/videos/{video_id}/comments
GET /api/v1/video-units/{unit_id}/timed-text

GET /health/live
GET /health/ready
```

完整请求/响应语义见 `docs/api-contract.md`。实际测试 Bilibili 热门页 `https://www.bilibili.com/v/popular/all` 的发现、子任务采集和结果验收时，按 `docs/manual-test-runbook.md` 执行；部署、Profile 登录、备份、恢复、取消与排障命令见 `docs/operations.md`；数据库表与唯一约束见 `docs/architecture/database-schema.md`。

## 数据保留与安全

- 原始对象默认保留 30 天；`RAW_ARTIFACT_RETENTION_DAYS=0` 表示永久保留。
- 清理只删除 MinIO 原始对象，不删除 MySQL 结构化结果。
- `.env`、浏览器 Profile、真实站点响应、Cookie 和账号数据不得提交到 Git。
- 不要使用 `docker compose down -v` 进行普通重启；`-v` 会删除数据库、对象和 Profile volumes。
