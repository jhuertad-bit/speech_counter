FROM python:3.10-slim

WORKDIR /app

# Instalar dependencias
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt uvicorn

# Copiar todo el código
COPY . .

EXPOSE 8080

# Ignoramos el if __name__ y levantamos la app con uvicorn en el puerto de GCP
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port $PORT"]