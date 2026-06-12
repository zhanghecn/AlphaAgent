FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM deps AS dev
WORKDIR /app
COPY . .

ENV VITE_API_BASE_URL=http://localhost:8000/api

EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]

FROM deps AS build
WORKDIR /app
COPY . .
RUN npm run build

FROM nginx:1.27-alpine AS runtime
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY docker-entrypoint.sh /docker-entrypoint.d/99-alphaagent-config.sh
RUN chmod +x /docker-entrypoint.d/99-alphaagent-config.sh

ENV VITE_API_BASE_URL=http://localhost:8000/api

EXPOSE 80
