FROM node:24-bookworm-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci
COPY . .
RUN npm run build

FROM nginx:1.30-alpine AS runtime
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --chmod=755 docker/40-willay-config.sh /docker-entrypoint.d/
COPY --from=build /app/dist/dashboard/browser /usr/share/nginx/html
EXPOSE 80
