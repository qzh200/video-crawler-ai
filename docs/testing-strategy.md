# 测试策略

## 1. 测试层级

### 单元测试

覆盖：

- Domain 模型和校验；
- 策略合并与边界；
- 状态机；
- 游标编码解码；
- 去重键；
- Adapter Registry；
- Bilibili parser；
- 脱敏器；
- Profile 路径校验。

### Repository 集成测试

使用临时 MySQL：

- Alembic 空库升级；
- Job claim 的 `SKIP LOCKED`；
- UUID BINARY 转换；
- 评论 Upsert 和父子关系；
- 时间文本去重；
- 指标快照不可覆盖；
- 幂等键 24 小时语义。

### MinIO 集成测试

使用临时 MinIO：

- 临时对象上传；
- 校验 hash/size；
- 提升为正式对象；
- 预签名 URL；
- 过期清理；
- 中断对象回收。

### API 测试

使用 FastAPI TestClient/httpx：

- API Key；
- 创建任务；
- 幂等提交；
- 取消；
- 续跑；
- 查询与游标分页；
- 错误格式。

### Worker 测试

- 领取单个任务；
- 子进程启动；
- 心跳；
- SIGTERM；
- SIGKILL fallback；
- Chromium 模拟子进程被整组回收；
- Worker 重启后回收过期租约。

### Adapter 测试

CI 不访问真实网站。使用：

- mock BrowserGateway；
- mock HttpGateway；
- 脱敏本地 fixture；
- 合成二进制/JSON/XML 数据；
- 已知输入到标准模型的断言。

真实 Profile 验证标记为 `manual`，默认不运行。

## 2. 覆盖率

- 总覆盖率不低于 85%；
- Domain、状态机、策略和去重逻辑目标 95% 以上；
- 每个生产 bug 必须先增加回归测试。

## 3. 必须验证的端到端场景

1. 单视频任务全部成功；
2. 列表任务发现 3 个视频并创建子任务；
3. 评论失败但指标和时间文本成功，任务为 partial；
4. 手动续跑只执行评论；
5. 取消运行任务后进程组无残留；
6. 重复采集评论和时间文本不重复插入；
7. 指标重复采集生成两个快照；
8. Profile 失效使相关任务失败并暂停；
9. MinIO 不可用时不产生伪 available 对象；
10. 过期清理只删除原始对象，不删除结构化数据。
