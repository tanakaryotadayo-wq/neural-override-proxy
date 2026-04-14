FROM python:3.12-slim

WORKDIR /app

# TODO: Install dependencies 
# RUN apt-get update && apt-get install -y ...

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# TODO: Copy prompt_hook.py and other necessary files
COPY prompt_hook.py .

# TODO: Configure Healthcheck
# HEALTHCHECK CMD ...

EXPOSE 18008

ENTRYPOINT ["python3", "prompt_hook.py"]
