FROM python:3.10-slim

WORKDIR /app

# Instalar dependencias
COPY src/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar todo el código
COPY . .

WORKDIR /app/src

EXPOSE 8080

# Imagen opcional para pruebas locales con functions-framework (no usada en cloudbuild).
CMD ["sh", "-c", "exec functions-framework --target=main --port=${PORT:-8080}"]