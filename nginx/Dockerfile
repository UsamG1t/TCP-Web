FROM nginx:alpine

# Remove default config
RUN rm /etc/nginx/conf.d/default.conf

# Copy custom config
COPY nginx.conf /etc/nginx/conf.d/

# Copy frontend static files
COPY --from=frontend /app/ /var/www/tcp-simulator/

EXPOSE 80 443
