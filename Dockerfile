FROM python:3.12-slim

# ping para el chequeo de conectividad y zona horaria para mostrar bien las fechas
RUN apt-get update \
 && apt-get install -y --no-install-recommends iputils-ping tzdata \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py monitor.py avisos.py ./
COPY templates ./templates
COPY static ./static

ENV PYTHONUNBUFFERED=1 \
    BACKUP_CONFIG=/app/config/config.json \
    BACKUP_DATOS=/app/data
EXPOSE 5050
CMD ["python", "app.py"]
