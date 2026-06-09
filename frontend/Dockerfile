FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:22-alpine
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

ENV VITE_API_BASE_URL=http://localhost:8000/api

EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
