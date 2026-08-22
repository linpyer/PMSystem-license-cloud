# DD Rec Build 79 Admin 生产部署方案

## 范围与边界

- 仅部署 `license-admin` 静态站点变更：DD Rec favicon、统一页面标题、移除更新内容输入。
- 不修改生产数据库，不执行 Alembic migration，不创建或发布客户端更新记录。
- `client_releases.release_notes` 与版本策略旧字段继续保留，旧 API 请求仍兼容。
- Build 79 客户端发布与 Admin 部署必须分别获得人工确认。

## 部署前检查

1. 确认 `v1.3` 分支工作区干净，记录 cloud Git SHA。
2. 运行 Admin 单元测试、TypeScript 类型检查和 production 构建。
3. 确认产物包含 `admin/index.html` 与 `admin/favicon.svg`，且 `index.html` 引用 `/admin/favicon.svg`。
4. 运行 license-server 单元测试，确认 Edition/Environment 更新隔离与旧 `releaseNotes` 请求兼容。
5. 备份当前 `/var/www/ddrec-license/admin` 静态目录并记录当前 release 软链接目标。

## 构建与部署

1. 在构建机执行 `scripts/build_cloud_release.ps1 -Environment production -Service admin`，校验生成包的 `SHA256SUMS.txt`。
2. 上传生产包到服务器 incoming 目录，服务器端再次执行 SHA-256 校验。
3. 解压到新的不可变 release 目录，不覆盖当前 release。
4. 执行包内 `scripts/precheck.sh`。
5. 使用 `scripts/install-release.sh` 切换 release 并同步 Admin 静态文件；不运行数据库 migration。
6. 执行 `nginx -t`，通过后 reload Nginx。

## 验收

1. `GET https://license.aixcc.top/admin/` 返回 HTTP 200，title 为 `DD Rec 授权管理`。
2. `GET https://license.aixcc.top/admin/favicon.svg` 返回 HTTP 200，`Content-Type` 为 `image/svg+xml`，响应体不是 Vue fallback HTML。
3. Chrome 与 Edge 清缓存刷新后页签显示正式 DD Rec 图标。
4. Admin“客户端更新”和“版本策略”页面均不再出现更新内容输入；Edition、Environment 仍可见。
5. 验证 `/api/v1/health/live`、`/api/v1/health/ready` 与客户端更新查询 API 行为不变。
6. 抽查 Build 78 已发布记录仍为 published，未产生新草稿或数据库写入。

## 回滚

1. 将 `current` 切回部署前 release，或恢复备份的 Admin 静态目录。
2. 执行 `nginx -t`，通过后 reload Nginx。
3. 复查 `/admin/`、API health 与客户端更新查询。
4. 本次无数据库 migration，不需要也不得执行数据库 downgrade。
