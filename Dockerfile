# Python backend with Playwright + Chromium
FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

WORKDIR /app

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers (Chromium only)
RUN playwright install chromium

# Copy source
COPY . .

# Create output dir for DB + logs
RUN mkdir -p output

# Railway sets PORT env var
ENV PORT=8000

CMD uvicorn api.app:app --host 0.0.0.0 --port ${PORT}
