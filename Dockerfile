FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

# Set timezone (Asia/Shanghai)
ENV TZ=Asia/Shanghai

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Create volume mount points
RUN mkdir -p /app/data /app/dist

EXPOSE 8080

CMD ["python", "main.py", "--daemon", "--config", "config.yaml", "--port", "8080"]
