# 运维指南

本文档描述 0.1.0 的实际生产路径：单个 API、单个 Worker、MySQL、MinIO、手动
Profile 登录，以及备份、恢复和故障处理。所有 PowerShell 命令均从仓库根目录执行。

## 1. 前置条件与固定版本

- Docker Desktop，支持 Compose v2；
- 首次构建时能够访问 Python 包索引和 Chromium 下载源；
- 容器内交互登录需要操作者自行提供 X11 显示服务；Windows 可使用本机 X Server，
  并允许 Docker Desktop 通过 `host.docker.internal` 访问；
- Python 镜像 `python:3.12.13-slim-bookworm`；
- MySQL 镜像 `mysql:8.4.10`；
- MinIO 镜像 `RELEASE.2025-09-07T16-13-09Z`；
- MinIO Client 镜像 `RELEASE.2025-08-13T08-35-41Z`；
- Crawl4AI `0.9.2`，镜像通过 Playwright 安装与其匹配的 Chromium 和 Linux 依赖。

版本来源和浏览器安装方式参考 [Crawl4AI 安装文档](https://docs.crawl4ai.com/core/installation/)、
[Crawl4AI PyPI](https://pypi.org/project/Crawl4AI/)、[Python 官方镜像](https://hub.docker.com/_/python)、
[MySQL 官方镜像](https://hub.docker.com/_/mysql) 和
[MinIO 发布页](https://github.com/minio/minio/releases)。升级前先在测试环境重新构建并执行完整验收。

## 2. 初始化配置

```powershell
Copy-Item .env.example .env
```

至少修改 `.env` 中的 `API_KEY`、`MYSQL_PASSWORD`、`MYSQL_ROOT_PASSWORD` 和
`MINIO_SECRET_KEY`。不要提交 `.env`，不要把真实 Cookie、账号信息或浏览器 Profile 放入 Git。
`BROWSER_PROFILE_ROOT` 在容器内保持为 `/var/lib/video-crawler/browser-profiles`；Worker 和
`profile-login` 都把 `browser_profiles` volume 挂载到该路径，API 不挂载此 volume。

检查解析后的配置；输出不得出现空变量警告：

```powershell
docker compose config --quiet
```

## 3. 构建和启动

首次构建会下载 Chromium，耗时取决于网络：

```powershell
docker compose build
docker compose up -d mysql minio minio-init migrate api worker
docker compose ps
Invoke-WebRequest http://localhost:8000/health/ready -UseBasicParsing
```

成功信号是 `mysql`、`minio` 健康，`migrate` 与 `minio-init` 成功退出，API 和 Worker
持续运行，readiness 返回 HTTP 200。迁移必须在 API/Worker 前完成；手动迁移命令为：

```powershell
docker compose run --rm migrate alembic upgrade head
```

## 4. Profile 首次登录

### 4.1 容器内交互登录

先启动本机 X Server，并按所选 X Server 的说明允许来自 Docker Desktop 的连接。然后运行：

```powershell
docker compose run --rm -e DISPLAY=host.docker.internal:0 profile-login login --platform bilibili --profile bilibili-main
```

浏览器打开后手动完成正常登录，回到终端按 Enter。该命令只运行
`python -m video_crawler.cli login ...`，不会启动 Worker 循环。不要在同一个 Profile 正被
Worker 使用时运行登录命令。若操作者使用其他显示方案，只替换 `DISPLAY`/X11 挂载方式，
不要更改 Profile volume。

### 4.2 本机交互登录

如果本机已有 Python 3.12，可让本机和 Worker 使用一个显式目录。Windows 示例：

```powershell
uv sync --extra dev
uv run python -m playwright install chromium
$env:BROWSER_PROFILE_ROOT = (Resolve-Path .).Path + '\browser_profiles'
uv run python -m video_crawler.cli login --platform bilibili --profile bilibili-main
```

若后续改用容器 Worker，需由操作者把这个目录安全复制到 `browser_profiles` volume；不要通过
API 上传 Cookie。通常优先使用容器登录，避免复制 Profile。

## 5. 注册与验证 Profile

登录完成后注册 Profile；同名 Profile 已存在时复用其返回的 `profile_id`：

```powershell
$headers = @{ 'X-API-Key' = '<your-api-key>' }
$body = @{
  platform = 'bilibili'
  profile_name = 'bilibili-main'
  profile_directory = 'bilibili-main'
} | ConvertTo-Json
$profile = Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/v1/auth-profiles -Headers $headers -ContentType 'application/json' -Body $body
$profileId = $profile.profile_id
Invoke-RestMethod -Method Post -Uri "http://localhost:8000/api/v1/auth-profiles/$profileId/verify" -Headers $headers
```

只有验证结果为 `active` 才创建任务。验证失败时停止相关任务，重新执行交互登录，再调用
`verify`；不要删除结构化结果。

## 6. 创建、查询、取消和续跑

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

取消会先请求终止任务进程组，宽限期后强制终止；已提交的 MySQL 数据和完整 MinIO 对象保留。
续跑只允许 `partial`、`failed` 或 `cancelled` 任务，并创建新的 run。

## 7. 备份与恢复

创建一致性维护窗口时先停止写入：

```powershell
docker compose stop api worker
New-Item -ItemType Directory -Force .\backup\minio | Out-Null
docker compose exec -T mysql sh -c 'exec mysqldump --single-transaction --routines --triggers -uroot -p"$MYSQL_ROOT_PASSWORD" "$MYSQL_DATABASE"' > .\backup\mysql.sql
docker compose run --rm --entrypoint /bin/sh --volume "${PWD}\backup\minio:/backup" minio-init -ec 'mc alias set local http://minio:9000 "$MINIO_ACCESS_KEY" "$MINIO_SECRET_KEY"; mc mirror --overwrite "local/$MINIO_BUCKET" /backup'
docker compose start api worker
```

恢复前再次停止 API/Worker，并确认目标环境允许覆盖。数据库恢复到已创建的空数据库；MinIO
恢复只影响原始对象，结构化数据以 MySQL 为准：

```powershell
docker compose stop api worker
Get-Content -Raw .\backup\mysql.sql | docker compose exec -T mysql sh -c 'exec mysql -uroot -p"$MYSQL_ROOT_PASSWORD" "$MYSQL_DATABASE"'
docker compose run --rm --entrypoint /bin/sh --volume "${PWD}\backup\minio:/backup" minio-init -ec 'mc alias set local http://minio:9000 "$MINIO_ACCESS_KEY" "$MINIO_SECRET_KEY"; mc mirror --overwrite /backup "local/$MINIO_BUCKET"'
docker compose start api worker
Invoke-WebRequest http://localhost:8000/health/ready -UseBasicParsing
```

备份文件包含敏感业务数据，应加密、限制访问并按组织策略保留。不要用 `docker compose down -v`
进行普通重启；`-v` 会删除数据库、对象和 Profile volumes。

## 8. 清理与故障处理

- 原始对象按 `RAW_ARTIFACT_RETENTION_DAYS` 清理；`0` 表示永久。清理只删除 MinIO 原始对象，
  不删除结构化数据；查看 Worker 日志确认 `delete_failed` 后再处理存储权限或网络问题。
- readiness 非 200：运行 `docker compose ps` 和 `docker compose logs migrate api minio`，依次确认
  MySQL、迁移版本、MinIO 与 bucket。
- Worker 异常：运行 `docker compose logs worker`；用 `docker compose top worker` 查看任务与
  Chromium 子进程。确认没有运行任务后可执行 `docker compose restart worker`。
- 强制取消后仍有 Chromium：记录 job/run ID、`docker compose top worker` 输出和 Worker 日志；
  重启 Worker 作为恢复措施，不要手工删除 Profile。
- Profile 失效：停止使用该 Profile 的任务，重新执行第 4 节登录命令，再调用 `verify` 和
  `resume`。同一 Profile 只允许一个 Worker/登录进程占用。
- 浏览器无法显示：确认 X Server 正在运行、允许连接，且 `DISPLAY` 指向操作者选择的显示服务；
  容器内不提供或绕过验证码。
- 浏览器依赖错误：重新执行 `docker compose build --no-cache profile-login`，检查构建日志中的
  Playwright Chromium 安装步骤；不要在运行中的容器临时安装未记录依赖。

排障日志不得包含 Cookie、Authorization、完整敏感请求头或真实 `.env` 值。
