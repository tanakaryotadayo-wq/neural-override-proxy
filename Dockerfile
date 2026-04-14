FROM python:3.12-slim

WORKDIR /app

# Install dependencies including curl for healthcheck
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-dev.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY prompt_hook.py /app/

# Add a basic healthcheck block
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD curl -f -s -X OPTIONS http://localhost:18008 || exit 1

EXPOSE 18008

ENTRYPOINT ["python3", "prompt_hook.py"]
