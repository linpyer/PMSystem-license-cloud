FROM node:22.17.0-bookworm-slim AS builder

WORKDIR /build
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts
COPY index.html tsconfig*.json vite.config.ts vitest.config.ts ./
COPY src ./src
ARG VITE_API_BASE_URL=/api/v1
ARG VITE_BASE_PATH=/admin/
ARG VITE_APP_TITLE=PMSystem License Administration
ARG VITE_APP_ENVIRONMENT=production
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL \
    VITE_BASE_PATH=$VITE_BASE_PATH \
    VITE_APP_TITLE=$VITE_APP_TITLE \
    VITE_APP_ENVIRONMENT=$VITE_APP_ENVIRONMENT
RUN npm run build

FROM caddy:2.10.0-alpine AS runtime
COPY --from=builder /build/dist /srv/admin
