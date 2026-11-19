FROM node:22.14.0-alpine

WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend ./

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
