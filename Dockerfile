FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Cache-bust: change this value to force Railway to rebuild
ARG CACHEBUST=2026031702

COPY . .

CMD ["python", "bot.py"]
