FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

ARG CACHEBUST=1
COPY . .

RUN chainlit init 2>/dev/null || true

ENV HOME=/tmp
ENV HF_HOME=/tmp/hf_cache
ENV TRANSFORMERS_CACHE=/tmp/hf_cache
RUN mkdir -p /tmp/hf_cache /app/.files && chmod -R 777 /tmp /app/.files

EXPOSE 8000

CMD ["chainlit", "run", "app.py", "--host", "0.0.0.0", "--port", "8000"]
