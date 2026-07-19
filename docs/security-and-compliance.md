# 安全与合规

## 1. 凭据

- Cookie 和浏览器状态只存在于 Worker 挂载的 Profile Volume；
- MySQL 只保存安全相对目录名；
- API 容器不能访问 Profile Volume；
- 所有密钥通过环境变量或 Docker Secrets 注入；
- 生产环境不得使用示例密码；
- MinIO Bucket 保持私有；
- 原始对象下载使用短期预签名 URL。

## 2. 路径安全

`profile_directory` 必须满足：

- 只包含字母、数字、`.`、`_`、`-`；
- 长度 1–100；
- 不能是 `.` 或 `..`；
- 解析后的绝对路径必须位于 `BROWSER_PROFILE_ROOT` 下；
- 不接受绝对路径和路径分隔符。

## 3. 日志脱敏

必须屏蔽：

- `Cookie`；
- `Set-Cookie`；
- `Authorization`；
- API Key；
- MinIO Secret；
- MySQL 密码；
- 可能包含签名或令牌的查询参数；
- Profile 文件内容。

日志保留：

- request_id；
- job_id；
- run_id；
- video_id；
- module；
- stage；
- elapsed_ms；
- error_code；
- HTTP 状态；
- 脱敏后的 host/path。

## 4. 采集边界

系统只使用用户自己的浏览器登录态访问其正常可见数据。禁止实现：

- CAPTCHA 绕过；
- DRM 绕过；
- 付费墙绕过；
- 访问控制绕过；
- 账号轮换规避限制；
- 自动破解签名或反爬对抗；
- 未经授权的高并发批量访问。

Adapter 遇到登录失效、风控或拒绝访问时，应返回结构化错误并停止相关 Profile 任务。

## 5. API Key

无用户体系。可选固定 API Key：

- 使用常量时间比较；
- 不记录原值；
- 健康检查可公开；
- 业务接口统一依赖鉴权依赖项。
