FROM python:3.10-slim

WORKDIR /app

# Instalar dependencias
COPY src/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar todo el código
COPY . .

WORKDIR /app/src

EXPOSE 8080

# Cloud Run exige escuchar en $PORT (8080). main() es handler HTTP de Cloud Functions.
CMD ["sh", "-c", "exec functions-framework --target=main --port=${PORT:-8080}"]