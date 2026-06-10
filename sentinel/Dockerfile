FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    git \
    patch \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY sentinel/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN playwright install chromium --with-deps

COPY sentinel/ ./sentinel/

ENV PYTHONUNBUFFERED=1
CMD ["python", "-m", "sentinel.main"]
