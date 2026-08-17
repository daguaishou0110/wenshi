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

COPY app.py greenhouse.py detector.py ./
COPY knowledge ./knowledge
COPY static ./static
COPY weights ./weights
RUN mkdir -p logs static/uploads \
    && test -f weights/best.onnx \
    && python -c "import fastapi,uvicorn,numpy,PIL; print('imports-ok')"

# Shell form so $PORT expands; avoid start.sh CRLF issues on Windows commits
CMD python -m uvicorn app:app --host 0.0.0.0 --port ${PORT:-10000} --workers 1 --log-level info
