# syntax=docker/dockerfile:1

# ---- deps: installed once, shared by the dev and build stages -------------
FROM node:20-slim AS deps
WORKDIR /app
COPY package.json package-lock.json ./
# npm's postinstall (copy-pdfjs-assets.mjs) needs the rest of scripts/ present.
COPY scripts ./scripts
RUN npm ci

# ---- dev: what docker-compose.yml runs for local development --------------
# Source is bind-mounted over this in compose; the copy below only matters for
# `docker build --target dev` run standalone, without the mount.
FROM deps AS dev
COPY . .
EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]

# ---- build: compiles static assets for the production image ---------------
FROM deps AS build
COPY . .
# VITE_API_URL is baked into the bundle at build time, so it must be supplied
# as a build arg pointing at the URL the browser can reach, not a compose
# service name — same constraint as the dev stage's environment variable.
ARG VITE_API_URL
ENV VITE_API_URL=${VITE_API_URL}
RUN npm run build

# ---- prod: static assets served by nginx -----------------------------------
FROM nginx:1.27-alpine AS prod
COPY nginx.conf /etc/nginx/nginx.conf
COPY --from=build /app/dist /usr/share/nginx/html
RUN adduser -D -u 10001 app \
    && chown -R app:app /usr/share/nginx/html /var/cache/nginx
USER app
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD wget -q -O- http://127.0.0.1:8080/ >/dev/null || exit 1
CMD ["nginx", "-g", "daemon off;"]
