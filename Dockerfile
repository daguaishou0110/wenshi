FROM python:3.11.9-slim-bookworm

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    OMP_NUM_THREADS=1 \
    ORT_INTRA_THREADS=1 \
    ORT_INTER_THREADS=1 \
    WEB_CONCURRENCY=1 \
    PORT=10000

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY entrypoint.py app.py greenhouse.py detector.py ./
COPY knowledge ./knowledge
COPY static ./static
COPY weights/best.onnx ./weights/best.onnx
RUN mkdir -p logs static/uploads \
    && test -f weights/best.onnx \
    && python -c "import app; print('app-import-ok', app.app.title)"

EXPOSE 10000
# Exec form: Render injects PORT; entrypoint reads it in Python
CMD ["python", "entrypoint.py"]
