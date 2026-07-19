# Codex 代码审查提示

审查当前分支相对基线的修改，重点检查：

1. 是否违反 `AGENTS.md` 或 `CONSTRAINTS.md`；
2. Core 是否出现 `bvid`、`cid`、Bilibili URL 或平台字段；
3. Adapter 是否直接访问数据库或 MinIO；
4. 是否存在明文 Cookie、Authorization、API Key 或密码；
5. 强制取消是否终止整个进程组；
6. MySQL 事务是否会在强制中断时留下半提交状态；
7. MinIO 对象是否可能在未完成时被标记 available；
8. 评论和时间文本 Upsert 是否真正幂等；
9. 指标缺失是否被错误写成 0；
10. 游标分页是否稳定且不使用深 OFFSET；
11. 续跑是否会重复执行已成功模块；
12. 测试是否依赖真实网站或真实登录态；
13. Alembic 是否可从空库升级；
14. 是否增加了未批准的前端、用户、定时任务或多 Worker；
15. 文档和实现是否一致。

按严重程度输出：Blocker、Major、Minor。每条问题必须包含文件路径、具体风险和建议修复方式。
