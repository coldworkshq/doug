# Built from the repo root (npm workspaces). CI and gcp.sh must use:
#   docker build -f web/Dockerfile .
# App-dir context (`docker build web`) cannot see the root lockfile.
ARG NODE_IMAGE=node:22-alpine@sha256:c610fcdfb1d5b4740dd70c284ed3cb16bb857e0f7166196e36a5501df7a3aa32

FROM ${NODE_IMAGE} AS builder
WORKDIR /app
COPY package.json package-lock.json ./
COPY web ./web
COPY console/package.json ./console/
# npm workspaces + `npm ci` skips optional native bindings of nested deps
# (npm/cli#4828). Install the Alpine musl bindings for this TARGETARCH after.
ARG TARGETARCH
RUN npm ci \
 && case "$TARGETARCH" in \
      arm64) NATIVE="@tailwindcss/oxide-linux-arm64-musl lightningcss-linux-arm64-musl" ;; \
      *)     NATIVE="@tailwindcss/oxide-linux-x64-musl lightningcss-linux-x64-musl" ;; \
    esac \
 && npm install --no-save --workspace=web --workspace=console $NATIVE \
 && npm run build --workspace=web

FROM ${NODE_IMAGE}
WORKDIR /app
ENV NODE_ENV=production
# outputFileTracingRoot is the monorepo root, so standalone nests under web/.
COPY --from=builder /app/web/.next/standalone ./
COPY --from=builder /app/web/.next/static ./web/.next/static
COPY --from=builder /app/web/public ./web/public
ENV PORT=3000
EXPOSE 3000
CMD ["node", "web/server.js"]
