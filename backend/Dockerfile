FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg git curl build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
COPY pipeline/requirements.txt /app/pipeline-requirements.txt
RUN python -m pip install --upgrade pip \
    && python -m pip install -r /app/requirements.txt \
    && python -m pip install -r /app/pipeline-requirements.txt

COPY app /app/app
COPY pipeline /app/pipeline
COPY data /app/data
COPY tools /app/tools

ENV PIPELINE_ROOT=/app/pipeline \
    PIPELINE_RUNS_DIR=/app/pipeline/runs

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
