# LEGACY (build desde raíz del paquete).
# Deploy Cloud Build Gen2 usa: onemarketer-api/src/Dockerfile  (--source=onemarketer-api/src)
FROM python:3.10-slim

WORKDIR /app

COPY src/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

WORKDIR /app/src

EXPOSE 8080

CMD ["sh", "-c", "exec functions-framework --target=main --port=${PORT:-8080}"]