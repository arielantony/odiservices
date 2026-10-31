# syntax=docker/dockerfile:1
# The web image: nginx serves the built React app and proxies /api and
# /healthz to the api image (OPS-01 spec). Build context is app/web. Base
# digests change only by a deliberate PR.

FROM node:24-bookworm-slim@sha256:c86ecead9e55a5210ac1727de38a4ca840bf03dcaf34dc9749addbf383b1920c AS build
WORKDIR /build
RUN corepack enable
COPY package.json yarn.lock .yarnrc.yml ./
RUN yarn install --immutable
COPY index.html vite.config.ts tsconfig.json ./
COPY src ./src
RUN yarn build

FROM nginxinc/nginx-unprivileged:stable-bookworm@sha256:cd33960e98e93d4d63385790ff7f8f5bf2ca95184c581b7f42ae8aea1139fbfc
ENV API_UPSTREAM=api:8000 \
    API_RESOLVER=127.0.0.11
COPY nginx/headers.conf /etc/nginx/headers.conf
COPY nginx/csp-page.conf /etc/nginx/csp-page.conf
COPY nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /build/dist /usr/share/nginx/html
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD ["curl", "-fs", "-o", "/dev/null", "http://127.0.0.1:8080/"]
