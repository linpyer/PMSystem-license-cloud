# PMSystem 云环境实施部署与版本发布操作手册

> 正式 Markdown 操作源文件
>
> 代码基线：云端仓库 `54dca46f9836c0f92e1ed82490f487295ddf62c3`
>
> 生产实证基线：2026-08-04 成功发布记录
>
> 总原则：先校验、再备份、后迁移、最后切换；任一关键检查失败立即停止。

## 第1章 文档说明

本手册适用于 PMSystem 云端授权管理系统的首次生产部署、日常版本发布、备份验证、数据库迁移、验证、应用回滚和灾难恢复演练。适用人员为服务器实施人员、发布负责人、数据库负责人和安全管理员。

Windows 客户端不属于本手册的云端发布对象。首次部署需要准备操作系统、目录、生产秘密、数据库、Nginx 和 HTTPS；日常发布复用这些服务器资源，只替换经过验证的 API、Admin 和版本软链接。

操作标识：

- `【本地 Windows】`：在云端源码仓库根目录使用 PowerShell。
- `【生产服务器】`：通过 SSH 登录 Linux 后使用 Bash。
- `【浏览器】`：在浏览器中人工验收。
- `【需要人工输入】`：密码、TOTP 或确认短语只能交互输入。
- `【只读检查】`：不改变生产状态。
- `【会修改生产环境】`：执行前必须满足前置条件并准备回滚。
- `【危险操作】`：可能造成停机或数据风险，必须由发布负责人确认。

本文用 `<VERSION>`、`<GIT_SHA>`、`<POSTGRES_PASSWORD>` 等表示待替换值。先设置变量，后复制命令；不要把尖括号占位符原样执行。

```bash
# 【生产服务器】每次发布按实际填写，不要永久固定版本。
PMSYSTEM_ROOT=/opt/pmsystem-license
VERSION=<VERSION>
GIT_SHA=<FULL_GIT_SHA>
SHORT_SHA=<SHORT_GIT_SHA>
RELEASE_DIR="${VERSION}-${SHORT_SHA}"
```

真实密码、私钥、TOTP Secret、恢复码和 `.env.production` 内容不得进入本文、Git、聊天、工单或发布日志。

## 第2章 系统架构

```text
PMSystem Windows 客户端 ── HTTPS ──┐
                                   │
用户浏览器                          │
    │                              │
    ▼                              ▼
Nginx / HTTPS（宿主机 80/443）
    ├── /admin/  → /var/www/pmsystem-license/admin（Vue 静态文件）
    └── /api/v1/ → 127.0.0.1:8080
                         │
                         ▼
                    FastAPI API 容器
                         │
                         ▼
                    PostgreSQL 容器
                    （仅内部网络，无宿主机端口）
```

- 授权 API 和管理后台是两个独立可发布组件。
- 客户端只通过 HTTPS 调用授权 API；客户端发布不进入云端发布包。
- PostgreSQL 数据和 Docker Volume 不属于普通软件发布包。
- Alembic 迁移随 API 发布。
- Nginx、DNS 和 HTTPS 通常只在首次部署或明确配置变更时调整。
- API 容器以 UID/GID `10001:10001` 运行，根文件系统只读，签名私钥只读挂载。

## 第3章 目录结构

```text
/opt/pmsystem-license/
├── current -> release/<当前发布目录>
├── release/                     # 不可变历史版本
├── incoming/                    # 上传与解压暂存
├── backups/                     # PostgreSQL custom-format dump
├── config/
│   └── .env.production          # 真实生产配置，禁止进入版本目录
├── secrets/
│   ├── production_ed25519_private.pem
│   └── production_ed25519_public.pem
└── scripts/                     # install-release.sh 复制的运维脚本

/var/www/pmsystem-license/
├── admin
├── admin.backup-<YYYYMMDD-HHMMSS>
└── admin.previous-<SHORT_SHA>
```

`current` 是软链接。发布包先进入 `incoming`，校验后进入新的 `release/<VERSION>-<SHORT_SHA>`；不得覆盖旧版本。生产配置和密钥必须位于版本目录之外。Admin 使用宿主机静态目录，回滚依赖旧版本、旧镜像、Admin 备份和经过验证的数据库备份。

当前实例仅作为示例：

| 项目 | 当前值（2026-08-04） |
|---|---|
| 公网 IP / SSH 别名 | `47.98.206.68` / `pmsystem-prod` |
| 域名 | `license.aixcc.top` |
| current | `/opt/pmsystem-license/release/1.0.5-54dca46` |
| API 镜像 | `pmsystem-license-api:1.0.5-production` |
| Git SHA | `54dca46f9836c0f92e1ed82490f487295ddf62c3` |
| Compose 项目 | `pmsystem-license-production` |
| 服务 | `license-api`、`postgres` |
| 数据库/用户 | `pmsystem_license` / `pmsystem_license` |

## 第4章 账号、权限和敏感信息

实施前准备：云服务器 root 或受控部署账号、SSH 密钥、DNS 管理权限、证书申请权限、密码管理工具、PostgreSQL 密码、Admin 会话密钥、TOTP 加密密钥、授权码及设备凭据 pepper、Ed25519 服务端签名私钥及对应客户端公钥、OWNER 密码和 TOTP 验证器。

- 私钥不得进入 Git、发布包或普通工作站；客户端只能持有公钥。
- `.env.production` 只保存在服务器 `/opt/pmsystem-license/config`，使用 `root:root`、权限 `600`。
- 私钥必须为 `root:10001`、权限 `640`；公钥为 `root:root`、权限 `644`。
- 管理员密码和 TOTP Secret 不得作为命令参数或写入 Shell 历史。
- PostgreSQL 不映射宿主机端口；API 只映射 `127.0.0.1:8080`。
- 安全组和 firewalld 只开放受限 SSH、80、443；禁止开放 5432、8080。
- 当前代码没有独立 `JWT_SECRET`；管理会话使用 `LICENSE_ADMIN_SESSION_SECRET`。不要自行增加未被代码读取的 JWT 变量替代它。

## 第5章 新服务器首次部署前准备

### 5.1 已验证平台与建议范围

仓库 `SERVER-PREPARATION.md` 明确目标为 Alibaba Cloud Linux 3、x86_64。2026-08-04 实例验证版本：Docker 26.1.3、Compose 2.27.0、Nginx 1.24.0、PostgreSQL 17.5-alpine、API 基础 Python 3.12.10。

| 组件 | 当前已验证 | 建议兼容范围 |
|---|---|---|
| OS | Alibaba Cloud Linux 3 x86_64 | 同系列，必须通过 `precheck.sh` |
| Docker | 26.1.3 | 支持 Compose v2、`pull_policy: never` 的受支持版本 |
| Compose | 2.27.0 | Compose v2；不支持旧 `docker-compose` v1 |
| Nginx | 1.24.0 | Alibaba Cloud Linux 3 当前受支持版本 |
| PostgreSQL | 17.5-alpine 容器 | 必须与 `compose.yml` 精确一致 |
| 内存 | 当前 3.5 GiB + 2 GiB swap | 建议至少 4 GiB、保留 swap |
| 磁盘 | 发布前约 67 GiB 可用 | 至少容纳镜像、双版本和备份 |

```bash
# 【生产服务器】【只读检查】
cat /etc/os-release
uname -m
date
date -u
timedatectl status
```

预期 Alibaba Cloud Linux 3、`x86_64`、时钟同步；否则停止。仅在 NTP 未启用时执行：

```bash
# 【生产服务器】【会修改生产环境】
timedatectl set-ntp true
timedatectl status
```

### 5.2 安装 Docker、Compose、Nginx 和工具

仓库不提供操作系统安装脚本。以下命令仅适用于已确认的 Alibaba Cloud Linux 3，不得与 Ubuntu/apt 混用。

```bash
# 【生产服务器】【会修改生产环境】
dnf install -y dnf-plugins-core
dnf config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
dnf install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
dnf install -y nginx firewalld openssl rsync curl tar gzip bind-utils
systemctl enable --now docker nginx firewalld

docker version
docker compose version
nginx -v
systemctl is-active docker nginx firewalld
```

任一验证失败即停止。目标区域无法访问 Docker CE 仓库时，使用组织批准的镜像源或离线 RPM，不得带病部署。

### 5.3 创建目录与防火墙

```bash
# 【生产服务器】【会修改生产环境】
install -d -m 750 /opt/pmsystem-license \
  /opt/pmsystem-license/release \
  /opt/pmsystem-license/incoming \
  /opt/pmsystem-license/backups \
  /opt/pmsystem-license/scripts
install -d -m 700 /opt/pmsystem-license/config \
  /opt/pmsystem-license/secrets
install -d -m 755 /var/www/pmsystem-license/admin \
  /var/www/certbot

firewall-cmd --permanent --add-service=ssh
firewall-cmd --permanent --add-service=http
firewall-cmd --permanent --add-service=https
firewall-cmd --reload
firewall-cmd --list-all
```

如 SSH 使用自定义端口，先确认不会锁断当前会话。执行后确认 5432、8080 未开放。

## 第6章 域名、Nginx、HTTPS 和自动续期

### 6.1 DNS

当前实例将 `license.aixcc.top` A 记录解析至 `47.98.206.68`；新服务器替换为新公网 IP。

```powershell
# 【本地 Windows】【只读检查】
nslookup license.aixcc.top
```

```bash
# 【生产服务器】【只读检查】
dig +short A <LICENSE_DOMAIN>
getent ahostsv4 <LICENSE_DOMAIN>
```

结果不是目标公网 IP 时停止申请证书和上线。

### 6.2 Nginx

仓库 `deploy/production-nginx/nginx/pmsystem-license.conf` 是签证前 HTTP 引导配置。`install-release.sh` 遇到不同的活动配置只写 `.conf.new`，不会覆盖线上 TLS 段。

以下为仓库规则扩展出的脱敏 HTTPS 示例。先用 `nginx -T` 核对活动配置，不得直接覆盖已有证书路径或 Certbot 管理段。

```nginx
server {
    listen 80;
    listen [::]:80;
    server_name <LICENSE_DOMAIN>;
    location ^~ /.well-known/acme-challenge/ {
        root /var/www/certbot;
        try_files $uri =404;
    }
    location / { return 301 https://$host$request_uri; }
}

server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name <LICENSE_DOMAIN>;

    ssl_certificate /etc/letsencrypt/live/<LICENSE_DOMAIN>/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/<LICENSE_DOMAIN>/privkey.pem;
    include /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;

    root /var/www/pmsystem-license;
    client_max_body_size 10m;
    access_log /var/log/nginx/pmsystem-license-access.log;
    error_log /var/log/nginx/pmsystem-license-error.log warn;
    add_header Strict-Transport-Security "max-age=31536000" always;

    location = / { return 302 /admin/; }
    location = /admin { return 301 /admin/; }
    location ^~ /admin/assets/ {
        try_files $uri =404;
        expires 1y;
        add_header Cache-Control "public, immutable" always;
        add_header X-Content-Type-Options "nosniff" always;
    }
    location /admin/ {
        try_files $uri $uri/ /admin/index.html;
        add_header Cache-Control "no-cache" always;
        add_header Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'" always;
        add_header X-Content-Type-Options "nosniff" always;
        add_header Referrer-Policy "strict-origin-when-cross-origin" always;
        add_header Permissions-Policy "camera=(), microphone=(), geolocation=()" always;
        add_header X-Frame-Options "DENY" always;
        add_header Cross-Origin-Opener-Policy "same-origin" always;
        add_header Cross-Origin-Resource-Policy "same-origin" always;
    }
    location /api/v1/ {
        proxy_pass http://127.0.0.1:8080;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_connect_timeout 5s;
        proxy_send_timeout 30s;
        proxy_read_timeout 30s;
        proxy_buffering off;
        add_header Cache-Control "no-store" always;
    }
}
```

保存前备份活动文件；保存后验证：

```bash
nginx -t && systemctl reload nginx
curl -fsSI https://<LICENSE_DOMAIN>/admin/
curl -fsS https://<LICENSE_DOMAIN>/api/v1/health/ready
```

### 6.3 HTTPS 与续期

仓库规定使用发行版支持的 Certbot Nginx 集成，2026-08-04 生产证书确认由 Let’s Encrypt 签发。该次发布记录没有保存活动 Nginx 的 `ssl_certificate` 行和 systemd timer 名称，因此不能凭记录断言具体 timer。以下是 Certbot 默认路径，**只有 `certbot certificates` 与 `nginx -T` 显示一致时才能作为当前真实路径**：

```text
/etc/letsencrypt/live/<LICENSE_DOMAIN>/fullchain.pem
/etc/letsencrypt/live/<LICENSE_DOMAIN>/privkey.pem
```

首次申请前必须满足 DNS 正确、80 可公网访问、HTTP Nginx 配置通过。

```bash
# 【生产服务器】【会修改生产环境】
dnf install -y certbot python3-certbot-nginx
certbot --nginx -d <LICENSE_DOMAIN>
nginx -t && systemctl reload nginx
```

若包不可用，停止并按阿里云 Linux 3 当前官方软件源启用 Certbot；不要使用来源不明脚本。不同 RPM 的 timer 可能是 `certbot-renew.timer` 或 `certbot.timer`，先识别实际单元：

```bash
# 【生产服务器】【只读检查】
systemctl list-unit-files | grep -E '^certbot(-renew)?\.timer'
systemctl list-timers --all | grep -E 'certbot|NEXT|LEFT'
certbot certificates
nginx -T 2>/dev/null | grep -E 'ssl_certificate(_key)? '
```

只启用实际存在者，然后模拟续期：

```bash
# 【生产服务器】【会修改生产环境】二选一
systemctl enable --now certbot-renew.timer
# systemctl enable --now certbot.timer
certbot renew --dry-run
```

用 `systemctl cat <实际service>` 确认成功续期会 reload Nginx。证书检查：

```bash
openssl s_client -connect <LICENSE_DOMAIN>:443 \
  -servername <LICENSE_DOMAIN> </dev/null 2>/dev/null \
  | openssl x509 -noout -subject -issuer -dates
```

## 第7章 生产配置文件

代码只读取 `LICENSE_*` 变量及 Compose 使用的 `PMSYSTEM_API_IMAGE_TAG`、`POSTGRES_*`。不存在通用 `APP_ENV` 或 `ENVIRONMENT`；实际变量是 `LICENSE_ENVIRONMENT=production`。Admin 标签由本地 `VITE_APP_ENV_LABEL=生产环境` 注入，不从服务器 `.env.production` 读取。

```dotenv
PMSYSTEM_API_IMAGE_TAG=<VERSION>-production
POSTGRES_DB=pmsystem_license
POSTGRES_USER=pmsystem_license
POSTGRES_PASSWORD=<POSTGRES_PASSWORD>
LICENSE_DATABASE_URL=postgresql+asyncpg://pmsystem_license:<URL_ENCODED_POSTGRES_PASSWORD>@postgres:5432/pmsystem_license
LICENSE_ENVIRONMENT=production
LICENSE_API_HOST=0.0.0.0
LICENSE_API_PORT=8080
LICENSE_PUBLIC_BASE_URL=https://<LICENSE_DOMAIN>
LICENSE_ADMIN_BASE_URL=https://<LICENSE_DOMAIN>/admin/
LICENSE_ADMIN_ALLOWED_ORIGINS=https://<LICENSE_DOMAIN>
LICENSE_ADMIN_COOKIE_NAME=pms_admin_session
LICENSE_ADMIN_COOKIE_SECURE=true
LICENSE_ADMIN_SESSION_SECRET=<RANDOM_SESSION_SECRET>
LICENSE_ADMIN_TOTP_ENCRYPTION_KEY=<FERNET_KEY>
LICENSE_ADMIN_SESSION_IDLE_MINUTES=30
LICENSE_ADMIN_SESSION_MAX_HOURS=8
LICENSE_ADMIN_LOGIN_MAX_FAILURES=5
LICENSE_ADMIN_LOCKOUT_MINUTES=15
LICENSE_ALLOWED_HOSTS=<LICENSE_DOMAIN>,127.0.0.1,localhost
LICENSE_TRUSTED_PROXY_COUNT=1
LICENSE_CODE_PEPPER=<RANDOM_CODE_PEPPER>
LICENSE_DEVICE_CREDENTIAL_PEPPER=<RANDOM_DEVICE_PEPPER>
LICENSE_SIGNING_KEY_ID=<SIGNING_KEY_ID>
LICENSE_SIGNING_PRIVATE_KEY_PATH=/run/secrets/license_signing_private_key.pem
LICENSE_MINIMUM_CLIENT_VERSION=<MINIMUM_CLIENT_VERSION>
LICENSE_LOG_LEVEL=INFO
LICENSE_OPENAPI_ENABLED=false
LICENSE_RATE_LIMIT_ENABLED=true
LICENSE_REQUEST_MAX_BYTES=10485760
LICENSE_DB_POOL_SIZE=5
LICENSE_DB_MAX_OVERFLOW=5
LICENSE_DB_POOL_TIMEOUT_SECONDS=10
LICENSE_DB_STATEMENT_TIMEOUT_MS=15000
LICENSE_BACKUP_RETENTION_DAYS=30
LICENSE_BUILD_COMMIT=<FULL_GIT_SHA>
LICENSE_SERVICE_VERSION=<VERSION>
```

首次部署必填或由 `init-production.sh` 生成：数据库密码、DATABASE_URL、会话密钥、TOTP 加密密钥、两个 pepper、签名密钥和 key ID。日常发布只允许更新 `PMSYSTEM_API_IMAGE_TAG`、`LICENSE_SERVICE_VERSION`、`LICENSE_BUILD_COMMIT`；不得覆盖其他秘密和策略。

```bash
chown root:root /opt/pmsystem-license/config/.env.production
chmod 600 /opt/pmsystem-license/config/.env.production
```

## 第8章 首次安装授权后端

推荐顺序：上传 production/all 离线包；双层 SHA 校验；解压 staging；转换 Shell 为 LF；运行 `precheck.sh`；加载镜像；首次运行 `init-production.sh`；安装版本；启动 PostgreSQL；执行 Alembic；启动 API；验证 ready；最后创建 OWNER。

| 脚本 | 实际职责 | 边界 |
|---|---|---|
| `precheck.sh` | root、命令、x86_64、Docker/Compose/Nginx、资源、端口、DNS和目录只读检查 | 不创建资源 |
| `load-images.sh` | 校验并加载旧离线包镜像、检查平台 | 仍期望 API 标签 `<VERSION>`；统一构建为 `<VERSION>-production`，不匹配时不要执行 |
| `init-production.sh` | 首次生成 `.env.production`、Ed25519 密钥和随机秘密 | 默认拒绝覆盖；普通发布禁止 `--force` |
| `install-release.sh` | 校验、安装纯版本目录、切 current、同步 Admin、复制脚本、保护 Nginx | 不启动容器；同版本重发会拒绝 |
| `migrate.sh` | 启动/等待 PostgreSQL，执行 `upgrade head` 并显示前后 revision | 不启动 API、不 downgrade |
| `start.sh` | 检查私钥，启动 PostgreSQL/API并等待 healthy | 首次启动前先迁移 |
| `restart.sh` | `compose up -d --pull never` 并等待两个服务 healthy | 不删除 Volume |
| `register-signing-key.sh` | 说明并验证启动时自动注册签名公钥 | 没有独立导入 CLI |
| `verify.sh` | 健康、端口、Admin、Nginx、HTTP/HTTPS检查 | HTTPS 未完成时提示 |
| `deploy.sh` | 旧离线包有序包装 | 统一包须先核对标签/目录兼容性 |

首次安装且 `release/<VERSION>` 不存在时可执行：

```bash
# 【生产服务器】【会修改生产环境】前提：包和包内哈希已通过
cd "/opt/pmsystem-license/incoming/${VERSION}/staging/${PACKAGE_ROOT}"
find scripts -type f -name '*.sh' -exec sed -i 's/\r$//' {} +
find scripts -type f -name '*.sh' -exec bash -n {} \;
bash scripts/precheck.sh

# 按第16章加载镜像；标签不匹配时禁止盲用 load-images.sh。
bash scripts/init-production.sh
bash scripts/install-release.sh "$PWD"
bash /opt/pmsystem-license/current/scripts/migrate.sh
bash /opt/pmsystem-license/current/scripts/start.sh
bash /opt/pmsystem-license/current/scripts/register-signing-key.sh
bash /opt/pmsystem-license/current/scripts/verify.sh
```

执行前条件：镜像标签、生产域名和密钥权限正确。执行后验证：两个容器 healthy、ready 200。失败时停止，不创建 OWNER、不开放生产流量，保留失败目录和日志。

## 第9章 首次部署管理后台

本地可构建 production/admin，或从 production/all 包使用 `admin/`：

```powershell
# 【本地 Windows】
.\scripts\build_cloud_release.ps1 -Environment production -Service admin
```

实际流程执行 `npm ci --ignore-scripts`、类型检查、Vitest 和 `npm run build:production`；Vite base 是 `/admin/`，静态产物位于包内 `admin/`。

```bash
# 【生产服务器】【会修改生产环境】
SHORT_SHA=<SHORT_GIT_SHA>
ADMIN_SOURCE="/opt/pmsystem-license/release/${RELEASE_DIR}/admin"
ADMIN_NEW="/var/www/pmsystem-license/admin.new-${SHORT_SHA}"

test -f "${ADMIN_SOURCE}/index.html" || exit 1
test ! -e "${ADMIN_NEW}" || exit 1
install -d -m 755 "${ADMIN_NEW}"
rsync -a --delete "${ADMIN_SOURCE}/" "${ADMIN_NEW}/"
find "${ADMIN_NEW}" -type d -exec chmod 755 {} +
find "${ADMIN_NEW}" -type f -exec chmod 644 {} +
grep -RIl --binary-files=without-match '生产环境' "${ADMIN_NEW}" >/dev/null || exit 1
! grep -RIlE --binary-files=without-match \
  '开发环境|localhost|127\.0\.0\.1' "${ADMIN_NEW}" >/dev/null || exit 1
grep -oE '/admin/assets/[^" ]+\.(js|css)' "${ADMIN_NEW}/index.html"
```

首次部署可将验证后的目录重命名为 `admin`；日常替换按第18章保留 backup 和 previous。必须验证 `/admin/`、登录页及 index 引用的 JS/CSS 均为 200。

## 第10章 创建首个 OWNER

仅在 API ready、迁移完成且确认不存在 OWNER 后执行：

```bash
# 【生产服务器】【只读检查】
cd /opt/pmsystem-license/current
source scripts/common.sh
load_environment
compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc \
  "SELECT count(*) FROM admin_users WHERE role='OWNER' AND status='ACTIVE';"
```

输出 `0` 才允许创建；大于 0 时禁止再次创建。

```bash
# 【生产服务器】【需要人工输入】【会修改生产环境】
bash /opt/pmsystem-license/current/scripts/create-owner.sh \
  <NON_DEFAULT_USERNAME> "<DISPLAY_NAME>"
```

- 用户名至少 4 位且不能为 `admin`；登录字段是 username。
- 密码由 Python `getpass` 两次输入，终端不回显。
- TOTP Secret 和 provisioning URI 只显示一次；立即录入验证器并保存至批准的离线秘密库。
- 建议在验证器中命名为 `PMSystem-生产环境`、`PMSystem-开发环境`，两者不能混用。
- 不得截图、复制到聊天或保存到普通日志。
- 当前仓库没有 TOTP 重绑脚本，只有密码重置 CLI；TOTP 丢失时必须先开发、审计并测试专用工具，禁止直接修改数据库密文字段。

## 第11章 本地一键打包

双击根目录 `一键打包-云端授权系统.bat`，PowerShell 菜单提供：local/api、local/admin、local/all、production/api、production/admin、production/all 和退出。正式完整发布选择“生产环境 - 全部服务”。

```powershell
# 【本地 Windows】普通完整源码/静态包
.\scripts\build_cloud_release.ps1 -Environment production -Service all

# 离线服务器优先：同时导出 linux/amd64 API 与 PostgreSQL 镜像
.\scripts\build_cloud_release.ps1 `
  -Environment production `
  -Service all `
  -ExportDockerImage
```

- `api`：后端源码、Dockerfile、依赖声明、Alembic，以及有限 API 部署辅助文件。
- `admin`：生产静态文件、Nginx 参考配置和 Admin 部署说明。
- `all`：API 源码、Admin、Compose、全套部署脚本和说明。
- Windows 客户端与 PostgreSQL 数据都不进入上述包。

输出：

```text
artifacts/cloud/<environment>/<service>/
├── PMSystem-License-Cloud-<VERSION>-<environment>-<service>.tar.gz
├── RELEASE-MANIFEST.txt
└── SHA256SUMS.txt
```

版本来自根目录 `VERSION`，并强制与 `license-server/pyproject.toml`、`license-admin/package.json` 和 lock 文件一致。生产构建要求配置分支、干净工作区、测试、HTTPS API、生产标签和敏感信息扫描全部通过。菜单本身不传 `-ExportDockerImage`；需要离线镜像时使用上述命令行。

## 第12章 生产发布前检查

### 12.1 本地检查

```powershell
# 【本地 Windows】【只读检查】
git branch --show-current
git rev-parse HEAD
git status --short
Get-Content .\artifacts\cloud\production\all\RELEASE-MANIFEST.txt
Get-FileHash -Algorithm SHA256 -LiteralPath $Package
tar -tzf $Package | Select-Object -First 50
```

必须确认：分支等于 `scripts/cloud_release_config.psd1` 的 `ProductionBranch`；状态为空；Manifest 为 production/all；版本、Git SHA、API、Admin 标签、包名与 SHA 正确；无 `.env`、私钥、数据库备份或真实秘密。任一不符停止。

### 12.2 服务器检查

```bash
# 【生产服务器】【只读检查】
date
timedatectl status
df -h
free -h
docker ps -a
docker compose ls
nginx -t
readlink -f /opt/pmsystem-license/current
curl -fsS -i https://<LICENSE_DOMAIN>/api/v1/health
curl -fsSI https://<LICENSE_DOMAIN>/admin/
```

预期：时钟同步、空间充足、Docker/Nginx 正常、postgres/API healthy、两个 HTTP 检查为 200。原服务或数据库已异常时停止，先记录并处理原故障。

## 第13章 上传发布包

```powershell
# 【本地 Windows】
$Version = '<VERSION>'
$Service = '<api|admin|all>'
$Package = '<ABSOLUTE_PACKAGE_PATH>'
$Output = Split-Path -Parent $Package
$Incoming = "/opt/pmsystem-license/incoming/$Version"

ssh pmsystem-prod "install -d -m 750 '$Incoming'"
scp -- "$Package" `
  (Join-Path $Output 'RELEASE-MANIFEST.txt') `
  (Join-Path $Output 'SHA256SUMS.txt') `
  "pmsystem-prod:${Incoming}/"
```

```bash
# 【生产服务器】【只读检查】
VERSION=<VERSION>
SERVICE=<api|admin|all>
INCOMING="/opt/pmsystem-license/incoming/${VERSION}"
cd "${INCOMING}"
sha256sum "PMSystem-License-Cloud-${VERSION}-production-${SERVICE}.tar.gz"
cat RELEASE-MANIFEST.txt
tar -tzf "PMSystem-License-Cloud-${VERSION}-production-${SERVICE}.tar.gz" >/dev/null
```

不得上传到 `current`，不得直接覆盖 Admin。必须同时上传 Manifest 和 SHA 文件，服务器哈希必须与本地和 Manifest 一致。

## 第14章 发布前备份

### 14.1 数据库

```bash
# 【生产服务器】【会修改生产环境：只新增备份】
bash /opt/pmsystem-license/current/scripts/backup.sh

BACKUP_FILE=$(find /opt/pmsystem-license/backups -maxdepth 1 -type f -name '*.dump' \
  -printf '%T@ %p\n' | sort -nr | cut -d' ' -f2- | sed -n '1p')
test -s "$BACKUP_FILE"
sha256sum -c "${BACKUP_FILE}.sha256"
bash /opt/pmsystem-license/current/scripts/verify-backup.sh "$BACKUP_FILE"
```

`verify-backup.sh` 会恢复到随机临时数据库，检查 Alembic 和关键表，再删除临时库。必须看到成功日志；否则停止发布。

### 14.2 Admin 与配置

```bash
# 【生产服务器】【会修改生产环境：只新增备份】
BACKUP_TIME=$(date +%Y%m%d-%H%M%S)
cp -a /var/www/pmsystem-license/admin \
  "/var/www/pmsystem-license/admin.backup-${BACKUP_TIME}"
cp -a /opt/pmsystem-license/config/.env.production \
  "/opt/pmsystem-license/config/.env.production.backup-${BACKUP_TIME}"
```

不得在报告中输出配置内容。完整发布建议每次备份配置。

### 14.3 记录回滚锚点

```bash
# 【生产服务器】【只读检查】
readlink -f /opt/pmsystem-license/current
docker inspect -f '{{.Config.Image}} {{.Image}} {{.State.Status}} {{.State.Health.Status}}' \
  pmsystem-license-production-license-api-1
docker inspect -f '{{.Config.Image}} {{.Image}} {{.State.Status}} {{.State.Health.Status}}' \
  pmsystem-license-production-postgres-1
```

同时按第20章记录 OWNER、授权、设备和审计数量。

## 第15章 解压和预检查

```bash
# 【生产服务器】【会修改生产环境：新增版本目录】
VERSION=<VERSION>
SERVICE=<api|admin|all>
SHORT_SHA=<SHORT_GIT_SHA>
PACKAGE_ROOT="PMSystem-License-Cloud-${VERSION}-production-${SERVICE}"
ARCHIVE="/opt/pmsystem-license/incoming/${VERSION}/${PACKAGE_ROOT}.tar.gz"
STAGING="/opt/pmsystem-license/release/.staging-${VERSION}-${SHORT_SHA}"
FINAL="/opt/pmsystem-license/release/${VERSION}-${SHORT_SHA}"

test ! -e "$STAGING" || exit 1
test ! -e "$FINAL" || exit 1
install -d -m 750 "$STAGING"
tar -xzf "$ARCHIVE" --strip-components=1 -C "$STAGING"
cd "$STAGING"
```

先按原包清单校验，再处理执行环境差异：

```bash
sed -i 's/\r$//' SHA256SUMS.txt
sha256sum -c SHA256SUMS.txt
cp SHA256SUMS.txt SHA256SUMS.package.txt

find scripts -type f -name '*.sh' -exec sed -i 's/\r$//' {} +
find scripts -type f -name '*.sh' -exec chmod 755 {} +
find scripts -type f -name '*.sh' -exec bash -n {} \;

# LF 转换后重新建立“服务器工作清单”，并保留原包清单。
find . -type f ! -name 'SHA256SUMS.txt' ! -name 'SHA256SUMS.package.txt' \
  -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS.txt
sha256sum -c SHA256SUMS.txt

mv "$STAGING" "$FINAL"
cd "$FINAL"
bash scripts/precheck.sh
docker compose --project-name pmsystem-license-production \
  --env-file /opt/pmsystem-license/config/.env.production \
  -f compose.yml config --quiet
nginx -t
```

Windows CRLF 可能让 Linux 把清单文件名末尾 `\r` 当作字符；不能因此跳过校验。先核对压缩包 SHA，再仅转换清单；转换 `.sh` 后，原哈希不再描述工作副本，必须保留原清单并记录重新生成原因。出现 `$'\r': command not found` 时只转换 Shell 文件，不批量修改业务文件。

## 第16章 API 发布

### 16.1 路径 A：加载预构建镜像（优先）

`-ExportDockerImage` 生成 `images/pmsystem-production-images-<VERSION>.tar`，API 标签为 `pmsystem-license-api:<VERSION>-production`。

```bash
# 【生产服务器】【会修改生产环境：新增镜像】
IMAGE_TAR=$(find "$FINAL/images" -maxdepth 1 -type f \
  -name 'pmsystem-production-images-*.tar' -print -quit)
test -n "$IMAGE_TAR" || exit 1
docker load --input "$IMAGE_TAR"
docker image inspect "pmsystem-license-api:${VERSION}-production" \
  --format '{{.Id}} {{.Os}}/{{.Architecture}}'
docker image inspect postgres:17.5-alpine \
  --format '{{.Id}} {{.Os}}/{{.Architecture}}'
```

必须为 `linux/amd64`，并保留旧镜像。当前 `load-images.sh` 仍检查 `pmsystem-license-api:<VERSION>`，与统一构建标签不一致；未修复前使用上述明确命令，不得为通过脚本而覆盖旧标签。

### 16.2 路径 B：服务器构建

```bash
# 【生产服务器】【会修改生产环境：构建新镜像】
API_SOURCE="$FINAL/api-source"
test -d "$API_SOURCE" || API_SOURCE="$FINAL/api"
test -f "$API_SOURCE/Dockerfile" || exit 1
docker build --pull=false \
  --tag "pmsystem-license-api:${VERSION}-production" \
  "$API_SOURCE"
docker image inspect "pmsystem-license-api:${VERSION}-production" --format '{{.Id}}'
```

基础镜像不可用或 Docker Hub 超时时，不得切换生产；优先恢复网络、使用批准的镜像源或上传离线镜像。

### 16.3 受控 wheel 应急方案

2026-08-04 因 `python:3.12.10-slim-bookworm` 下载超时，生产未切换；确认新旧后端差异仅为版本元数据且依赖、迁移兼容后，才以已验证旧 API 镜像为基础层安装经哈希校验的新 wheel，生成新不可变标签。

仅当以下全部成立才允许：代码审查证明 wheel 覆盖不遗漏系统包、入口、依赖或镜像层变化；wheel 来自当前 Git SHA 并记录 SHA；Python ABI/依赖兼容；Alembic 随镜像复制；生产变量下应用可导入；UID 10001 可读取只读私钥；生成新标签和镜像 ID；不修改运行中容器、不删除旧镜像。任一条件无法证明即停止。该方案不是常规流程。

## 第17章 Alembic 数据库迁移

`migrate.sh` 从 `PMSYSTEM_ENV_FILE` 读取镜像标签。迁移发生在正式配置切换前时，先建立权限为 600 的生产配置临时副本，只替换三个非敏感版本标识；这样迁移明确使用新镜像，又不会提前改变运行中 API：

```bash
# 【生产服务器】【会修改生产数据库结构】
MIGRATION_ENV="/opt/pmsystem-license/config/.env.production.migrate-${SHORT_SHA}"
test ! -e "$MIGRATION_ENV" || exit 1
cp -a /opt/pmsystem-license/config/.env.production "$MIGRATION_ENV"
sed -i \
  -e "s/^PMSYSTEM_API_IMAGE_TAG=.*/PMSYSTEM_API_IMAGE_TAG=${VERSION}-production/" \
  -e "s/^LICENSE_SERVICE_VERSION=.*/LICENSE_SERVICE_VERSION=${VERSION}/" \
  -e "s/^LICENSE_BUILD_COMMIT=.*/LICENSE_BUILD_COMMIT=${GIT_SHA}/" \
  "$MIGRATION_ENV"
chmod 600 "$MIGRATION_ENV"
PMSYSTEM_ENV_FILE="$MIGRATION_ENV" bash "$FINAL/scripts/migrate.sh"
```

脚本确保 PostgreSQL healthy，执行 `alembic current`、`upgrade head`、`current`。完整发布验证成功并正式更新 `.env.production` 后，才能删除这个精确命名的临时副本。发布前另读 head时也必须指定该临时配置：

```bash
cd "$FINAL"
docker compose --project-name pmsystem-license-production \
  --env-file "$MIGRATION_ENV" -f compose.yml \
  run --rm -T license-api alembic heads </dev/null
```

- current 等于 head：无待执行迁移，upgrade 应为无操作。
- current 落后：先审查迁移、锁表风险、向后兼容性和停机要求。
- 迁移失败：立即停止，不切 current、不启动新 API；先判断事务状态。
- 普通 API 或前端错误不能成为恢复数据库的理由。
- 只有不兼容迁移或确认数据损坏才进入第22章并人工批准。

## 第18章 Admin 生产部署

```bash
# 【生产服务器】【会修改生产环境】
SHORT_SHA=<SHORT_GIT_SHA>
ADMIN_SOURCE="$FINAL/admin"
ADMIN_NEW="/var/www/pmsystem-license/admin.new-${SHORT_SHA}"
ADMIN_PREVIOUS="/var/www/pmsystem-license/admin.previous-${SHORT_SHA}"

test -f "$ADMIN_SOURCE/index.html" || exit 1
test ! -e "$ADMIN_NEW" || exit 1
test ! -e "$ADMIN_PREVIOUS" || exit 1
install -d -m 755 "$ADMIN_NEW"
rsync -a --delete "$ADMIN_SOURCE/" "$ADMIN_NEW/"
find "$ADMIN_NEW" -type d -exec chmod 755 {} +
find "$ADMIN_NEW" -type f -exec chmod 644 {} +
grep -RIl --binary-files=without-match '生产环境' "$ADMIN_NEW" >/dev/null || exit 1
! grep -RIlE --binary-files=without-match \
  '开发环境|localhost|127\.0\.0\.1|<OLD_SERVER_IP>' "$ADMIN_NEW" >/dev/null || exit 1
grep -oE '/admin/assets/[^" ]+\.(js|css)' "$ADMIN_NEW/index.html"

mv /var/www/pmsystem-license/admin "$ADMIN_PREVIOUS"
mv "$ADMIN_NEW" /var/www/pmsystem-license/admin
```

执行前条件：第14章时间戳备份存在，扫描和资源检查通过。执行后验证：index、JS、CSS 和 SPA 路由为 200。失败处理：将失败目录移至 `admin.failed-<SHORT_SHA>`，把 previous 原子移回 `admin`，保留失败目录调查。

API-only 发布不替换 Admin；admin-only 发布不迁移数据库、不切 current、不重启 API/PostgreSQL。

## 第19章 切换 current 和重启

完整或 API 发布仅在镜像、备份、迁移和 Admin 准备全部通过后执行：

```bash
# 【生产服务器】【会修改生产环境】
ln -sfn "/opt/pmsystem-license/release/${RELEASE_DIR}" \
  /opt/pmsystem-license/current
readlink -f /opt/pmsystem-license/current
```

生产 `.env.production` 只允许更新：

```text
PMSYSTEM_API_IMAGE_TAG=<VERSION>-production
LICENSE_SERVICE_VERSION=<VERSION>
LICENSE_BUILD_COMMIT=<FULL_GIT_SHA>
```

应用临时文件保留属主和权限，校验后原子替换；禁止 `cat` 或在日志输出整份生产配置。随后执行：

```bash
bash /opt/pmsystem-license/current/scripts/restart.sh
```

当前脚本执行 `docker compose up -d --pull never`；普通 API 变更通常只重建 API，PostgreSQL 配置未变时应保留原容器。重启后检查两个容器的 `StartedAt`、health 和 `RestartCount`。永远禁止 `docker compose down -v`。

## 第20章 发布后验证

### 20.1 服务端

```bash
# 【生产服务器】【只读检查】
bash /opt/pmsystem-license/current/scripts/status.sh
bash /opt/pmsystem-license/current/scripts/verify.sh
cd /opt/pmsystem-license/current
docker compose --project-name pmsystem-license-production \
  --env-file /opt/pmsystem-license/config/.env.production -f compose.yml ps
docker compose --project-name pmsystem-license-production \
  --env-file /opt/pmsystem-license/config/.env.production -f compose.yml \
  logs --tail=200 license-api
nginx -t
```

预期：两个容器 healthy、API 日志无 ERROR/Traceback、Nginx 通过。

### 20.2 HTTP、端口和版本

```bash
curl -fsS -i https://<LICENSE_DOMAIN>/api/v1/health
curl -fsS -i https://<LICENSE_DOMAIN>/api/v1/health/ready
curl -fsSI https://<LICENSE_DOMAIN>/admin/
curl -fsS -i http://127.0.0.1:8080/api/v1/health
ss -lntp | awk 'NR == 1 || $4 ~ /:(80|443|8080|5432)$/'
```

API JSON 的 version、buildCommit、environment、database 必须符合本次版本、Git SHA、production、ok；8080 只能为 `127.0.0.1:8080`，5432 不应出现宿主机监听。

### 20.3 数据只读计数

表名来自当前 SQLAlchemy 模型：`admin_users`、`licenses`、`device_bindings`、`admin_audit_events`。

```bash
# 【生产服务器】【只读检查】
cd /opt/pmsystem-license/current
source scripts/common.sh
load_environment
compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At <<'SQL'
SELECT 'owner_active', count(*) FROM admin_users
 WHERE role='OWNER' AND status='ACTIVE'
UNION ALL SELECT 'licenses', count(*) FROM licenses
UNION ALL SELECT 'device_bindings', count(*) FROM device_bindings
UNION ALL SELECT 'admin_audit_events', count(*) FROM admin_audit_events
ORDER BY 1;
SELECT 'alembic_revision', version_num FROM alembic_version;
SQL
```

与发布前记录对比。数量意外减少时停止后续写入并进入第23章。

### 20.4 浏览器人工验收

1. 无痕窗口打开 `https://<LICENSE_DOMAIN>/admin/`。
2. 确认显示“生产环境”，无“开发环境”。
3. 用 OWNER username 和密码登录。
4. 输入生产环境对应 TOTP，不要使用开发条目。
5. 检查首页数据。
6. 检查授权列表。
7. 打开创建授权/设备相关页面；没有验收计划时不提交测试数据。
8. 检查版本策略。
9. 检查审计日志。
10. DevTools Network 不得请求 localhost、127.0.0.1 或开发域名。
11. Console 不得有资源、CORS、CSP 或 API 错误。

全部自动验证和人工验收完成后，若本次创建了迁移临时环境副本，确认正式 `.env.production` 已包含相同三个版本标识，再删除精确文件；不得使用通配符：

```bash
# 【生产服务器】【会修改生产环境：删除本次临时秘密副本】
test "$MIGRATION_ENV" = "/opt/pmsystem-license/config/.env.production.migrate-${SHORT_SHA}" || exit 1
rm -f -- "$MIGRATION_ENV"
```

## 第21章 安全回滚

```bash
# 【生产服务器】【危险操作】先填入第14章记录
OLD_RELEASE=<ABSOLUTE_OLD_RELEASE_DIRECTORY>
OLD_IMAGE_TAG=<OLD_API_IMAGE_TAG>
OLD_ADMIN_BACKUP=<ABSOLUTE_ADMIN_BACKUP_OR_PREVIOUS>
ENV_BACKUP=<ABSOLUTE_ENV_BACKUP>
```

执行前条件：停止继续发布；记录失败日志；确认旧代码与当前数据库 schema 兼容。

```bash
# 【生产服务器】【会修改生产环境】
ln -sfn "$OLD_RELEASE" /opt/pmsystem-license/current
readlink -f /opt/pmsystem-license/current

cp -a "$ENV_BACKUP" /opt/pmsystem-license/config/.env.production.restore
mv -f /opt/pmsystem-license/config/.env.production.restore \
  /opt/pmsystem-license/config/.env.production

FAILED_ADMIN="/var/www/pmsystem-license/admin.failed-$(date +%Y%m%d-%H%M%S)"
mv /var/www/pmsystem-license/admin "$FAILED_ADMIN"
cp -a "$OLD_ADMIN_BACKUP" /var/www/pmsystem-license/admin

bash /opt/pmsystem-license/current/scripts/restart.sh
bash /opt/pmsystem-license/current/scripts/verify.sh
curl -fsS https://<LICENSE_DOMAIN>/api/v1/health/ready
curl -fsSI https://<LICENSE_DOMAIN>/admin/
```

执行后验证：旧 current、旧镜像、API/Admin 200、数据库 healthy、数据计数正常。失败则停止反复操作，保留失败版本与日志，升级为事故处理。

普通前端失败不恢复数据库；API 启动失败也不必然恢复数据库。只有不兼容迁移或确认数据损坏才评估第22章。回滚后不得删除失败版本。

## 第22章 数据库恢复（高风险）

> **⚠️ 危险：数据库恢复不是普通应用回滚步骤。恢复旧备份可能覆盖备份之后产生的授权、设备绑定和审计数据。必须停止写入、完成事故审批并由数据库负责人执行。**

允许场景：确认生产数据损坏、不可逆不兼容迁移且无法前向修复、PostgreSQL Volume 损坏。前端故障、502、镜像错误或普通 API 回滚均不允许恢复数据库。

先停止外部写入；可以停止 API，但保持 PostgreSQL 和 Volume：

```bash
# 【生产服务器】【危险操作】只停止 API，不删除容器/Volume
cd /opt/pmsystem-license/current
source scripts/common.sh
load_environment
compose stop license-api
```

验证并恢复到独立临时数据库：

```bash
BACKUP_FILE=/opt/pmsystem-license/backups/<BACKUP_FILE>.dump
sha256sum -c "${BACKUP_FILE}.sha256"
bash /opt/pmsystem-license/current/scripts/verify-backup.sh "$BACKUP_FILE"

# 【需要人工输入】脚本要求输入精确确认短语。
bash /opt/pmsystem-license/current/scripts/restore-postgres.sh \
  "$BACKUP_FILE" \
  pmsystem_license_restore_<INCIDENT_ID>
```

`restore-postgres.sh` 明确拒绝覆盖生产数据库；成功后保留临时库供审查。检查 Alembic revision、关键表、OWNER/授权/设备/审计数量和 ACTIVE signing key。生产库切换属于独立 DBA 变更：必须先保留当前失败数据库和 Volume，制定连接切换、权限、回退和停写方案；仓库没有自动覆盖生产库的脚本，不得临时拼接 `dropdb` 或直接覆盖命令。切换后再核对 Alembic、数据和签名密钥，最后启动 API并验证 ready。

## 第23章 常见故障排查

### 23.1 SHA256SUMS 在 Linux 失败

Windows CRLF 会让文件名尾部出现 `\r`。先直接计算压缩包 SHA 与本地对比，再执行 `sed -i 's/\r$//' SHA256SUMS.txt` 和 `sha256sum -c`。不得跳过哈希。

### 23.2 Shell 出现 `$'\r'`

只对 `scripts/*.sh` 转 LF，再执行 `bash -n`；转换后建立服务器工作清单，不批量修改业务文件。

### 23.3 Docker Hub 基础镜像下载超时

保持旧服务，不切 current。检查 DNS、代理和镜像源，优先上传离线镜像。仅在第16.3全部条件满足时使用受控 wheel 方案。

### 23.4 Admin 仍显示开发环境

核对 Manifest、`VITE_APP_ENVIRONMENT`、`VITE_APP_ENV_LABEL`、dist 扫描、index 引用的 hash 文件、服务器 Admin 目录和浏览器缓存。不要修改压缩 JS。

### 23.5 API 健康但后台打不开

检查 `nginx -t`、`index.html`、目录权限、`/admin/` base path、SPA fallback 和 hash 资源 HTTP 状态。

### 23.6 API 返回 502

```bash
ss -lntp | grep ':8080'
docker compose ps license-api
docker compose logs --tail=200 license-api
nginx -T | grep -A15 'location /api/v1/'
```

确认 proxy_pass 为 `http://127.0.0.1:8080` 且容器 healthy。

### 23.7 PostgreSQL 不健康

检查日志、磁盘、内存、Volume 挂载和健康检查。禁止重建 Volume、`down -v` 或 `docker volume rm`；优先备份和事故恢复。

### 23.8 Alembic revision 不一致

比较 current 与 heads，阅读中间迁移并评估兼容性。current 超前、多 head 或迁移失败时停止，不盲目 downgrade。

### 23.9 OWNER 无法登录

确认 active OWNER 存在、使用 username、账号未 disabled、生产/开发 TOTP 未混淆、NTP 正常。默认连续 5 次失败锁定 15 分钟；不要继续暴力尝试或把密码写入命令。密码恢复使用服务器受控 CLI并审查审计记录；TOTP 重绑当前无现成脚本。

### 23.10 发布后数据数量变化

停止新写入，确认是否连接错误数据库、迁移是否执行、查询条件是否一致，并与备份临时恢复库比较。未确认损坏前不得恢复生产库。

## 第24章 明确禁止操作

> **⚠️ 以下操作禁止用于本系统生产发布。**

| 禁止操作 | 风险 |
|---|---|
| `docker compose down -v` | 删除生产数据库 Volume |
| `docker volume rm ...` | 永久丢失数据库数据 |
| `docker system prune -a` | 删除回滚所需旧镜像 |
| `rm -rf /opt/pmsystem-license` | 删除版本、配置、密钥和备份 |
| `rm -rf /var/lib/postgresql` | 破坏数据库数据 |
| 直接覆盖 `current` | 失去不可变版本和回滚锚点 |
| 无备份直接覆盖 Admin | 无法恢复旧前端 |
| 跳过数据库备份或 SHA | 没有可信恢复点或完整性证据 |
| 迁移失败后继续切换 | 造成代码/schema 不一致 |
| 删除旧版本或旧镜像 | 应用回滚失败 |
| 提交生产 `.env` | 泄露生产秘密 |
| 把私钥打入发布包 | 破坏签名信任 |

## 第25章 发布记录模板

```text
PMSystem 云端授权系统发布记录

发布时间：                 操作人：
发布环境：production       发布服务：api / admin / all
版本：                     Git SHA：
发布包：                   发布包 SHA-256：
Manifest：

原 current：               新 current：
原 API 镜像及 ID：         新 API 镜像及 ID：

数据库备份路径：           大小：
数据库备份 SHA-256：       临时恢复验证：
Admin 备份路径：           生产配置备份路径：

迁移前 revision：          migration head：
迁移后 revision：          是否发生 schema 变化：

发布前 OWNER/授权/设备/审计数量：
发布后 OWNER/授权/设备/审计数量：
API 健康检查：             Admin HTTP：
Nginx/HTTPS：              浏览器人工验收：

发布结果：                 是否回滚：
回滚目标：                 遗留问题：
审批/复核人：
```

## 附录 A 组件单独发布边界

- API-only：备份数据库和配置，加载/构建新镜像，用组件包内迁移脚本和临时环境副本执行 Alembic，再更新当前服务器配置中的三个版本标识并运行原 `current` 的 `restart.sh`；API 组件包不是完整发布目录，不切 current、不替换 Admin。
- Admin-only：备份 Admin，验证 production/admin 包，原子切换静态目录并验证；不迁移数据库、不切 current、不重启 API/PostgreSQL。
- All：按第12至20章完整执行；任一组件失败，整体不得标记成功。

## 附录 B 仓库与生产基线

- 后端：`license-server/`
- 管理后台：`license-admin/`
- 统一版本：`VERSION`
- 构建入口：`一键打包-云端授权系统.bat`
- 构建实现：`scripts/build_cloud_release.ps1`
- Compose：`deploy/production-nginx/compose.yml`
- 部署脚本：`deploy/production-nginx/scripts/`
- Nginx HTTP 引导模板：`deploy/production-nginx/nginx/pmsystem-license.conf`
- 当前 API：`https://license.aixcc.top/api/v1/`
- 当前 Admin：`https://license.aixcc.top/admin/`
