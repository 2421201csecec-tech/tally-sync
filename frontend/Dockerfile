FROM node:22-alpine
WORKDIR /app
ARG BACKEND_URL=http://localhost:8000
ENV BACKEND_URL=$BACKEND_URL
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build
EXPOSE 3000
CMD ["npm", "run", "start"]
