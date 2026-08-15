# DDREC 生产环境迁移清单

本清单仅用于后续维护窗口内规划现有生产服务器迁移。本次代码重命名未连接生产服务器，也未修改线上目录、Compose 项目、容器、Volume、PostgreSQL、Nginx、证书或密钥。

## 身份映射

- 品牌展示：`PMSystem` → `DD Rec`
- 技术产品：`PMSystem` → `DDREC`
- 部署根目录：`/opt/pmsystem-license` → `/opt/ddrec-license`
- Compose 项目：`pmsystem-license-production` → `ddrec-license-production`
- API 镜像：`pmsystem-license-api` → `ddrec-license-api`
- PostgreSQL 数据库与用户：`pmsystem_license` → `ddrec_license`
- PostgreSQL Volume：先记录线上实际名称，再迁移到 `ddrec-license-production_ddrec_license_postgres_data`
- Nginx 配置：`pmsystem-license.conf` → `ddrec-license.conf`
- Admin 静态目录：`/var/www/pmsystem-license/admin` → `/var/www/ddrec-license/admin`
- Nginx 日志：`pmsystem-license-*.log` → `ddrec-license-*.log`
- 环境变量前缀：`PMSYSTEM_` → `DDREC_`

## 执行前

- 安排维护窗口并停止写入，记录当前 Git SHA、发布版本、Compose 项目名、容器、网络、Volume、数据库名、角色、Nginx 配置及证书路径。
- 对 PostgreSQL 创建可恢复的自定义格式备份与 SHA-256，并在隔离环境完成一次恢复演练。
- 备份 `/opt/pmsystem-license/config`、`secrets`、当前发布软链接和 Nginx 配置；私钥不得进入发布包或 Git。
- 明确 Volume 的真实物理名称，不通过猜测或通配符执行移动、删除或重建。

## 维护窗口

- 先部署新的 DDREC 代码和镜像，但不要让新旧栈同时写入同一数据库。
- 使用备份恢复或经过验证的 PostgreSQL 重命名方案建立 `ddrec_license`，同步角色授权后再切换连接串。
- 显式创建并验证新的 Compose 项目、网络与 Volume；禁止执行 `docker compose down -v`。
- 安装 `ddrec-license.conf`，通过 Nginx 配置检查后再原子切换并 reload。
- 验证 API 健康检查、Admin 登录、TOTP、授权码签发、客户端激活、审计日志、备份与恢复。

## 回滚与收尾

- 保留旧栈只读快照、数据库备份和旧 Nginx 配置，直到新栈完成观察期。
- 回滚只切换应用与 Nginx；数据库回滚必须基于已验证备份，禁止直接删除新旧 Volume。
- 观察期结束并再次确认备份可恢复后，另行审批旧目录、旧镜像、旧 Compose 项目、旧 Volume、旧数据库和旧日志的清理。

## 本次状态

- 线上迁移：未执行。
- 数据库或 Volume 操作：未执行。
- Nginx 或证书操作：未执行。
