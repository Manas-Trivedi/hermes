# The dashboard as static files behind nginx. Where it finds the feed is decided at run time by a
# config.json mounted next to the page (see deploy/dashboard-config.example.json), not at build time.
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY index.html tsconfig.json vite.config.ts ./
COPY src src
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
