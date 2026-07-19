# 状态机

## 1. Crawl Job

```text
pending -> running -> success
                   -> partial
                   -> failed
                   -> cancelling -> cancelled
pending -------------------------> cancelled
partial/failed/cancelled --resume--> pending
```

非法转换必须返回领域错误，不得静默修改。

## 2. Crawl Run

```text
pending -> running -> success
                   -> partial
                   -> failed
                   -> cancelled
```

每次首次执行和手动续跑均创建新的 Run。

## 3. Module Run

模块：`discovery`、`metrics`、`comments`、`timed_text`。

```text
pending -> running -> success
                   -> failed
                   -> cancelled
                   -> skipped
```

`skipped` 只用于续跑时已经成功、不需要重复执行的模块。

## 4. Profile

```text
active -> expired
active -> disabled
expired -> active  # 人工重新登录并 verify
expired -> disabled
disabled -> active # enable 后仍需 verify
```

## 5. Raw Artifact

```text
uploading -> available
uploading -> missing
available -> expired
available -> missing
expired -> delete_failed
```

## 6. 父子任务汇总

列表父任务：

- 所有子任务成功：`success`；
- 至少一个成功或 partial，且至少一个失败/partial：`partial`；
- 所有子任务失败：`failed`；
- 父任务取消：`cancelled`，未开始子任务取消，当前子任务强制终止；
- 没有发现视频：根据 Adapter 结果决定 `success`（有效空列表）或 `failed`（解析失败）。
