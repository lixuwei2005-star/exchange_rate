# Multi-stage. `dev` target is used by docker-compose.yml (hot reload).
# `prod` target is used by docker-compose.prod.yml on the OCI server.

FROM node:20-alpine AS deps
ENV NEXT_TELEMETRY_DISABLED=1
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install --no-audit --no-fund

# -----------------------------------------------------------------------------
# dev: bind-mounted source, next dev
# -----------------------------------------------------------------------------
FROM node:20-alpine AS dev
ENV NEXT_TELEMETRY_DISABLED=1
WORKDIR /app
EXPOSE 3000
CMD ["npm", "run", "dev"]

# -----------------------------------------------------------------------------
# prod: copy source, build, start
# -----------------------------------------------------------------------------
FROM node:20-alpine AS prod
ENV NEXT_TELEMETRY_DISABLED=1 NODE_ENV=production
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build
EXPOSE 3000
CMD ["npm", "run", "start"]
