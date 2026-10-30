FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg fonts-noto-core ghostscript libcairo2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml requirements.txt ./
COPY frameforge_engine ./frameforge_engine
RUN python -m pip install --no-cache-dir .

RUN useradd --create-home --uid 10001 frameforge \
    && mkdir -p /app/.runtime \
    && chown -R frameforge:frameforge /app
USER frameforge

EXPOSE 8000
CMD ["python", "-m", "frameforge_engine.server"]

