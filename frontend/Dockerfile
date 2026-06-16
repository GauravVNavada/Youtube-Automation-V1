FROM nginx:1.27-alpine

COPY nginx/default.conf /etc/nginx/conf.d/default.conf
COPY frontend/dist /usr/share/nginx/html
COPY playground/ui/dist /usr/share/nginx/html/playground

EXPOSE 80
