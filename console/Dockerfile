# Built from the repo root (npm workspaces). CI and gcp.sh must use:
#   docker build -f console/Dockerfile .
# App-dir context (`docker build console`) cannot see the root lockfile.
ARG NODE_IMAGE=node:22-alpine@sha256:c610fcdfb1d5b4740dd70c284ed3cb16bb857e0f7166196e36a5501df7a3aa32

FROM ${NODE_IMAGE} AS builder
WORKDIR /app
COPY package.json package-lock.json ./
COPY console ./console
COPY web/package.json ./web/
# npm workspaces + `npm ci` skips optional native bindings of nested deps
# (npm/cli#4828). Direct optionalDependencies cover CI (gnu); Alpine still
# needs an explicit musl install. Versions are read from console/package.json
# so they cannot drift from the optionalDependencies pins.
# TARGETARCH is BuildKit-only — fall back to uname so a legacy builder on
# arm64 does not silently grab x64 wheels.
ARG TARGETARCH=
RUN npm ci \
 && arch="${TARGETARCH}" \
 && if [ -z "$arch" ]; then \
      case "$(uname -m)" in aarch64|arm64) arch=arm64 ;; *) arch=amd64 ;; esac; \
    fi \
 && case "$arch" in arm64) cpu=arm64 ;; *) cpu=x64 ;; esac \
 && oxide_v=$(node -p "require('./console/package.json').optionalDependencies['@tailwindcss/oxide-linux-'+'${cpu}'+'-musl']") \
 && lcss_v=$(node -p "require('./console/package.json').optionalDependencies['lightningcss-linux-'+'${cpu}'+'-musl']") \
 && npm install --no-save --workspace=web --workspace=console \
      "@tailwindcss/oxide-linux-${cpu}-musl@${oxide_v}" \
      "lightningcss-linux-${cpu}-musl@${lcss_v}" \
 && npm run build --workspace=console

FROM ${NODE_IMAGE}
WORKDIR /app
ENV NODE_ENV=production
# outputFileTracingRoot is the monorepo root, so standalone nests under console/.
# public/ is not inside standalone — copy it beside server.js explicitly.
COPY --from=builder /app/console/.next/standalone ./
COPY --from=builder /app/console/.next/static ./console/.next/static
COPY --from=builder /app/console/public ./console/public
ENV PORT=3000
EXPOSE 3000
CMD ["node", "console/server.js"]
