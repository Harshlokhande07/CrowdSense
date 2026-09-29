# CrowdSense Production Docker Container
FROM python:3.11-slim

# System dependencies for OpenCV, headless video processing, and networking
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root system user
RUN useradd -m -u 1000 crowdsense

WORKDIR /app

# Install Python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files and ensure non-root ownership
COPY . .
RUN mkdir -p /app/scratch/uploads /app/results && chown -R crowdsense:crowdsense /app

# Switch to non-root user
USER crowdsense

# Expose FastAPI Command Center Port
EXPOSE 8000

ENV HOST=0.0.0.0
ENV PORT=8000
ENV DEMO_MODE=false
ENV PYTHONUNBUFFERED=1

# Container Healthcheck
HEALTHCHECK --interval=20s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1

# Run CrowdSense Dashboard Server
CMD ["python", "dashboard.py", "--host", "0.0.0.0", "--port", "8000"]
