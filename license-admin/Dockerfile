FROM node:22.17.0-bookworm-slim AS builder

WORKDIR /build
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts
COPY index.html tsconfig*.json vite.config.ts vitest.config.ts ./
COPY src ./src
COPY scripts ./scripts
ARG VITE_API_BASE_URL=https://license.aixcc.top/api/v1
ARG VITE_BASE_PATH=/admin/
ARG VITE_APP_TITLE=PMSystem授权管理
ARG VITE_APP_ENVIRONMENT=production
ARG VITE_APP_ENV_LABEL=生产环境
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL \
    VITE_BASE_PATH=$VITE_BASE_PATH \
    VITE_APP_TITLE=$VITE_APP_TITLE \
    VITE_APP_ENVIRONMENT=$VITE_APP_ENVIRONMENT \
    VITE_APP_ENV_LABEL=$VITE_APP_ENV_LABEL
RUN npm run build

FROM caddy:2.10.0-alpine AS runtime
COPY --from=builder /build/dist /srv/admin
