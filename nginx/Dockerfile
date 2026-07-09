# ---- stage 1: build the Svelte frontend ----
FROM node:20-alpine AS build
WORKDIR /app
COPY frontend/package.json ./
RUN npm install
COPY frontend/ ./
# built to be served under /latest/ and to call the API at /api
ENV VITE_BASE=/latest/
ENV VITE_API_BASE=/api
RUN npm run build          # -> /app/dist

# ---- stage 2: nginx runtime ----
FROM nginx:alpine
RUN rm /etc/nginx/conf.d/default.conf
COPY nginx/nginx.conf /etc/nginx/conf.d/default.conf

# new app under /latest, old page under /old
COPY --from=build /app/dist/ /usr/share/nginx/html/latest/
COPY legacy/tcp_simulator.html /usr/share/nginx/html/old/index.html

EXPOSE 80
