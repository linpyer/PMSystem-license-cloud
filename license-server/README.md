# DDREC License Server

## Production operation

Production deployment is defined under `deploy/production-nginx`. The API runs as a non-root Python
3.12 container behind host Nginx, binds only to host loopback, and does not run Alembic automatically
at startup. Production mode requires HTTPS URLs, Secure cookies, explicit hosts/origins, OpenAPI
disabled, non-development secrets, and a non-development PostgreSQL database. Health endpoints are
split into `/api/v1/health/live` and `/api/v1/health/ready`; readiness checks PostgreSQL and the
configured ACTIVE Ed25519 key. Run `python -m app.cli.cleanup_expired` through a separately reviewed
server timer when periodic cleanup is required. Offline deployment, backup verification, key
handling, Nginx proxy, and disaster recovery procedures are documented in
`deploy/production-nginx/README.md` and `deploy/production-nginx/DISASTER_RECOVERY.md`.

DDREC 激活码系统的独立 FastAPI/PostgreSQL 服务。该目录同时提供客户端授权 API
与网页版管理端 API，
不会读取或修改 DDREC 客户端的 SQLite 数据库、配置或视频目录。

## 当前范围

- PostgreSQL 授权、设备绑定、审计、幂等请求和签名公钥模型。
- 激活、在线验证、刷新、主动解绑和健康检查 API。
- 服务端按 `deviceId + fingerprintVersion` 唯一发放的 168 小时免费试用。
- HMAC-SHA256 激活码与设备凭据摘要。
- Ed25519 规范化 JSON 许可证签名。
- Alembic 可逆迁移。
- 激活码和开发签名密钥 CLI。
- 管理员账号、TOTP、服务端会话、CSRF、角色权限和管理审计。
- 授权创建、状态管理、设备解绑、版本策略和聚合仪表盘 API。
- Docker Compose 本地 PostgreSQL/API 环境。

当前不包含在线支付、生产部署、生产密钥管理和客户自助中心。

## 目录

```text
app/api          HTTP 路由与依赖
app/core         配置、错误、日志、安全和签名原语
app/db           SQLAlchemy 模型与数据库运行时
app/repositories 持久化访问
app/services     授权业务规则
app/cli          开发管理命令
alembic          PostgreSQL 迁移
tests            单元与专用 PostgreSQL 集成测试
```

## 环境变量

复制 `.env.example` 为 `.env` 并替换所有开发示例值。关键变量：

- `LICENSE_DATABASE_URL`：必须为 `postgresql+asyncpg://...`。
- `LICENSE_ENVIRONMENT`：`development`、`test` 或 `production`。
- `LICENSE_SIGNING_PRIVATE_KEY_PATH`：Ed25519 PEM 私钥路径。
- `LICENSE_SIGNING_KEY_ID`：稳定的签名密钥标识。
- `LICENSE_CODE_PEPPER`：激活码 HMAC pepper。
- `LICENSE_DEVICE_CREDENTIAL_PEPPER`：设备凭据 HMAC pepper。
- `LICENSE_API_HOST`、`LICENSE_API_PORT`、`LICENSE_LOG_LEVEL`。
- `LICENSE_OPENAPI_ENABLED`：是否开放 `/docs` 和 OpenAPI JSON。
- `LICENSE_MINIMUM_CLIENT_VERSION`：最低允许的 DDREC 客户端版本。
- `LICENSE_ADMIN_SESSION_SECRET`：管理员会话令牌 HMAC 密钥。
- `LICENSE_ADMIN_TOTP_ENCRYPTION_KEY`：数据库内 TOTP 密钥加密主密钥。
- `LICENSE_ADMIN_ALLOWED_ORIGINS`：精确的管理端 CORS 来源列表。
- `LICENSE_ADMIN_COOKIE_SECURE`：生产 HTTPS 环境必须设为 `true`。

`.env`、`.secrets/` 和私钥均被 Git 忽略。不要把生产密码、pepper 或私钥写入镜像。

## 本地开发

```powershell
cd license-server
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python -m app.cli.generate_dev_keys
Copy-Item .env.example .env
```

如果 API 在宿主机运行，将 `.env` 的 PostgreSQL 主机从 `postgres` 改为
`127.0.0.1:5433`，并把私钥路径改为 `.secrets/dev_ed25519_private.pem`。

## Docker Compose

先生成开发密钥和 `.env`，然后：

```bash
docker compose up --build
```

Compose 创建独立数据库 `ddrec_license_dev`，并由
`scripts/init-test-database.sql` 创建测试专用库 `ddrec_license_test`。它不会挂载
DDREC 用户目录。

## Alembic

```powershell
.venv\Scripts\alembic upgrade head
.venv\Scripts\alembic downgrade -1
```

迁移从空 PostgreSQL 创建授权与管理表、外键、索引及单 ACTIVE 绑定部分唯一索引。

## 管理员初始化

网页不开放注册。首次管理员通过交互式 CLI 创建，密码不会出现在命令行参数或日志中：

```powershell
.venv\Scripts\python -m app.cli.create_admin --username owner --display-name "系统所有者" --role OWNER
.venv\Scripts\python -m app.cli.reset_admin_password --username owner
```

创建时只显示一次 TOTP 密钥和绑定 URI。数据库保存 Argon2id 密码摘要及加密后的 TOTP
密钥，不保存明文密码、明文会话令牌或 CSRF 令牌。

## 创建测试激活码

```powershell
.venv\Scripts\python -m app.cli.create_license --type monthly
.venv\Scripts\python -m app.cli.create_license --type yearly
.venv\Scripts\python -m app.cli.create_license --type permanent
.venv\Scripts\python -m app.cli.create_license --type fixed_date --expires-at 2027-12-31T23:59:59Z
```

完整激活码只在创建命令中显示一次。数据库仅保存 HMAC-SHA256 和脱敏值。

## API

- `GET /api/v1/health`
- `POST /api/v1/licenses/activate`
- `POST /api/v1/trials/activate`
- `POST /api/v1/licenses/verify`
- `POST /api/v1/licenses/deactivate`
- `POST /api/v1/licenses/refresh`

管理 API 基础路径为 `/api/v1/admin`，包括：

- `auth`：密码登录、TOTP 验证、退出、当前账号和修改密码。
- `dashboard/summary`：数据库聚合统计。
- `licenses`：单张/批量创建、列表、详情、资料修改、禁用、恢复和撤销。
- `trials`：试用设备分页、状态/时间/设备筛选、只读详情和可审计禁用。不提供重置、延长或删除试用的接口。
- `bindings/{bindingId}/deactivate`：管理员设备解绑。
- `license-events`、`audit-events`：授权与管理审计。
- `version-policy`：推荐版本和最低支持版本。
- `users`：OWNER 创建、禁用和恢复管理员账号。

管理端使用 HttpOnly、SameSite=Strict Cookie。所有写操作还必须携带 CSRF Cookie 对应的
`X-CSRF-Token`，角色权限始终由后端校验。开发环境仅允许 `.env` 中明确列出的来源。

启用 OpenAPI 时文档位于 `http://localhost:8000/docs`。

## 测试

测试环境必须设置 `LICENSE_ENVIRONMENT=test`，且数据库名称必须以 `_test` 结尾：

```powershell
$env:LICENSE_ENVIRONMENT='test'
$env:LICENSE_DATABASE_URL='postgresql+asyncpg://ddrec_license:password@127.0.0.1:5434/ddrec_license_test'
.venv\Scripts\pytest
```

配置保护会拒绝测试进程连接名称不以 `_test` 结尾的数据库。

## 管理端联调

```powershell
docker compose up -d --build
cd ..\license-admin
npm install
npm run dev
```

浏览器访问 `http://127.0.0.1:5173`。如果 Windows 上另有 IPv4 服务占用
`127.0.0.1:8000`，开发代理可以改用 `http://localhost:8000`，但生产环境应使用固定同域
HTTPS 地址。

## 安全说明

- 开发密钥绝不能用于生产。
- 私钥只从文件系统读取，不进入数据库、Git、日志或 API。
- 激活码和设备凭据只存 HMAC 摘要。
- 日志只记录 traceId、requestId、脱敏码和 deviceId 前缀。
- 生产环境仍需外部密钥管理、TLS、反向代理限流、备份和监控。
