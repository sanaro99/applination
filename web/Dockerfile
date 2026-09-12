# syntax=docker/dockerfile:1
# Applination frontend — Next.js 16 standalone server on :3000

FROM node:22-alpine AS base
RUN apk add --no-cache libc6-compat

FROM base AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM base AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

# BUILD-TIME, and it ships to the browser. Next inlines NEXT_PUBLIC_* into the
# client bundle, so setting this on the NAS does nothing — it must be baked in
# here. Same-origin by default: Traefik routes /api and /files on this same
# hostname through to the backend container.
ARG NEXT_PUBLIC_API_BASE=https://applination.sanchitarora.me
ENV NEXT_PUBLIC_API_BASE=$NEXT_PUBLIC_API_BASE
# Kept in both images so the build metadata is available for image inspection.
# The Config page fetches the authoritative runtime value from /api/version.
ARG APPLINATION_VERSION=0.1.1
ARG APPLINATION_BUILD_SHA=dev
ENV APPLINATION_VERSION=$APPLINATION_VERSION \
    APPLINATION_BUILD_SHA=$APPLINATION_BUILD_SHA
ENV NEXT_TELEMETRY_DISABLED=1

RUN npm run build

FROM base AS runner
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0 \
    TZ=America/Los_Angeles

RUN addgroup --system --gid 1001 nodejs && adduser --system --uid 1001 nextjs

COPY --from=build /app/public ./public
COPY --from=build --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=build --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs
EXPOSE 3000
CMD ["node", "server.js"]
