# 0.1.0 实际系统测试操作手册

本文档用于在 Windows PowerShell 中对 0.1.0 做一次真实、可留证的系统测试。测试使用操作者自己的 Bilibili 登录态，只访问正常可见数据，不绕过验证码、风控、付费墙或访问控制。

默认使用独立 Compose 项目 `video-crawler-manual-test`，避免复用其他环境的 MySQL、MinIO 和浏览器 Profile 数据卷。所有命令都在同一个 PowerShell 窗口中执行。

## 1. 测试范围

本手册验证：

- Compose 配置、构建、迁移和健康检查；
- 持久化 Chromium Profile 的手动登录、注册与验证；
- 热门列表发现和子任务执行；
- 指标、评论、弹幕和字幕的结构化结果；
- MinIO 原始对象元数据；
- 幂等创建、取消和手动续跑；
- API Key 与日志脱敏；
- 服务停止、数据保留和测试环境清理。

实时站点行为可能受登录状态、地区、内容可见性和上游接口变化影响。遇到验证码、风控或拒绝访问时应停止测试并记录现象，不做规避。

## 2. 建立隔离测试上下文

打开 PowerShell，执行：

```powershell
Set-Location 'C:\Users\Administrator\Documents\video-crawler-ai'
$env:COMPOSE_PROJECT_NAME = 'video-crawler-manual-test'

docker version
docker compose version
git status --short
```

成功信号：Docker 客户端和服务端均可访问，Compose 为 v2，仓库状态符合预期。

确认 API 和 MinIO Console 端口没有被其他程序占用：

```powershell
Get-NetTCPConnection -State Listen -LocalPort 8000,9001 -ErrorAction SilentlyContinue
```

无输出表示端口空闲。如果有输出，先停止占用端口的既有测试服务；不要为了本测试删除未知数据卷。

## 3. 初始化测试配置

仅在 `.env` 不存在时复制示例：

```powershell
if (-not (Test-Path .env)) {
    Copy-Item .env.example .env
}
notepad .env
```

如果已有 `.env` 属于其他运行环境，不要直接改写；请改用独立 checkout，或先由环境负责人确认可复用。Compose 服务固定读取仓库根目录的 `.env`。

至少把以下四项改成新的测试值，不要继续使用 `change-me`：

```text
API_KEY=<new-test-api-key>
MYSQL_PASSWORD=<new-test-mysql-password>
MYSQL_ROOT_PASSWORD=<new-test-root-password>
MINIO_SECRET_KEY=<new-test-minio-password>
```

注意：MySQL 和 MinIO 首次初始化后，单纯修改 `.env` 不会修改已有数据卷内的凭据。如果出现 MySQL `1045 Access denied`，先确认当前 `COMPOSE_PROJECT_NAME` 是否正确；不要对未知或需保留的数据卷执行 `down -v`。

验证 Compose 插值：

```powershell
docker compose config --quiet
if ($LASTEXITCODE -ne 0) { throw 'Compose configuration is invalid' }
```

成功信号：退出码为 0，且没有“变量未设置”警告。

## 4. 构建并启动基础服务

首次构建会下载 Python 依赖和 Chromium，可能耗时较长：

```powershell
docker compose build
if ($LASTEXITCODE -ne 0) { throw 'Image build failed' }

docker compose up -d mysql minio minio-init migrate api
docker compose ps -a
```

等待 readiness：

```powershell
$ready = $false
for ($attempt = 1; $attempt -le 60; $attempt++) {
    try {
        $response = Invoke-WebRequest http://localhost:8000/health/ready -UseBasicParsing -TimeoutSec 5
        if ($response.StatusCode -eq 200) {
            $ready = $true
            break
        }
    } catch {
        Start-Sleep -Seconds 2
    }
}
if (-not $ready) {
    docker compose ps -a
    docker compose logs --tail 200 migrate api mysql minio minio-init
    throw 'Readiness did not become healthy'
}
```

成功信号：

- `mysql` 和 `minio` 为 healthy；
- `migrate` 和 `minio-init` 退出码为 0；
- `api` 持续运行；
- `/health/ready` 返回 HTTP 200。

## 5. 登录浏览器 Profile

Worker 暂时不要启动。先启动本机 X Server，并允许 Docker Desktop 通过 `host.docker.internal` 连接。然后执行：

```powershell
docker compose run --rm -e DISPLAY=host.docker.internal:0 profile-login login --platform bilibili --profile bilibili-main
```

浏览器打开后，由操作者手动完成正常登录，确认网页处于已登录状态，再回到终端按 Enter。

成功信号：命令退出码为 0，`browser_profiles` 数据卷保留 Profile。不要在 Worker 正使用该 Profile 时重复运行登录命令。

如果容器显示方案不可用，可按 `docs/operations.md` 的“本机交互登录”步骤操作；不得通过 API 上传 Cookie。

## 6. 注册并验证 Profile

安全地输入 `.env` 中自己设置的 API Key：

```powershell
$secureApiKey = Read-Host 'Enter API_KEY from .env' -AsSecureString
$apiKey = [System.Net.NetworkCredential]::new('', $secureApiKey).Password
$headers = @{ 'X-API-Key' = $apiKey }
```

先复用已注册的同名 Profile；不存在时再创建：

```powershell
$profiles = @(Invoke-RestMethod -Method Get -Uri http://localhost:8000/api/v1/auth-profiles -Headers $headers)
$profile = $profiles |
    Where-Object { $_.platform -eq 'bilibili' -and $_.profile_directory -eq 'bilibili-main' } |
    Select-Object -First 1

if ($null -eq $profile) {
    $profileBody = @{
        platform = 'bilibili'
        profile_name = 'bilibili-main'
        profile_directory = 'bilibili-main'
    } | ConvertTo-Json
    $profile = Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/v1/auth-profiles -Headers $headers -ContentType 'application/json' -Body $profileBody
}

$profileId = $profile.profile_id
$verifiedProfile = Invoke-RestMethod -Method Post -Uri "http://localhost:8000/api/v1/auth-profiles/$profileId/verify" -Headers $headers
$verifiedProfile | ConvertTo-Json -Depth 10

if ($verifiedProfile.status -ne 'active') {
    throw "Profile verification failed with status $($verifiedProfile.status)"
}
```

成功信号：Profile 响应不包含 Cookie 或文件内容，`status` 为 `active`。

## 7. 启动单 Worker

```powershell
docker compose up -d worker
docker compose ps worker
docker compose logs --tail 100 worker
```

成功信号：只有一个 `worker` 服务实例持续运行，没有启动错误。不要使用 `--scale worker=2`。

## 8. 创建最小真实采集任务

先定义轮询函数：

```powershell
function Wait-CrawlJob {
    param(
        [Parameter(Mandatory)] [string] $JobId,
        [int] $TimeoutSeconds = 900
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        $record = Invoke-RestMethod -Method Get -Uri "http://localhost:8000/api/v1/crawl-jobs/$JobId" -Headers $headers
        Write-Host "$(Get-Date -Format s) job=$JobId status=$($record.status) modules=$($record.module_states | ConvertTo-Json -Compress)"
        if ($record.status -in @('success','partial','failed','cancelled')) {
            return $record
        }
        Start-Sleep -Seconds 5
    } while ((Get-Date) -lt $deadline)

    throw "Timed out waiting for job $JobId"
}
```

使用 1 个视频、5 条一级评论的烟雾策略，避免第一次测试范围过大：

```powershell
$idempotencyKey = "manual-smoke-$(Get-Date -Format yyyyMMddHHmmss)"
$jobBody = @{
    source_url = 'https://www.bilibili.com/v/popular/all'
    auth_profile_id = $profileId
    video_limit = 1
    strategy = @{
        max_root_comments = 5
        fetch_all_replies = $false
        fetch_all_danmaku = $true
        fetch_all_subtitles = $true
        timed_text_batch_size = 1000
        max_retries = 2
        video_delay_min_seconds = 1.0
        video_delay_max_seconds = 1.5
        comment_page_delay_min_seconds = 0.8
        comment_page_delay_max_seconds = 1.0
        request_timeout_seconds = 30
        page_timeout_seconds = 60
    }
} | ConvertTo-Json -Depth 10

$createHeaders = $headers + @{ 'Idempotency-Key' = $idempotencyKey }
$job = Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/v1/crawl-jobs -Headers $createHeaders -ContentType 'application/json' -Body $jobBody
$jobId = $job.job_id
$job | ConvertTo-Json -Depth 10
```

热门页任务是列表父任务。先等待父任务完成发现：

```powershell
$parentResult = Wait-CrawlJob -JobId $jobId
$parentResult | ConvertTo-Json -Depth 10
```

成功信号：父任务通常为 `success`，并创建一个视频子任务。`partial` 或 `failed` 时先查看第 15 节。

## 9. 定位并等待视频子任务

0.1.0 的任务响应尚不直接暴露数据库 `video_id` 和子任务列表，因此实际测试需做只读 MySQL 查询。定义安全的只读 SQL 辅助函数；SQL 通过标准输入传给容器，数据库密码不回显到宿主命令行：

```powershell
function Invoke-CrawlerSql {
    param([Parameter(Mandatory)] [string] $Sql)

    $result = $Sql | docker compose exec -T mysql sh -c 'exec mysql --batch --raw --skip-column-names -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE"'
    if ($LASTEXITCODE -ne 0) { throw 'MySQL query failed' }
    return $result
}
```

查询父任务创建的直接子任务：

```powershell
$childRows = @(Invoke-CrawlerSql @"
SELECT BIN_TO_UUID(id), video_id, status
FROM crawl_jobs
WHERE parent_job_id = UUID_TO_BIN('$jobId')
ORDER BY created_at ASC;
"@)

$childJobs = @($childRows | Where-Object { $_.Trim() } | ForEach-Object {
    $columns = $_ -split "`t"
    [pscustomobject]@{
        JobId = $columns[0]
        VideoId = [int64]$columns[1]
        InitialStatus = $columns[2]
    }
})

if ($childJobs.Count -eq 0) { throw 'No child video jobs were discovered' }
$childJobs | Format-Table
```

等待所有子任务进入终态，并选择一个有结构化结果的子任务：

```powershell
$completedChildren = @($childJobs | ForEach-Object {
    $childResult = Wait-CrawlJob -JobId $_.JobId -TimeoutSeconds 1800
    [pscustomobject]@{
        JobId = $_.JobId
        VideoId = $_.VideoId
        Status = $childResult.status
        ModuleStates = $childResult.module_states
    }
})

$completedChildren | Format-List
$selected = $completedChildren | Where-Object { $_.Status -in @('success','partial') } | Select-Object -First 1
if ($null -eq $selected) { throw 'No child job produced queryable results' }
$videoId = $selected.VideoId
```

成功信号：子任务为 `success`，或在个别模块上为 `partial`；模块状态能说明 `metrics`、`comments`、`timed_text` 各自结果。

## 10. 验证指标和评论 API

```powershell
$latestMetrics = Invoke-RestMethod -Method Get -Uri "http://localhost:8000/api/v1/videos/$videoId/metrics/latest" -Headers $headers
$metricPage = Invoke-RestMethod -Method Get -Uri "http://localhost:8000/api/v1/videos/$videoId/metrics?page_size=10" -Headers $headers
$commentPage = Invoke-RestMethod -Method Get -Uri "http://localhost:8000/api/v1/videos/$videoId/comments?page_size=10&order=asc" -Headers $headers

$latestMetrics | ConvertTo-Json -Depth 10
$metricPage | ConvertTo-Json -Depth 10
$commentPage | ConvertTo-Json -Depth 10
```

检查点：

- 指标键只包含批准的 `standard.*` 和 Adapter 命名空间键；
- 缺失指标使用 `unsupported`、`not_public` 或 `fetch_failed`，不能伪造为 0；
- 评论包含平台评论 ID、文本、作者展示字段、点赞/回复数和父子关系字段；
- 分页响应有 `next_cursor` 时，可带回下一请求，页面之间不应重复或遗漏。

游标示例：

```powershell
if ($commentPage.next_cursor) {
    $escapedCursor = [uri]::EscapeDataString($commentPage.next_cursor)
    $nextComments = Invoke-RestMethod -Method Get -Uri "http://localhost:8000/api/v1/videos/$videoId/comments?page_size=10&order=asc&cursor=$escapedCursor" -Headers $headers
    $nextComments | ConvertTo-Json -Depth 10
}
```

## 11. 验证弹幕和字幕 API

先取得内容单元 ID：

```powershell
$unitRows = @(Invoke-CrawlerSql "SELECT id, platform_unit_id FROM video_units WHERE video_id = $videoId ORDER BY id ASC;")
if ($unitRows.Count -eq 0) { throw 'No video units were persisted' }

$unitColumns = $unitRows[0] -split "`t"
$unitId = [int64]$unitColumns[0]
$platformUnitId = $unitColumns[1]
Write-Host "unitId=$unitId platformUnitId=$platformUnitId"
```

查询弹幕与字幕：

```powershell
$danmakuPage = Invoke-RestMethod -Method Get -Uri "http://localhost:8000/api/v1/video-units/$unitId/timed-text?content_type=danmaku&page_size=10" -Headers $headers
$subtitlePage = Invoke-RestMethod -Method Get -Uri "http://localhost:8000/api/v1/video-units/$unitId/timed-text?content_type=subtitle&page_size=10" -Headers $headers

$danmakuPage | ConvertTo-Json -Depth 10
$subtitlePage | ConvertTo-Json -Depth 10
```

检查点：

- 弹幕和字幕都通过统一 timed-text API 返回；
- `content_type` 正确区分 `danmaku` 与 `subtitle`；
- `start_ms` 非负，字幕存在时 `end_ms >= start_ms`；
- 同一 `stream_id + dedup_key` 不产生重复条目；
- 无字幕可能是内容本身没有可访问字幕，不应自动判定为系统失败。

## 12. 验证数据库计数和原始对象

执行只读汇总：

```powershell
Invoke-CrawlerSql @"
SELECT 'metric_snapshots', COUNT(*) FROM metric_snapshots WHERE video_id = $videoId
UNION ALL
SELECT 'comments', COUNT(*) FROM comments WHERE video_id = $videoId
UNION ALL
SELECT 'timed_text_items', COUNT(*)
FROM timed_text_items i
JOIN timed_text_streams s ON s.id = i.stream_id
JOIN video_units u ON u.id = s.video_unit_id
WHERE u.video_id = $videoId
UNION ALL
SELECT 'available_raw_artifacts', COUNT(*)
FROM raw_artifacts
WHERE video_id = $videoId AND storage_status = 'available';
"@
```

查看原始对象元数据，不输出对象正文：

```powershell
Invoke-CrawlerSql @"
SELECT bucket, object_key, artifact_type, sha256, etag, size_bytes, storage_status
FROM raw_artifacts
WHERE video_id = $videoId
ORDER BY captured_at ASC;
"@
```

成功信号：成功模块有对应结构化行；正式原始对象为 `available`，同时有非空 bucket、object key、SHA-256、大小和 ETag。数据库不保存预签名 URL。

## 13. 验证创建幂等性

使用同一个 `Idempotency-Key` 和同一个请求体再次创建：

```powershell
$sameJob = Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/v1/crawl-jobs -Headers $createHeaders -ContentType 'application/json' -Body $jobBody
if ($sameJob.job_id -ne $jobId) { throw 'Idempotent replay returned a different job' }
Write-Host "Idempotent replay returned original job $jobId"
```

同一个 key 改变请求应返回 409：

```powershell
$conflictBody = @{
    source_url = 'https://www.bilibili.com/v/popular/all'
    auth_profile_id = $profileId
    video_limit = 2
} | ConvertTo-Json

try {
    Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/v1/crawl-jobs -Headers $createHeaders -ContentType 'application/json' -Body $conflictBody
    throw 'Expected IDEMPOTENCY_CONFLICT but request succeeded'
} catch {
    $statusCode = [int]$_.Exception.Response.StatusCode
    if ($statusCode -ne 409) { throw }
    Write-Host 'Received expected HTTP 409 IDEMPOTENCY_CONFLICT'
}
```

## 14. 验证 pending 取消和手动续跑

该步骤会创建测试任务。先停止 Worker，确保任务保持 `pending`：

```powershell
docker compose stop worker

$cancelKey = "manual-cancel-$(Get-Date -Format yyyyMMddHHmmss)"
$cancelHeaders = $headers + @{ 'Idempotency-Key' = $cancelKey }
$cancelJob = Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/v1/crawl-jobs -Headers $cancelHeaders -ContentType 'application/json' -Body $jobBody
$cancelJobId = $cancelJob.job_id

$cancelled = Invoke-RestMethod -Method Post -Uri "http://localhost:8000/api/v1/crawl-jobs/$cancelJobId/cancel" -Headers $headers
if ($cancelled.status -ne 'cancelled') { throw "Expected cancelled, got $($cancelled.status)" }

$resumed = Invoke-RestMethod -Method Post -Uri "http://localhost:8000/api/v1/crawl-jobs/$cancelJobId/resume" -Headers $headers -ContentType 'application/json' -Body '{}'
if ($resumed.status -ne 'pending') { throw "Expected pending after resume, got $($resumed.status)" }

$cancelledAgain = Invoke-RestMethod -Method Post -Uri "http://localhost:8000/api/v1/crawl-jobs/$cancelJobId/cancel" -Headers $headers
if ($cancelledAgain.status -ne 'cancelled') { throw 'Second cancellation failed' }

docker compose start worker
```

成功信号：pending 任务可直接取消；只有 `partial`、`failed`、`cancelled` 可续跑；续跑保持逻辑 job ID 不变并恢复为 `pending`。

运行中进程组取消属于更具破坏性的可选测试：只在隔离测试项目内创建一个预计运行较久的子任务，确认状态为 `running` 后调用 cancel，并检查 Worker 日志与 `docker compose top worker`。最终必须为 `cancelled`，且不应遗留 Chromium 子进程。

## 15. 日志与脱敏检查

```powershell
$logs = docker compose logs --no-color --since 60m api worker

if ($logs -match [regex]::Escape($apiKey)) {
    throw 'API key value appeared in logs'
}
if ($logs -match 'session=nested-cookie|test-secret') {
    throw 'A known sensitive test value appeared in logs'
}

Write-Host 'No supplied API key value was found in API/Worker logs'
```

人工检查日志只能包含 request/job/run/video/module、脱敏错误、HTTP host/path/status 等允许字段，不得包含 Cookie、Authorization 值、完整敏感请求头、Profile 文件内容或真实 `.env` 值。

常用排障命令：

```powershell
docker compose ps -a
docker compose logs --tail 300 migrate api worker mysql minio minio-init
docker compose top worker
```

常见判断：

- `401 UNAUTHORIZED`：API Key 缺失或不一致；
- `PROFILE_EXPIRED` 或验证结果非 active：重新手工登录，再 verify；
- MySQL `1045`：`.env` 凭据与已有数据卷初始化凭据不一致；
- readiness 503：查看响应中的 MySQL、迁移 revision、MinIO、bucket 组件状态；
- `partial`：逐项查看 `module_states`，成功模块的数据应保留；
- 上游拒绝、验证码或风控：停止测试，不做绕过。

## 16. 可选：运行代码验收套件

该步骤会安装开发依赖并使用 Docker Testcontainers：

```powershell
uv sync --extra dev
uv run ruff format --check src tests
uv run ruff check src tests
uv run mypy src
uv run pytest --cov=video_crawler --cov-report=term-missing
```

0.1.0 Task 22 的参考成功信号是：格式、Ruff、mypy 全部通过；总覆盖率至少 85%；Windows 上 POSIX 进程组集成测试允许按平台条件跳过，其余测试不得失败。

## 17. 测试证据清单

建议保存以下非敏感证据：

- 当前 commit hash：`git rev-parse HEAD`；
- `docker compose config --quiet` 退出码；
- `docker compose ps -a` 状态；
- readiness JSON；
- Profile ID 与状态，不保存 Cookie/Profile 内容；
- 父任务、子任务 ID 和终态；
- 各模块状态与结果计数；
- 原始对象的 object key、大小、SHA-256/ETag，不保存预签名 URL；
- 幂等、取消、续跑的状态码和结果；
- 测试套件摘要与覆盖率；
- 失败时的脱敏日志片段。

禁止把 `.env`、真实 Cookie、账号信息、Profile、未脱敏响应或备份文件提交到 Git。

## 18. 停止或销毁测试环境

只停止容器并保留数据库、MinIO 和 Profile 数据：

```powershell
docker compose down
```

再次启动：

```powershell
docker compose up -d mysql minio minio-init migrate api worker
```

只有确认测试数据不再需要时，才可删除本手册创建的隔离数据卷。下面操作不可恢复：

```powershell
if ($env:COMPOSE_PROJECT_NAME -ne 'video-crawler-manual-test') {
    throw "Refusing destructive cleanup for project $env:COMPOSE_PROJECT_NAME"
}

docker compose down --volumes --remove-orphans
Remove-Variable apiKey,secureApiKey -ErrorAction SilentlyContinue
Remove-Item Env:COMPOSE_PROJECT_NAME
```

成功信号：只删除 `video-crawler-manual-test` 项目的容器、网络和命名卷。不要对需要保留的数据环境执行 `down -v`。
