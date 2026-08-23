# DD Rec 生产一键发布工具

## 1. 目标与边界

DD Rec 生产发布统一从下面的 Windows 启动器进入：

```text
E:\AI-Project\DDREC\DDREC-Release.bat
```

BAT 只定位并启动 PowerShell、传递退出码和暂停显示结果。真正受 Git 管理的发布逻辑位于：

```text
cloud-license\scripts\release\release-all.ps1
cloud-license\scripts\release\DDREC.Release.psm1
cloud-license\deploy\production-release\*.sh
```

发布工具不会替代客户端现有“一键打包”。日常顺序仍然是：先打包、安装测试，确认无误后再运行发布工具。发布工具不会自动编译客户端，不会修复 Git，不会新建 AccessKey，也不会要求 Release Notes。

生产技术目录继续使用 `/opt/pmsystem-license`，不得因品牌名称变化而迁移或重命名。

## 2. 已审计的现网事实

截至 2026-08-23 的只读审计结果：

- SSH 配置别名为 `pmsystem-prod`，指向 `47.98.206.68`，沿用现有 SSH key。
- 生产根目录为 `/opt/pmsystem-license`。
- `current` 指向 `/opt/pmsystem-license/release/1.3.0-7001110`。
- API 为 `https://license.aixcc.top/api/v1`，Admin 为 `https://license.aixcc.top/admin/`。
- 下载域名 Nginx `root` 为 `/var/www/ddrec-downloads`，不是猜测值。
- 正式客户端路径为 `/releases/stable/<standard|license>/<version>/<build>/<file>`。
- Build 78 Standard 实际文件：`/var/www/ddrec-downloads/releases/stable/standard/1.3.0/78/DDREC-1.3.0-standard-Setup.exe`。
- Build 78 License Production 实际文件：`/var/www/ddrec-downloads/releases/stable/license/1.3.0/78/DDREC-1.3.0-license-Setup.exe`。
- Build 78 两个文件的服务器 SHA-256 与 `client_releases` published 记录一致。
- Admin 创建、编辑、发布、下架接口分别为：
  - `POST /api/v1/admin/client-releases`
  - `PATCH /api/v1/admin/client-releases/{id}`
  - `POST /api/v1/admin/client-releases/{id}/publish`
  - `POST /api/v1/admin/client-releases/{id}/withdraw`
- OWNER 登录使用 `POST /api/v1/admin/auth/login` 和 `POST /api/v1/admin/auth/totp/verify`，后续写请求使用安全 Cookie 与 CSRF header。
- 客户端公开更新接口为 `GET /api/v1/client-updates/latest`。
- PostgreSQL 当前镜像为 `postgres:17.5-alpine`；普通应用发布不得升级该镜像或重建数据库 volume。
- Alembic 当前数据库 revision 与现有生产代码 head 均为 `0007_client_releases`。

历史无 Build 目录的 URL 仍由 Nginx 只读兼容，但新发布一律使用 Build 目录。现网 API 校验规则要求目录名为纯数字 Build，因此本工具不会改成物理目录 `build-81`。

## 3. 文件与配置

非敏感配置位于：

```text
cloud-license\scripts\release\production-config.json
```

示例位于 `production-config.example.json`。可配置服务器别名、API、下载域名、生产根目录、下载根目录和最低磁盘空间。配置不得保存密码、TOTP、Token、SSH 私钥或更新签名私钥。

更新签名私钥默认只从下面的本机路径读取：

```text
%USERPROFILE%\.ddrec\keys\DDREC-update-ed25519-private.pem
```

私钥内容不会上传服务器、写日志、写 JSON 或进入 Git。服务器只收到安装包以及通过 Admin API保存的公开 Manifest 元数据和签名。

每次运行建立 `YYYYMMDD-HHMMSS` Session。本地日志位于：

```text
cloud-license\artifacts\release-logs\
```

服务器日志未来位于：

```text
/opt/pmsystem-license/logs/releases/<session>.log
```

日志会记录阶段、Git SHA、Build、SHA、目标路径和健康结果。密码、TOTP、私钥、Authorization、Cookie 和完整 Token 会被禁止记录或脱敏。

## 4. 首次 Bootstrap

服务器统一执行器首次安装必须与业务发布分开。先复核代码和 Dry Run，再由有权限人员明确执行：

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass `
  -File .\cloud-license\scripts\release\bootstrap-server-tools.ps1 `
  -ConfirmBootstrap
```

脚本还会要求准确输入：

```text
BOOTSTRAP
```

Bootstrap 的行为仅包括：

1. 本地对所有 Shell 文件执行语法检查。
2. 上传到独立 incoming 临时目录。
3. 服务器重新计算 SHA-256。
4. 服务器再次执行 `bash -n`。
5. 备份 `/opt/pmsystem-license/scripts` 中已有同名文件。
6. 先安装 `.new`，再逐文件原子替换稳定执行器。
7. 设置执行权限。

Bootstrap 不部署业务、不切换 `current`、不重启 Docker、不执行 Migration、不修改 Nginx、不上传客户端包。正在运行的执行器不会被边读边覆盖；新工具在临时区验证完毕后才替换，正式业务部署过程中也不会自更新执行器。

未来服务器安装路径为：

```text
/opt/pmsystem-license/scripts/
  deploy-release.sh
  backup-production.sh
  verify-release.sh
  health-check.sh
  rollback-release.sh
  status-production.sh
  common-release.sh
```

## 5. 菜单说明

双击 BAT 后显示：

```text
[1] 仅发布 Standard 客户端
[2] 仅发布 License-Production 客户端
[3] 发布 Standard + License-Production
[4] 仅部署 DD Rec 云端服务
[5] 云端服务 + Standard
[6] 云端服务 + Standard + License-Production
[7] Dry Run / 发布预检
[8] 查看当前生产状态
[0] 退出
```

`license-local` 不属于生产发布项。

每个真实发布模式自动执行 Preflight。client 与 cloud 仓库在涉及自身发布时必须同时满足：分支为 `v1.3`、工作区 clean、`HEAD == origin/v1.3`。不满足即停止；工具不会 pull、reset、rebase、提交、解决冲突或 force push。

## 6. 安装包识别与真实性验证

Standard 自动扫描：

```text
client\artifacts\client\standard\
```

License Production 自动扫描：

```text
client\artifacts\client\license\production\
```

工具读取候选安装包同目录的 `RELEASE-MANIFEST.txt` 与 `SHA256SUMS.txt`，并与实际文件交叉校验：

- ProductVersion
- BuildNumber
- GitCommit
- Edition
- LicenseEnvironment
- UpdaterVersion
- Installer 文件名
- 实际文件大小
- 实际 SHA-256
- Windows PE ProductVersion

伴随构建元数据通过实际文件 SHA-256 与唯一安装包绑定，不是只按文件名判断。Standard 必须为 `Edition=standard, Environment=none`；License Production 必须为 `Edition=license, Environment=production`。安装包 GitCommit 必须等于当前 client HEAD。

如果自动候选不合适，可以通过 Windows 文件选择器选择另一个 `.exe`，但所有验证规则仍然生效。

## 7. Preflight 与 Dry Run

Preflight 检查：

- 两个 Git 仓库的真实状态和 SHA。
- SSH，失败后等待 5 秒，最多共 3 次。
- API、Admin、下载域名。
- `current`、Docker API/PostgreSQL health。
- 数据库 revision 与代码 head。
- Nginx 下载 root。
- 磁盘空间。
- 数据库核心数量。
- 本地 Ed25519 更新私钥是否存在。
- 选定安装包真实性。
- 正式目标路径是否已存在及其 SHA。
- pending/destructive Migration。

Dry Run 会执行上述只读检查并显示 Cloud release 目录、Migration 计划、客户端目标 URL 和执行步骤。它绝不上传、备份、部署、Migration、修改数据库、创建 Draft、Published 或 reload。

可从命令行无交互执行 Standard Dry Run：

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass `
  -File .\cloud-license\scripts\release\release-all.ps1 `
  -Mode DryRun -DryRunScope Standard -NonInteractive
```

## 8. 客户端-only 发布

客户端-only 不构建或部署 cloud，不备份 PostgreSQL，不重启 Docker，不 reload Nginx。流程为：

1. Preflight 与安装包确认。
2. 显示目标 URL、Build、Git 和 SHA。
3. 要求输入 `DEPLOY` 才允许上传。
4. 上传到 `/opt/pmsystem-license/incoming/client/<session>/` 的 `.part` 文件。
5. 服务器校验大小和 SHA。
6. 在正式目录生成隐藏临时文件，再通过不覆盖的硬链接原子创建最终文件。
7. 若最终文件已存在：SHA 相同则幂等复用；SHA 不同立即停止。
8. HTTPS HEAD 与 Range 请求验证 200/206、Content-Length、Accept-Ranges、ETag/Last-Modified（按现网响应）。
9. 本机生成 Manifest、使用 Ed25519 私钥签名，再使用客户端内置公钥验证签名。
10. OWNER 交互登录并创建 Draft。
11. 验证 Draft 未出现在公开 API，standard/license-production/license-local 通道没有串线。
12. 最后显示发布确认。默认保持 Draft；只有选择目标并准确输入 `PUBLISH` 才调用 publish API。

上传中断不会创建 Draft 或 Published。incoming 中安全的 `.part` 可以留待清理；正式目录不会出现半文件。

## 9. Cloud-only 与完整发布

Cloud 包由现有 `scripts/build_cloud_release.ps1` 从当前 clean commit 生成，运行原有测试和生产构建，生成 tar.gz 与 SHA-256。服务端再校验 archive SHA、内部 `SHA256SUMS.txt`、Git commit、版本、必需文件和 Shell 语法。

Cloud-only 执行：

1. 完整计划展示并要求输入 `DEPLOY`。
2. `flock` 获取 `/opt/pmsystem-license/.deploy.lock`；已有发布时拒绝并发。
3. 解压到 `.staging-<session>` 并验证，再安装为不可变 `release/<version>-<short-sha>`。
4. 比较现用 PostgreSQL 镜像和新 Compose；任何 PostgreSQL 镜像变化默认阻止。
5. 备份成功后才继续。
6. 使用新 API image 只读检查数据库 revision 与代码 head。
7. 无 pending Migration 则继续；有 pending Migration 时必须再次回答 Y；破坏性模式直接停止并要求人工审计。
8. Admin 构建先进入临时目录，验证 `index.html` 后再原子替换。
9. 新 `.env.production` 在独立临时文件中只更新 image tag、version 与 build commit，再原子替换。
10. `current.new-<session>` 准备好后通过原子 rename 切换 `current`。
11. 只 reconcile `license-api`；不执行 `down -v`，不删除或重建 PostgreSQL volume，不 prune。
12. Nginx 配置相同则完全不 reload。配置不同时默认阻止；只有独立审计并显式允许时才备份、安装、`nginx -t` 和 reload。
13. 验证 Docker、API、数据库、Admin、buildCommit 和核心数量。

完整发布在 Cloud 健康和数据数量检查通过后才上传客户端、签名、创建 Draft，Published 始终是最后一步。

## 10. 备份

每次 Cloud 部署创建：

```text
/opt/pmsystem-license/backups/release-<session>/
```

至少包括：

- PostgreSQL custom-format dump。
- dump SHA-256。
- `pg_restore -l` 可读列表。
- Admin 静态目录压缩包。
- `.env.production`（目录 0700、文件 0600）。
- current release 路径。
- 当前 Nginx 配置与 `nginx -T` 输出。
- 部署前数据库核心数量。

dump 必须非空、SHA 校验成功且 `pg_restore -l` 可读，否则部署停止。现有独立 `verify-backup.sh` 临时恢复验证流程仍保留，可在高风险发布前额外执行；统一执行器不会直接覆盖恢复生产数据库。

## 11. Migration 与回滚边界

本地和服务器都会扫描 pending Migration。出现 `drop_table`、`drop_column`、`DROP TABLE`、`DROP COLUMN`、`TRUNCATE` 或无条件 `DELETE FROM` 等明显破坏性模式时自动停止。

- 未执行 Migration：部署后 health 失败会尝试恢复旧 `.env.production`、旧 `current` 和 Admin，再启动旧 API 并重新执行 health。只有健康检查成功才报告“生产已恢复”。
- 已执行 Migration：不会自动 pg_restore，不会盲目切回旧应用。工具保留备份与现场，输出人工兼容性/恢复审计要求。

数据库恢复必须按照现有灾难恢复文档，在独立 restore 数据库验证后，由人工制定恢复窗口。普通发布绝不执行 Alembic downgrade。

## 12. Draft、Published 与幂等性

工具只通过 Admin API 操作发布记录，不直接 INSERT/UPDATE 生产数据库。

相同 Version、Build、Edition：

- 正式文件不存在：上传并创建。
- 正式文件存在且 SHA 相同：复用并继续校验。
- 正式文件存在但 SHA 不同：立即停止，不覆盖。
- Draft 已存在：应复用/由运维复核；API 的唯一约束也会阻止重复记录。
- Published 已存在：显示已发布，不创建重复 published。

`published` 之后不再执行部署、上传、Migration、Nginx 等高风险动作。取消或失败时，Draft 可以保留以维持审计链；工具不会直接删除数据库记录。

## 13. Production Status

菜单 `[8]` 只读显示：

- SSH 与磁盘空间。
- current release。
- API version/buildCommit/status/database。
- cloud local HEAD。
- API/PostgreSQL 容器 health。
- Admin HTTP。
- Nginx download root。
- OWNER、licenses、device bindings、license events、device trials、admin audit、client releases 数量。
- Standard 与 License Production 最新 published 记录及下载 URL。

下载域名根路径返回 404 是现网设计（目录列表关闭），不表示文件下载服务故障。

## 14. 失败处理与退出码

任一关键阶段失败立即停止后续步骤。报告包含失败阶段、失败命令、已完成阶段、是否修改生产、Migration/回滚状态、Draft 和 Published 列表及日志路径。

退出码：

```text
0  成功
10 Preflight
20 上传
30 备份
40 部署
50 Migration
60 Health
70 客户端验证
80 Draft/Published API
90 用户取消
```

常见问题：

- `working tree dirty`：人工审阅、提交并 push；不要让发布工具修复。
- `HEAD != origin/v1.3`：先按团队 Git 流程同步，不要 force push/reset。
- License 包 GitCommit 不一致：重新用当前 client commit 打包并测试。
- SSH 连续失败：检查本地网络、SSH key 和云安全组；工具不会修改 sshd 或安全组。
- 不可变路径 SHA 冲突：视为严重发布冲突，禁止覆盖，人工审计历史记录。
- pending destructive Migration：停止并安排数据库变更评审。
- health 失败且已 Migration：不要直接 restore，按人工恢复指引处理。

## 15. 测试

测试文件：

```text
cloud-license\tests\release\ReleaseTool.Tests.ps1
```

运行：

```powershell
Import-Module Pester -RequiredVersion 3.4.0 -Force
Invoke-Pester .\cloud-license\tests\release\ReleaseTool.Tests.ps1
```

覆盖 25 个指定故障分支以及 Git、安装包、不可变 SHA 和通道隔离成功分支。还应执行 PowerShell parser、Python compile、所有 Shell `bash -n`、真实 Production Status 与真实只读 Dry Run。

## 16. 本轮启用边界

首次代码交付只完成审计、开发、测试和生产只读检查。不得顺带执行 Bootstrap、业务部署、Docker 更新、Migration、Nginx 修改、客户端上传、Production Draft 或 Published。

用户审阅本文件、自动测试和真实 Dry Run 后，下一步仅是单独确认是否 Bootstrap 新的服务器发布执行器。Bootstrap 完成后仍需另一次明确的 `DEPLOY` 才能进入任何生产写操作。
