FROM node:20-alpine AS playground_build

WORKDIR /app
COPY playground/ui/package*.json ./
RUN npm ci
COPY playground/ui ./
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx/nginx.conf /etc/nginx/nginx.conf
COPY --from=playground_build /app/dist /usr/share/nginx/html/playground
EXPOSE 80
