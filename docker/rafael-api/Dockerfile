FROM python:3.12-slim-bookworm

RUN apt-get update \
  && apt-get install -y --no-install-recommends \
       tesseract-ocr \
       tesseract-ocr-heb \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY api /app/api

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

EXPOSE 8080

CMD ["sh", "-c", "exec uvicorn api.index:app --host 0.0.0.0 --port ${PORT:-8080}"]
