# PMSystem License Server

PMSystem 激活码系统第二阶段的后端基础服务。该目录是独立的 FastAPI/PostgreSQL 服务，
不会读取或修改 PMSystem 客户端的 SQLite 数据库、配置或视频目录。

## 当前范围

- PostgreSQL 授权、设备绑定、审计、幂等请求和签名公钥模型。
- 激活、在线验证、刷新、主动解绑和健康检查 API。
- HMAC-SHA256 激活码与设备凭据摘要。
- Ed25519 规范化 JSON 许可证签名。
- Alembic 首版可逆迁移。
- 激活码和开发签名密钥 CLI。
- Docker Compose 本地 PostgreSQL/API 环境。

当前不包含 PMSystem 客户端激活页面、DPAPI 本地许可证、LicenseGate、完整管理后台、
在线支付、生产部署和生产密钥管理。

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
- `LICENSE_MINIMUM_CLIENT_VERSION`：最低允许的 PMSystem 客户端版本。

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

Compose 创建独立数据库 `pmsystem_license_dev`，并由
`scripts/init-test-database.sql` 创建测试专用库 `pmsystem_license_test`。它不会挂载
PMSystem 用户目录。

## Alembic

```powershell
.venv\Scripts\alembic upgrade head
.venv\Scripts\alembic downgrade -1
```

首版迁移从空 PostgreSQL 创建全部五张表、外键、索引及单 ACTIVE 绑定部分唯一索引。

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
- `POST /api/v1/licenses/verify`
- `POST /api/v1/licenses/deactivate`
- `POST /api/v1/licenses/refresh`

启用 OpenAPI 时文档位于 `http://localhost:8000/docs`。

## 测试

测试环境必须设置 `LICENSE_ENVIRONMENT=test`，且数据库名称必须以 `_test` 结尾：

```powershell
$env:LICENSE_ENVIRONMENT='test'
$env:LICENSE_DATABASE_URL='postgresql+asyncpg://pmsystem_license:password@127.0.0.1:5434/pmsystem_license_test'
.venv\Scripts\pytest
```

配置保护会拒绝测试进程连接名称不以 `_test` 结尾的数据库。

## 安全说明

- 开发密钥绝不能用于生产。
- 私钥只从文件系统读取，不进入数据库、Git、日志或 API。
- 激活码和设备凭据只存 HMAC 摘要。
- 日志只记录 traceId、requestId、脱敏码和 deviceId 前缀。
- 生产环境仍需外部密钥管理、TLS、反向代理限流、备份和监控。
