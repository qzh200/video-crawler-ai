# Bilibili 热门页全流程实际测试文档

本文档用于实际测试以下入口的完整采集链路：

```text
https://www.bilibili.com/v/popular/all
```

测试链路是：热门页父任务发现视频 → 为每个视频创建子任务 → 采集指标、评论、弹幕和字幕 → 写入 MySQL 与 MinIO → 通过 API 查询结构化结果。

所有命令均在 Windows PowerShell 中执行。测试只能使用操作者自己的正常登录态，不得绕过验证码、风控、付费墙或访问控制，也不得保存或提交 Cookie、Profile 内容和真实响应。

## 1. 测试模式与通过标准

首次测试推荐先执行“小规模全链路”，确认每个模块都能工作后，再执行默认数据量验收。

| 模式 | `video_limit` | 一级评论上限 | 全部回复 | 用途 |
| --- | ---: | ---: | --- | --- |
| 小规模全链路 | 3 | 20 | 否 | 快速验证所有处理环节 |
| 默认数据量验收 | 100 | 1000 | 是 | 按系统默认策略进行正式验收 |

这里的“小规模”只减少视频数和评论数，不跳过任何模块；指标、评论、全部可访问弹幕和全部可访问字幕仍会执行。

一次测试通过必须同时满足：

1. 父任务终态为 `success`，且 `module_states.discovery` 为 `success`；
2. 发现并创建的子任务数等于 `video_limit`；
3. 每个子任务终态为 `success`；
4. 每个子任务的 `metrics`、`comments`、`timed_text` 均为 `success`；
5. 指标快照可以通过 API 查询，指标使用 `standard.*` 或 `bilibili.*` 命名空间；
6. 评论、弹幕和字幕数据符合实际可访问情况，弹幕和字幕统一从 timed-text API 查询；
7. MySQL 有结构化记录，MinIO 原始对象元数据为 `available`；
8. 日志不包含 API Key、Cookie、Authorization 或 Profile 内容。

`partial` 表示系统正确保留了成功模块的数据，但本次“完整采集验收”仍判定为未通过，需要按第 12 节排障。

## 2. 建立隔离测试环境

进入仓库并设置独立 Compose 项目名：

```powershell
Set-Location 'C:\Users\Administrator\Documents\video-crawler-ai'
$env:COMPOSE_PROJECT_NAME = 'video-crawler-popular-e2e'

docker version
docker compose version
git rev-parse HEAD
git status --short
```

检查本机端口未被占用：

```powershell
$requiredPorts = 8000, 3306, 9000, 9001
$busyPorts = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
    Where-Object { $_.LocalPort -in $requiredPorts } |
    Select-Object -ExpandProperty LocalPort -Unique

if ($busyPorts) {
    throw "Ports already in use: $($busyPorts -join ', ')"
}
```

如果已有其他项目占用这些端口，请先停止对方或修改本测试项目的端口映射，不要复用其数据卷。

## 3. 配置并启动基础服务

仅当 `.env` 不存在时复制示例：

```powershell
if (-not (Test-Path '.env')) {
    Copy-Item '.env.example' '.env'
}
```

编辑 `.env`，至少确认 MySQL、MinIO、`API_KEY`、Profile 根目录与 Compose 配置有效。不要把真实密钥粘贴到本文档或提交到 Git。

```powershell
docker compose config --quiet
if ($LASTEXITCODE -ne 0) { throw 'Compose configuration is invalid' }

docker compose build
if ($LASTEXITCODE -ne 0) { throw 'Image build failed' }

docker compose up -d mysql minio minio-init migrate api
docker compose ps -a
```

等待 API 就绪：

```powershell
$ready = $false
for ($attempt = 1; $attempt -le 60; $attempt++) {
    try {
        $health = Invoke-RestMethod -Uri 'http://localhost:8000/health/ready'
        if ($health.status -eq 'ready') {
            $ready = $true
            $health | ConvertTo-Json -Depth 10
            break
        }
    }
    catch {
        Start-Sleep -Seconds 2
    }
}

if (-not $ready) {
    docker compose ps -a
    docker compose logs --tail 200 migrate api mysql minio minio-init
    throw 'API readiness did not become ready'
}
```

成功信号：`migrate` 正常退出，MySQL、MinIO 和 API 健康，readiness 返回 `status=ready`。

## 4. 准备 Bilibili 登录 Profile

首次测试需要手动登录。Worker 此时不要启动。

先启动本机 X Server，并允许 Docker Desktop 通过 `host.docker.internal` 连接，然后执行：

```powershell
docker compose run --rm -e DISPLAY=host.docker.internal:0 profile-login login --platform bilibili --profile bilibili-main
```

浏览器打开后，由操作者正常登录 Bilibili，确认网页显示已登录，再回到终端按 Enter。Profile 会保存在 `browser_profiles` 数据卷中。

如果容器显示方案不可用，按 [operations.md](operations.md) 的“本机交互登录”步骤操作。不要通过 API 上传 Cookie，也不要在 Worker 使用该 Profile 时再次登录。

## 5. 注册并验证 Profile

安全输入 `.env` 中配置的 API Key：

```powershell
$secureApiKey = Read-Host 'API key' -AsSecureString
$apiKey = [System.Net.NetworkCredential]::new('', $secureApiKey).Password
$headers = @{ 'X-API-Key' = $apiKey }
```

复用已注册的同名 Profile；不存在时创建：

```powershell
$profiles = @(Invoke-RestMethod -Method Get -Uri 'http://localhost:8000/api/v1/auth-profiles' -Headers $headers)
$profile = $profiles |
    Where-Object { $_.platform -eq 'bilibili' -and $_.profile_directory -eq 'bilibili-main' } |
    Select-Object -First 1

if ($null -eq $profile) {
    $profileBody = @{
        platform = 'bilibili'
        profile_name = 'bilibili-main'
        profile_directory = 'bilibili-main'
    } | ConvertTo-Json

    $profile = Invoke-RestMethod `
        -Method Post `
        -Uri 'http://localhost:8000/api/v1/auth-profiles' `
        -Headers $headers `
        -ContentType 'application/json' `
        -Body $profileBody
}

$profileId = $profile.profile_id
$verifiedProfile = Invoke-RestMethod `
    -Method Post `
    -Uri "http://localhost:8000/api/v1/auth-profiles/$profileId/verify" `
    -Headers $headers

$verifiedProfile | ConvertTo-Json -Depth 10
if ($verifiedProfile.status -ne 'active') {
    throw "Profile verification failed: $($verifiedProfile.status)"
}
```

成功信号：Profile 状态为 `active`，响应中没有 Cookie 或 Profile 文件内容。

## 6. 启动唯一 Worker

```powershell
docker compose up -d worker
docker compose ps worker
docker compose logs --tail 100 worker
```

成功信号：只有一个 `worker` 服务实例持续运行。禁止使用 `--scale worker=2`。

## 7. 定义测试辅助函数

定义任务轮询函数。父任务与子任务都使用该函数等待终态：

```powershell
function Wait-CrawlJob {
    param(
        [Parameter(Mandatory)] [string] $JobId,
        [int] $TimeoutSeconds = 7200
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        $job = Invoke-RestMethod `
            -Method Get `
            -Uri "http://localhost:8000/api/v1/crawl-jobs/$JobId" `
            -Headers $headers

        Write-Host "$(Get-Date -Format HH:mm:ss) job=$JobId status=$($job.status)"
        if ($job.status -in @('success', 'partial', 'failed', 'cancelled')) {
            return $job
        }

        Start-Sleep -Seconds 5
    } while ((Get-Date) -lt $deadline)

    throw "Timed out waiting for crawl job $JobId"
}
```

当前 API 不直接返回热门页生成的子任务列表，也不返回数据库内部 `video_id` 和 `unit_id`。因此验收需要只读查询 MySQL：

```powershell
function Invoke-CrawlerSql {
    param([Parameter(Mandatory)] [string] $Sql)

    $result = $Sql | docker compose exec -T mysql sh -c 'exec mysql --batch --raw --skip-column-names -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE"'
    if ($LASTEXITCODE -ne 0) { throw 'MySQL query failed' }
    return $result
}
```

密码由容器环境变量读取，不会写入宿主机命令历史。

## 8. 创建热门页全流程任务

### 8.1 首次推荐：3 个视频的小规模全链路

```powershell
$videoLimit = 3
$maxRootComments = 20
$fetchAllReplies = $false
```

### 8.2 正式验收：默认 100 个视频

完成小规模全链路后，如需按系统默认数据量验收，改用：

```powershell
$videoLimit = 100
$maxRootComments = 1000
$fetchAllReplies = $true
```

默认 100 视频会由单 Worker 串行处理，且会抓取所有可访问回复、弹幕和字幕，可能运行数小时。不要同时创建第二个正式任务。

### 8.3 提交任务

```powershell
$jobBody = @{
    source_url = 'https://www.bilibili.com/v/popular/all'
    auth_profile_id = $profileId
    video_limit = $videoLimit
    strategy = @{
        max_root_comments = $maxRootComments
        fetch_all_replies = $fetchAllReplies
        fetch_all_danmaku = $true
        fetch_all_subtitles = $true
        timed_text_batch_size = 1000
        max_retries = 3
        video_delay_min_seconds = 1.0
        video_delay_max_seconds = 3.0
        comment_page_delay_min_seconds = 0.8
        comment_page_delay_max_seconds = 1.5
        request_timeout_seconds = 30
        page_timeout_seconds = 60
    }
} | ConvertTo-Json -Depth 10

$createHeaders = $headers + @{
    'Idempotency-Key' = "popular-e2e-$(Get-Date -Format yyyyMMddHHmmss)"
}

$createdJob = Invoke-RestMethod `
    -Method Post `
    -Uri 'http://localhost:8000/api/v1/crawl-jobs' `
    -Headers $createHeaders `
    -ContentType 'application/json' `
    -Body $jobBody

$jobId = $createdJob.job_id
$createdJob | ConvertTo-Json -Depth 10
```

立即检查：

- `source_url` 必须是 `https://www.bilibili.com/v/popular/all`；
- `parent_job_id` 必须为 `null`；
- `root_job_id` 必须等于 `job_id`；
- `effective_strategy.video_limit` 必须等于 `$videoLimit`；
- 初始状态通常为 `pending` 或已经进入 `running`。

## 9. 验收父任务：热门页发现

```powershell
$parentResult = Wait-CrawlJob -JobId $jobId
$parentResult | ConvertTo-Json -Depth 10

if ($parentResult.status -ne 'success') {
    throw "Popular-page parent job failed: $($parentResult.status)"
}
if ($parentResult.module_states.discovery -ne 'success') {
    throw "Discovery module failed: $($parentResult.module_states.discovery)"
}
```

父任务 `success` 只说明热门页发现成功，不代表所有视频已经采集完毕。继续查询它创建的子任务：

```powershell
$childRows = @(Invoke-CrawlerSql @"
SELECT BIN_TO_UUID(id), video_id, status, source_url
FROM crawl_jobs
WHERE parent_job_id = UUID_TO_BIN('$jobId')
ORDER BY created_at ASC, id ASC;
"@)

$childJobs = @($childRows | ForEach-Object {
    $columns = $_ -split "`t", 4
    [pscustomobject]@{
        JobId = $columns[0]
        VideoId = [long]$columns[1]
        Status = $columns[2]
        SourceUrl = $columns[3]
    }
})

$childJobs | Format-Table -AutoSize
if ($childJobs.Count -ne $videoLimit) {
    throw "Expected $videoLimit child jobs, found $($childJobs.Count)"
}
```

验收点：子任务 URL 都应是发现到的 Bilibili 视频 URL；子任务数必须等于请求的 `$videoLimit`；同一个视频不应出现重复子任务。

## 10. 等待并验收所有视频子任务

单 Worker 会串行执行子任务，按顺序等待：

```powershell
$completedChildren = @($childJobs | ForEach-Object {
    $result = Wait-CrawlJob -JobId $_.JobId -TimeoutSeconds 7200
    [pscustomobject]@{
        JobId = $_.JobId
        VideoId = $_.VideoId
        Status = $result.status
        Metrics = $result.module_states.metrics
        Comments = $result.module_states.comments
        TimedText = $result.module_states.timed_text
        Error = if ($null -eq $result.error) { $null } else { $result.error | ConvertTo-Json -Compress -Depth 10 }
    }
})

$completedChildren | Format-Table -AutoSize

$failedChildren = @($completedChildren | Where-Object {
    $_.Status -ne 'success' -or
    $_.Metrics -ne 'success' -or
    $_.Comments -ne 'success' -or
    $_.TimedText -ne 'success'
})

if ($failedChildren.Count -gt 0) {
    $failedChildren | Format-Table -AutoSize
    throw "$($failedChildren.Count) video child job(s) did not complete the full flow"
}
```

再从数据库核对模块运行记录：

```powershell
Invoke-CrawlerSql @"
SELECT BIN_TO_UUID(j.id), j.video_id, j.status, mr.module_key, mr.status
FROM crawl_jobs j
JOIN crawl_runs r ON r.job_id = j.id
JOIN crawl_module_runs mr ON mr.crawl_run_id = r.id
WHERE j.parent_job_id = UUID_TO_BIN('$jobId')
ORDER BY j.created_at, r.attempt_no, mr.module_key;
"@
```

首次运行时，每个视频应有 `metrics`、`comments`、`timed_text` 三个模块，且均为 `success`。

## 11. 验收结构化结果与 MinIO 元数据

逐个视频查询指标、评论、内容单元、弹幕和字幕：

```powershell
$resultSummary = @()

foreach ($child in $childJobs) {
    $videoId = $child.VideoId

    $metrics = Invoke-RestMethod `
        -Method Get `
        -Uri "http://localhost:8000/api/v1/videos/$videoId/metrics/latest" `
        -Headers $headers

    $comments = Invoke-RestMethod `
        -Method Get `
        -Uri "http://localhost:8000/api/v1/videos/$videoId/comments?page_size=10&order=asc" `
        -Headers $headers

    $unitRows = @(Invoke-CrawlerSql "SELECT id, platform_unit_id FROM video_units WHERE video_id = $videoId ORDER BY id;")
    if ($unitRows.Count -eq 0) { throw "Video $videoId has no video_units" }

    $danmakuCount = 0
    $subtitleCount = 0
    foreach ($unitRow in $unitRows) {
        $unitColumns = $unitRow -split "`t", 2
        $unitId = [long]$unitColumns[0]

        $danmaku = Invoke-RestMethod `
            -Method Get `
            -Uri "http://localhost:8000/api/v1/video-units/$unitId/timed-text?content_type=danmaku&page_size=10" `
            -Headers $headers

        $subtitles = Invoke-RestMethod `
            -Method Get `
            -Uri "http://localhost:8000/api/v1/video-units/$unitId/timed-text?content_type=subtitle&page_size=10" `
            -Headers $headers

        $danmakuCount += @($danmaku.items).Count
        $subtitleCount += @($subtitles.items).Count
    }

    $resultSummary += [pscustomobject]@{
        VideoId = $videoId
        MetricKeys = @($metrics.metrics.PSObject.Properties).Count
        CommentSampleCount = @($comments.items).Count
        UnitCount = $unitRows.Count
        DanmakuSampleCount = $danmakuCount
        SubtitleSampleCount = $subtitleCount
    }
}

$resultSummary | Format-Table -AutoSize
```

人工检查：

- 指标 key 包括适用的 `standard.views`、`standard.likes`、`standard.favorites`、`standard.shares`、`standard.comments`、`standard.timed_comments` 和 `bilibili.coins`；
- 指标不可用时使用状态表达，不得伪造为 `0`；
- 评论包含父子关系、文本、作者平台标识、点赞数、回复数和发布时间等允许字段；
- timed-text 的 `content_type` 只能是 `danmaku` 或 `subtitle`，`start_ms >= 0`；
- 视频可能没有公开字幕，此时字幕数量为 0 是允许的；模块状态仍应为 `success`；
- API 仅返回结构化数据，不返回 MinIO 预签名 URL。

查询整次任务的数据库计数：

```powershell
Invoke-CrawlerSql @"
SELECT 'videos', COUNT(DISTINCT j.video_id)
FROM crawl_jobs j
WHERE j.parent_job_id = UUID_TO_BIN('$jobId')
UNION ALL
SELECT 'metric_snapshots', COUNT(*)
FROM metric_snapshots m
JOIN crawl_jobs j ON j.video_id = m.video_id
WHERE j.parent_job_id = UUID_TO_BIN('$jobId')
UNION ALL
SELECT 'comments', COUNT(*)
FROM comments c
JOIN crawl_jobs j ON j.video_id = c.video_id
WHERE j.parent_job_id = UUID_TO_BIN('$jobId')
UNION ALL
SELECT 'timed_text_items', COUNT(*)
FROM timed_text_items i
JOIN timed_text_streams s ON s.id = i.stream_id
JOIN video_units u ON u.id = s.video_unit_id
JOIN crawl_jobs j ON j.video_id = u.video_id
WHERE j.parent_job_id = UUID_TO_BIN('$jobId')
UNION ALL
SELECT 'available_raw_artifacts', COUNT(*)
FROM raw_artifacts a
JOIN crawl_jobs j ON j.video_id = a.video_id
WHERE j.parent_job_id = UUID_TO_BIN('$jobId')
  AND a.storage_status = 'available';
"@
```

抽查 MinIO 对象元数据：

```powershell
Invoke-CrawlerSql @"
SELECT a.bucket, a.object_key, a.artifact_type, a.sha256, a.etag, a.size_bytes, a.storage_status
FROM raw_artifacts a
JOIN crawl_jobs j ON j.video_id = a.video_id
WHERE j.parent_job_id = UUID_TO_BIN('$jobId')
ORDER BY a.id
LIMIT 50;
"@
```

成功信号：对象路径包含平台、日期、视频标识、运行 ID 和 artifact 类型；已完成对象为 `available`，并有 `sha256`、`etag` 和大小。

## 12. 失败与 partial 排障

先查看父子任务和模块状态：

```powershell
Invoke-CrawlerSql @"
SELECT BIN_TO_UUID(j.id), j.job_type, j.video_id, j.status, r.error_code, r.error_message
FROM crawl_jobs j
LEFT JOIN crawl_runs r
  ON r.job_id = j.id
 AND r.attempt_no = j.attempt_count
WHERE j.id = UUID_TO_BIN('$jobId') OR j.parent_job_id = UUID_TO_BIN('$jobId')
ORDER BY j.created_at;
"@

docker compose ps -a
docker compose logs --tail 500 worker api
docker compose top worker
```

常见判断：

- 父任务 `failed`：优先检查热门页是否能打开、Profile 是否 active、网络捕获和 DOM fallback 日志；
- 子任务 `partial`：检查是 `metrics`、`comments` 还是 `timed_text` 失败，已成功模块的数据应仍然存在；
- `PROFILE_EXPIRED`：停止 Worker，重新手工登录 Profile，再调用 verify；
- `401 UNAUTHORIZED`：PowerShell 中的 API Key 与 `.env` 不一致；
- readiness 503：检查 MySQL、迁移 revision、MinIO 和 bucket 状态；
- 评论为 0：先确认视频是否开放评论，再看 comments 模块与上游响应状态；
- 字幕为 0：视频可能没有可访问字幕，不单独视为失败；
- timed-text 失败：分别查看弹幕二进制、字幕元数据和原始 artifact 的记录。

需要续跑某个 `partial`、`failed` 或 `cancelled` 子任务时：

```powershell
$failedJobId = '<替换为子任务 JobId>'
$resumeBody = @{ strategy = @{ max_retries = 3 } } | ConvertTo-Json -Depth 5

Invoke-RestMethod `
    -Method Post `
    -Uri "http://localhost:8000/api/v1/crawl-jobs/$failedJobId/resume" `
    -Headers $headers `
    -ContentType 'application/json' `
    -Body $resumeBody

Wait-CrawlJob -JobId $failedJobId -TimeoutSeconds 7200 | ConvertTo-Json -Depth 10
```

续跑保持逻辑 job ID 不变，创建新的 `crawl_run`，并跳过已经成功的模块。

## 13. 日志脱敏与测试证据

```powershell
$logs = docker compose logs --no-color api worker

if ($logs -match [regex]::Escape($apiKey)) {
    throw 'API key appeared in logs'
}
if ($logs -match '(?i)cookie\s*[:=]|authorization\s*[:=]') {
    throw 'Potential sensitive header appeared in logs'
}
```

建议保存以下非敏感证据：

- `git rev-parse HEAD`；
- `docker compose ps -a` 和 readiness JSON；
- Profile ID 与 `active` 状态，不保存 Profile 内容；
- 父任务 ID、`discovery` 状态、发现数量；
- 所有子任务 ID、终态和三个模块状态；
- 每个视频的指标、评论、弹幕、字幕计数；
- MinIO object key、artifact type、大小、SHA-256/ETag；
- 脱敏后的错误码与必要日志片段。

禁止保存或提交 `.env`、API Key、Cookie、Authorization、账号信息、浏览器 Profile、未脱敏响应或预签名 URL。

## 14. 测试完成后停止环境

保留 MySQL、MinIO 和 Profile 数据，仅停止容器：

```powershell
docker compose down
Remove-Variable apiKey, secureApiKey -ErrorAction SilentlyContinue
Remove-Item Env:COMPOSE_PROJECT_NAME
```

需要继续测试时重新设置项目名并启动：

```powershell
$env:COMPOSE_PROJECT_NAME = 'video-crawler-popular-e2e'
docker compose up -d mysql minio minio-init migrate api worker
```

只有确认测试数据不再需要时，才执行不可恢复的数据卷删除：

```powershell
$confirmation = Read-Host 'Type DELETE-popular-e2e to remove isolated test volumes'
if ($confirmation -ne 'DELETE-popular-e2e') { throw 'Cleanup cancelled' }

$env:COMPOSE_PROJECT_NAME = 'video-crawler-popular-e2e'
docker compose down --volumes --remove-orphans
Remove-Item Env:COMPOSE_PROJECT_NAME
```
