# PMSystem 授权管理端

## Production build

`Dockerfile` uses Node 22 LTS only in the build stage, runs `npm ci` and the typed Vite build, then
copies only `dist` into a fixed Caddy runtime image. Production uses `VITE_BASE_PATH=/admin/` and
`VITE_API_BASE_URL=/api/v1` so the portal and API are same-origin. No server secret is a Vite
variable. The administration image and its dependencies are never included in the PMSystem Windows
installer; deployment, CSP, caching, HTTPS, and rollback are documented under `deploy/production`.

独立的网页版授权管理后台，通过 `license-server` 的 `/api/v1/admin` API 工作，不直接连接
PostgreSQL，也不会进入 PMSystem Windows 安装包。

“试用设备”页只用于查看每台设备唯一的 168 小时试用、转正式状态与审计记录。管理端不提供重置、延长或删除试用的操作。

## 技术栈

- Vue 3、TypeScript、Vite
- Vue Router、Pinia
- Element Plus、Axios
- Vitest、Vue Test Utils、Playwright

## 目录

```text
src/api         HTTP 访问层与统一 CSRF/错误处理
src/components  状态标签、页头、确认和激活码结果等通用组件
src/layouts     管理后台整体导航布局
src/router      路由与登录守卫
src/stores      会话和主题状态
src/views       登录、仪表盘、授权、审计、版本和账号页面
tests           前端单元测试
e2e             Playwright 端到端测试
```

## 环境要求

使用 Node.js LTS 与 npm，不混用其他包管理器。`package-lock.json` 是依赖锁定来源。

```powershell
node --version
npm --version
npm install
```

## 环境变量

复制 `.env.example` 为本地 `.env`：

```text
VITE_API_BASE_URL=http://localhost:8000/api/v1
VITE_APP_TITLE=PMSystem授权管理
VITE_APP_ENVIRONMENT=development
```

Vite 变量会进入浏览器构建产物，禁止放入密码、TOTP 密钥、数据库地址、pepper、私钥或
服务端会话密钥。

## 开发与构建

```powershell
npm run dev
npm run build
```

开发地址为 `http://127.0.0.1:5173`，后端必须把该精确来源加入 CORS。生产构建输出到
`dist/`，该目录被 Git 忽略，并与 PMSystem 客户端发布流程完全分离。

## 测试

```powershell
npm run test
npm run test:e2e
```

Vitest 覆盖认证状态、路由安全、错误映射、状态标签和主题；Playwright 覆盖登录、TOTP、
创建授权、列表详情、禁用恢复、解绑、版本策略和退出。

## 安全边界

- 管理端只通过管理员 API 操作授权数据，绝不直连数据库。
- 正式会话令牌只存在 HttpOnly、SameSite=Strict Cookie，前端不写入 localStorage。
- 写操作由 Axios 自动携带 CSRF Cookie 对应的 `X-CSRF-Token`。
- 明文激活码及管理员 TOTP 绑定信息只在创建响应中显示一次，不持久化到浏览器状态。
- 前端隐藏按钮只改善交互，最终角色权限由后端强制校验。
- `.env`、`node_modules/`、`dist/`、Playwright 截图/视频和测试报告均不提交。

## 当前未包含

本阶段不包含生产部署、HTTPS 反向代理、在线支付、自动发卡商城、多租户、客户自助中心
和生产管理员/生产密钥初始化。
