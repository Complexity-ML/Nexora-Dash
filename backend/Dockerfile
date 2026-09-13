FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends default-jre-headless && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app app
COPY alembic.ini .
COPY migrations migrations
COPY scripts scripts
COPY pytest.ini .
RUN mkdir -p /var/lib/nexora
CMD ["sh", "-c", "alembic upgrade head && gunicorn app.main:server --bind 0.0.0.0:8050 --workers 2 --threads 4 --timeout 120"]
