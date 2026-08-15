# DDREC 客户端在线更新设计与发布流程

## 架构与信任边界

DD Rec 在主窗口显示后延迟 7 秒后台访问 `GET https://license.aixcc.top/api/v1/client-updates/latest`，之后最多每 12 小时检查一次。接口只返回发布元数据，不读取安装包。客户端完全使用接口返回的 HTTPS 下载地址，因此以后迁移 OSS/CDN 不需要修改客户端、数据库、Admin、Updater 或签名格式。

正式安装包由 `download.aixcc.top` 的 Nginx 静态提供：支持 Content-Length、HTTP Range 和断点续传，单连接在首个 1 MB 后限制为约 4 MB/s。Python/FastAPI 不传输安装包。

更新只允许 `standard/production/stable -> standard/production/stable`、`license/production/stable -> license/production/stable`。`license/local/dev` 仅供测试，绝不查询 production stable 包。版本排序先比较三段 ProductVersion，再在版本相同时比较 BuildNumber；GitCommit 只用于追踪。

## Manifest 与签名

签名字段固定为 `product, version, buildNumber, edition, environment, architecture, channel, fileName, fileSize, sha256, publishedAt`。字段按名称排序，以 UTF-8、无额外空白的 JSON 规范化后使用 Ed25519 签名。客户端在下载前验证签名及发布通道，下载后验证文件大小和 SHA-256；启动 Updater 前和 Updater 启动安装程序前都会再次验证。

更新密钥与授权许可证密钥相互独立。私钥只存放在受保护的发布工作站 `%USERPROFILE%\.ddrec\keys\DDREC-update-ed25519-private.pem`，不得进入 Git、客户端、服务器下载目录、日志或报告。公钥可以进入客户端和 API 容器。密钥轮换必须先发布包含新公钥的客户端，再切换发布签名；旧公钥撤销前需完成覆盖率评估。

## 构建与发布

1. 在干净的 `v1.3` 分支执行正式客户端构建。`scripts/build_client.ps1` 动态读取版本、BuildNumber 与 GitCommit，并同时构建 `DDREC.exe` 和 `DDREC-Updater.exe`。
2. 确认安装包名称为 `DDREC-<version>-standard-Setup.exe` 或 `DDREC-<version>-license-Setup.exe`。同版本重新构建必须提高 BuildNumber，已发布文件不可覆盖。
3. 执行 `scripts/publish_client_update.ps1`。脚本读取 RELEASE-MANIFEST、重新计算 SHA-256、生成规范化 Manifest，并使用工作站外部私钥签名。
4. 脚本先上传到 `/opt/ddrec-updates/incoming/` 的 `.part` 文件，服务器复核大小和 SHA-256，再复制到正式文件系统的隐藏临时文件，并在同一目录原子 rename 为 `/var/www/ddrec-downloads/releases/<channel>/<edition>/<version>/<buildNumber>/...`。BuildNumber 目录确保同一 ProductVersion 的更高 Build 不覆盖历史安装包；Nginx 同时保留对早期无 BuildNumber 路径的只读兼容。
5. 脚本通过服务器 CLI 创建 `client_releases` 草稿，不会自动发布。
6. OWNER 登录“DD Rec 授权管理 → 客户端更新”，复核版本、Build、Edition、环境、更新说明、SHA-256 和 GitCommit，然后点击发布。API 会再次检查文件、大小、SHA-256、Ed25519 签名及唯一键；任一失败都禁止发布。
7. 需要停止分发时使用“下架”。已发布记录不删除，下架后立即不再被公开接口选中。

## 客户端流程与失败安全

自动检查失败仅写日志；手动失败才显示友好提示。自动下载和自动安装均关闭，用户必须点击“立即更新”。下载使用 `%LOCALAPPDATA%\DDREC\updates\<version>-<build>\`，未完成文件以 `.part` 结尾并带独立断点元数据。ETag、Last-Modified、文件大小或发布元数据变化时放弃旧断点。

录制是最高优先级：检查和提示允许继续，安装入口统一读取 Recorder 的实际状态；录制中不能启动更新或安装。下载过程中开始录制会暂停网络读取并保留 `.part`，录制结束后不会自动恢复抢占业务，必须由用户继续。

校验通过后 `DDREC-Updater.exe` 等待父进程正常退出，通过 Windows UAC 启动现有 Inno Setup 覆盖安装，等待成功后重新启动 `DDREC.exe`。Updater 不接触 SQLite、视频、配置、日志、授权缓存或业务模块。API、网络、签名、哈希、Updater、Installer 任一失败时，当前 DD Rec 和全部用户数据保持可用。

## 日志与 OSS/CDN 迁移

客户端记录 `update.check.started/success`、`update.available`、`update.download.started/paused/resumed/completed`、`update.sha256.failed`、`update.signature.failed`、`update.install.started/success/failed` 等事件。日志不得包含更新私钥、授权 Token、TOTP 或 SSH 凭据。

迁移 OSS/CDN 时保持数据库 Manifest、签名和公开 API 不变，将不可变安装包同步到新源站，并把 API 下载基址或 `download.aixcc.top` 切换到 CDN。迁移前验证 HEAD、GET、Range、Content-Length、ETag、HTTPS 和缓存键；不得复用 URL 覆盖已有对象。
