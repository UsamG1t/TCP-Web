FROM nginx:alpine

# Remove default config
RUN rm /etc/nginx/conf.d/default.conf

# Copy custom config
COPY nginx/nginx.conf /etc/nginx/conf.d/default.conf

# Copy frontend static files
COPY frontend/ /var/www/tcp-simulator/

EXPOSE 80 443
