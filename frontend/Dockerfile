FROM node:24-alpine AS builder
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html

# Files in /etc/nginx/templates are env-substituted into /etc/nginx/conf.d
# by the base image's entrypoint at container start.
COPY nginx.conf.template /etc/nginx/templates/default.conf.template

# Defaults for local runs; Cloud Run overrides both.
ENV PORT=8080
ENV BACKEND_URL=http://backend:8080

EXPOSE 8080
