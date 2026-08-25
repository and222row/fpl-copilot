FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Hosts inject the port they want the container to listen on ($PORT on Render,
# Fly and Railway); 8000 is the local fallback. Shell form, not exec form, so
# the variable is actually expanded rather than passed as the literal "$PORT".
#
# No --reload: it watches the filesystem and doubles memory for nothing in
# production, and the free tiers are memory-constrained.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
