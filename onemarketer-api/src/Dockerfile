# Cloud Functions Gen2 / Cloud Run (source = onemarketer-api/src)
FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1
EXPOSE 8080

CMD ["sh", "-c", "exec functions-framework --target=main --port=${PORT:-8080}"]
