# DDREC 生产发布检查清单

> 发布版本：__________　Git SHA：________________　操作人：__________　日期：__________
>
> 发布服务：`api` / `admin` / `all`　发布窗口：__________
>
> 任一关键项失败：立即停止，不迁移、不切换、不宣告成功。

## A. 本地构建

- [ ] 当前目录是云端授权系统仓库根目录。
- [ ] 当前分支等于 `scripts/cloud_release_config.psd1` 的 `ProductionBranch`。
- [ ] 已记录 `git rev-parse HEAD`。
- [ ] `git status --short` 为空。
- [ ] 根目录 `VERSION` 与后端、前端版本一致。
- [ ] 已选择 production / api、admin 或 all；完整生产发布选择 production / all。
- [ ] 需要离线镜像时已使用 `-ExportDockerImage`。
- [ ] 后端编译、依赖、pytest 和 Alembic heads 检查通过。
- [ ] 前端依赖、类型检查、测试和 production build 通过。
- [ ] Admin 包含“生产环境”和 `/admin/` base path。
- [ ] Admin 不包含“开发环境”、localhost、127.0.0.1 或旧服务器 IP。
- [ ] 发布包不含 `.env`、私钥、数据库、备份、密码或测试激活码。
- [ ] 已记录发布包、Manifest、大小和本地 SHA-256。

## B. 上传校验

- [ ] 已上传到 `/opt/ddrec-license/incoming/<VERSION>`，没有上传到 current。
- [ ] RELEASE-MANIFEST.txt 和 SHA256SUMS.txt 已同时上传。
- [ ] 服务器直接计算的压缩包 SHA 与本地完全一致。
- [ ] 压缩包可用 `tar -tzf` 读取。
- [ ] Manifest 的 environment、service、version、Git SHA、API 和 Admin 标签正确。
- [ ] 若 SHA 文件为 CRLF，已先确认压缩包真实 SHA，再转换清单换行。

## C. 发布前检查

- [ ] `date`、`date -u`、`timedatectl status` 正常。
- [ ] `df -h` 有足够空间，`free -h` 无资源风险。
- [ ] `docker ps -a` 和 `docker compose ls` 正常。
- [ ] 原 license-api 为 healthy。
- [ ] 原 postgres 为 healthy。
- [ ] `nginx -t` 通过，Nginx active。
- [ ] 已记录原 `readlink -f /opt/ddrec-license/current`。
- [ ] 发布前 API 返回 200。
- [ ] 发布前 Admin 返回 200。
- [ ] 8080 仅监听 loopback，5432 未暴露。
- [ ] 原服务存在异常时已停止本次发布。

## D. 数据库和 Admin 备份

- [ ] ⚠️ 已运行当前版本 `scripts/backup.sh`。
- [ ] 数据库 dump 存在且大小大于 0。
- [ ] `.dump.sha256` 校验通过。
- [ ] `verify-backup.sh` 临时恢复验证通过并完成清理。
- [ ] 已记录数据库备份路径、大小和 SHA。
- [ ] 已用 `cp -a` 创建 `admin.backup-<时间>`。
- [ ] 需要更新版本标识时已备份 `.env.production`，且未输出内容。
- [ ] 已记录原 API 镜像标签、镜像 ID、容器状态和数据计数。
- [ ] 旧版本目录和旧镜像仍保留。

## E. 新版本预检查

- [ ] 新目录使用 `<VERSION>-<SHORT_SHA>`，未覆盖任何旧目录。
- [ ] 先解压到 `.staging-<VERSION>-<SHORT_SHA>`。
- [ ] 原包内逐文件 SHA 校验通过。
- [ ] Shell 文件已转 LF，`bash -n` 全部通过。
- [ ] 转换后已保留原清单并生成有说明的服务器工作清单。
- [ ] `scripts/precheck.sh` 通过。
- [ ] `docker compose ... config --quiet` 通过。
- [ ] `nginx -t` 通过。
- [ ] 包内 `.env`、私钥、数据库备份和敏感信息扫描为零。

## F. API 发布

- [ ] 采用路径 A（离线镜像）或路径 B（标准服务器构建），已记录路径。
- [ ] 新标签为不可变的 `ddrec-license-api:<VERSION>-production`。
- [ ] 镜像平台为 linux/amd64。
- [ ] 已记录新镜像 ID；旧镜像未删除。
- [ ] 当前 `load-images.sh` 标签约定已核对，未盲目执行不兼容脚本。
- [ ] Docker Hub 超时时没有切换生产。
- [ ] 若使用 wheel 应急方案，全部准入条件和审批记录齐全。
- [ ] 新镜像可在生产变量下导入应用。
- [ ] UID 10001 能读取只读挂载的签名私钥。

## G. 数据库迁移

- [ ] ⚠️ 数据库备份及临时恢复验证已经成功。
- [ ] 已记录 `alembic current`。
- [ ] 已记录 `alembic heads`。
- [ ] 已审查待执行迁移和向后兼容性。
- [ ] 迁移前使用权限 600 的临时环境副本，并只替换三个版本标识。
- [ ] 已执行 `scripts/migrate.sh` 或明确等价命令。
- [ ] 已记录迁移后 revision。
- [ ] 迁移失败时已停止，未切 current、未启动新 API。

## H. Admin 部署

- [ ] Admin 时间戳备份已存在。
- [ ] 新静态文件先进入 `admin.new-<SHORT_SHA>`。
- [ ] `index.html`、hash JS 和 CSS 存在。
- [ ] “生产环境”存在；开发标签和开发地址扫描为零。
- [ ] 目录权限 755、文件权限 644。
- [ ] 已原子切换 Admin，并保留 `admin.previous-<SHORT_SHA>`。
- [ ] Admin-only 发布没有迁移数据库、切 current 或重启 API。

## I. current 切换

- [ ] ⚠️ 镜像、备份、迁移和 Admin 准备均已通过。
- [ ] `.env.production` 仅更新镜像标签、服务版本和 Git SHA。
- [ ] 配置更新使用临时文件原子替换，权限仍为 600。
- [ ] 已执行 `ln -sfn` 指向新版本目录。
- [ ] `readlink -f` 与预期新目录完全一致。

## J. 重启和验证

- [ ] 已运行新版本 `scripts/restart.sh`。
- [ ] 未运行 `docker compose down -v`。
- [ ] PostgreSQL 未因普通发布被重建。
- [ ] license-api running / healthy / RestartCount 正常。
- [ ] postgres running / healthy / RestartCount 正常。
- [ ] `scripts/status.sh` 和 `scripts/verify.sh` 通过。
- [ ] API、ready、本地 loopback API 均返回 200。
- [ ] Admin 和 index 引用的 JS/CSS 均返回 200。
- [ ] Nginx 配置、服务和 HTTPS 证书正常。
- [ ] API 自报 version、buildCommit、environment、database 正确。
- [ ] 发布前后 OWNER、授权、设备和审计数量合理一致。
- [ ] API 日志无新 ERROR、Traceback 或 CRITICAL。
- [ ] 全部验收后已精确删除本次迁移临时环境副本，没有使用通配符。

## K. 浏览器人工验收

- [ ] 使用无痕窗口打开 `/admin/`。
- [ ] 页面显示“生产环境”，不显示“开发环境”。
- [ ] OWNER username、密码登录成功。
- [ ] 生产环境 TOTP 验证成功。
- [ ] 首页正常。
- [ ] 授权列表可读取。
- [ ] 创建授权/设备相关页面可打开。
- [ ] 版本策略页面正常。
- [ ] 审计日志可读取。
- [ ] Network 不请求 localhost、127.0.0.1 或开发域名。
- [ ] Console 无资源、CORS、CSP 或 API 错误。

## L. 回滚准备

- [ ] 已记录 OLD_RELEASE、OLD_IMAGE_TAG、Admin 备份和环境备份。
- [ ] 已确认旧代码与迁移后的 schema 兼容。
- [ ] 回滚脚本/命令已由第二人复核。
- [ ] 明确普通前端/API 故障不恢复数据库。
- [ ] ⚠️ 数据库恢复必须停写、事故审批、先恢复到独立临时库。
- [ ] 回滚后仍保留失败版本、失败 Admin、日志、旧/新镜像和备份。
- [ ] 最终结论填写为：成功 / 成功但待确认 / 失败已回滚 / 失败需人工处理。

签字：操作人 __________　复核人 __________　业务验收人 __________
