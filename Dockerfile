# CrowdSense Production Docker Container
FROM python:3.11-slim

# System dependencies for OpenCV, GUI & video streaming
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . .

# Expose FastAPI Command Center Port
EXPOSE 8000

ENV HOST=0.0.0.0
ENV PORT=8000
ENV DEMO_MODE=false

# Run CrowdSense Dashboard Server
CMD ["python", "dashboard.py", "--host", "0.0.0.0", "--port", "8000"]
