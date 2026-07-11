FROM python:3.11-slim

WORKDIR /app

# --- JOB B fix: LightGBM's compiled C++ core needs libgomp (GNU OpenMP)
# at runtime. python:3.11-slim strips this out to stay small, so
# `import lightgbm` (triggered by joblib.load() in classifier.py) fails
# with "OSError: libgomp.so.1: cannot open shared object file" even
# though the model file itself loads fine. This has nothing to do with
# requirements.txt — libgomp is an OS package, not a pip package.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD exec gunicorn \
    --config gunicorn.conf.py \
    --bind :8080 \
    app:app