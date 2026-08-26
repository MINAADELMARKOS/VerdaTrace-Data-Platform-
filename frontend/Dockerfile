FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/nginx.conf
COPY . /usr/share/nginx/html
USER nginx
EXPOSE 8080
