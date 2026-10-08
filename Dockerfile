FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Kolkata

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
 && python -m playwright install --with-deps chromium \
 && rm -rf /var/lib/apt/lists/*

COPY aieditor ./aieditor
COPY assets ./assets
COPY editions ./editions

# One run = research the 24h ending now, build PDF + PPTX, email them, exit.
CMD ["python", "-m", "aieditor.daily"]
