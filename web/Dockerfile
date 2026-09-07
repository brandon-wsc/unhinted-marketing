# syntax=docker/dockerfile:1
# SPA image (ADR 0023). VITE_DEPLOYMENT_MODE is substituted into the bundle by
# `vite build` — rebuilding is the only way to change it. Build from repo root:
#   docker build -f web/Dockerfile -t unhinted-web:onprem web
#   docker build -f web/Dockerfile --build-arg VITE_DEPLOYMENT_MODE=cloud -t unhinted-web:cloud web
FROM node:22-alpine AS build

WORKDIR /app

ARG VITE_DEPLOYMENT_MODE=onprem
ENV VITE_DEPLOYMENT_MODE=${VITE_DEPLOYMENT_MODE}

RUN corepack enable
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY . .
RUN pnpm run build

FROM nginx:alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
