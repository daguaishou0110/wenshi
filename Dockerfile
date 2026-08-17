FROM python:3.11.9-slim-bookworm

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    OMP_NUM_THREADS=1 \
    ORT_INTRA_THREADS=1 \
    ORT_INTER_THREADS=1 \
    WEB_CONCURRENCY=1

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY . .
RUN chmod +x start.sh \
    && mkdir -p logs static/uploads \
    && test -f weights/best.onnx

EXPOSE 10000
CMD ["./start.sh"]
