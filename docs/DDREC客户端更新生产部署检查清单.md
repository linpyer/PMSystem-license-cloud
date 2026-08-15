# DDREC 客户端更新生产部署检查清单

## 上线前

- [ ] `download.aixcc.top` 已由域名管理员添加 A/AAAA 或 CNAME，且公网解析指向目标服务。
- [ ] DNS 生效后再申请该域名 HTTPS 证书；禁止临时 IP、HTTP 或跳过证书校验。
- [ ] 备份 PostgreSQL、`/var/www/ddrec-license/admin`、生产 `.env` 和现有 Nginx 配置。
- [ ] 记录 `docker compose ps`、授权 API healthy 状态、OWNER 登录与 Admin 基线结果。
- [ ] 创建 `/opt/ddrec-updates/incoming` 和 `/var/www/ddrec-downloads/releases`，设置发布账号可写、Nginx 只读、API 容器只读。
- [ ] 把仓库中的更新公钥安装为 `/opt/ddrec-license/config/update_ed25519_public.pem`；确认更新私钥从未上传服务器。
- [ ] 在生产 `.env` 配置 `DDREC_UPDATE_DOWNLOAD_ROOT`、`DDREC_UPDATE_DOWNLOAD_BASE_URL`、`DDREC_UPDATE_SIGNING_PUBLIC_KEY_PATH`。

## 数据库与应用

- [ ] 在数据库备份成功后执行 Alembic migration `0007_client_releases`，先检查单一 head 和 SQL。
- [ ] 部署 API/Admin 前核对镜像 digest、GitCommit 和 RELEASE-MANIFEST。
- [ ] 迁移后确认 PostgreSQL healthy、授权 API `/health/ready` 正常、原授权激活/验证行为无回归。
- [ ] OWNER、ADMIN、AUDITOR 登录与权限正常；仅 OWNER 能发布和下架，OWNER/ADMIN 可建草稿和编辑说明。
- [ ] Admin “客户端更新”可查看版本、Build、Edition、环境、架构、通道、状态、大小、发布时间、SHA-256 和 GitCommit。

## Nginx 与下载域名

- [ ] 先安装并测试 `ddrec-downloads-http.conf` 的 ACME 路径，再取得证书。
- [ ] 证书存在后从 `ddrec-downloads-https.conf.template` 启用 HTTPS 站点，执行 `nginx -t`，失败时不 reload。
- [ ] `curl -I` 返回 HTTPS、正确 Content-Length、Accept-Ranges；`curl -r 0-1048575` 返回 206 和正确 Content-Range。
- [ ] 完整大文件下载 SHA-256 与发布记录一致；1 MB 后单连接速度约 4 MB/s。
- [ ] 根目录、任意目录、隐藏文件和 `.part` 返回 404；不存在的安装包返回 404；目录列表关闭。
- [ ] `license.aixcc.top` 的 API、Admin、证书和 Nginx 配置不受影响。

## 首次发布验证

- [ ] 分别构建 standard 与 license-production，产物同时包含 `DDREC.exe` 和 `DDREC-Updater.exe`。
- [ ] 发布脚本仅生成草稿；OWNER 人工确认后发布。
- [ ] 无授权或授权过期客户端仍能查询公开更新接口；接口响应不含敏感信息。
- [ ] 验证无更新、大版本更新、同版本高 Build、低版本拒绝、Edition/环境/通道隔离。
- [ ] 验证断网续传、ETag 变化重置、SHA/签名篡改拒绝、重复点击并发控制。
- [ ] 实际录制时安装被拒绝；下载中开始录制后 `.part` 保留且录像 FPS、扫码输入正常。
- [ ] Updater 等待 DDREC 正常退出、UAC 正常出现、安装成功后重启；模拟失败时旧客户端和数据仍可用。

## 回滚与下架

- [ ] 问题版本立即在 Admin 下架；不覆盖或删除已发布安装包和数据库记录。
- [ ] 需要修复时提升 BuildNumber、重新构建签名并创建新草稿，不重用旧 URL。
- [ ] API/Admin 部署异常时使用部署前备份回滚；数据库回滚前评估并备份新增 `client_releases` 数据。
- [ ] 保留发布草稿、审核、发布、下架审计和 Nginx 访问日志，不记录私钥或凭据。

## 当前人工前置条件（2026-08-15）

检查时 `download.aixcc.top` 为 NXDOMAIN，而 `license.aixcc.top` 正常解析。因此当前只能合入代码、migration、Admin、发布脚本与 Nginx 模板；不得启用下载 HTTPS 站点或执行生产部署。域名管理员完成 DNS 后，按本清单重新从备份开始执行。
