FROM node:22-alpine AS ui
WORKDIR /frontend
COPY frontend/package.json ./
RUN npm install --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY backend/app/ /app/app/
COPY --from=ui /frontend/dist/ /app/public/
EXPOSE 8091
CMD ["uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8091", "--no-server-header"]
