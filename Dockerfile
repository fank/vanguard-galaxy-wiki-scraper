FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    WITH_EXTENSION=0

WORKDIR /app
COPY requirements.txt .
# WITH_EXTENSION=0 forces mwparserfromhell's pure-Python tokenizer so the
# install never needs gcc (slim images don't ship a compiler). Performance
# delta is irrelevant for our 115-page-per-day workload, and this avoids
# breaking on every new Python minor before binary wheels land.
RUN pip install -r requirements.txt
COPY scrape.py .

# Outputs land in /work/out by default. Mount a host directory at /work
# (or /work/out) to persist the CSV/JSON/manifest between runs:
#   docker run --rm -v "$PWD/out:/work/out" ghcr.io/fank/vanguard-galaxy-wiki-scraper
WORKDIR /work
RUN useradd -u 1000 -m scraper && chown scraper:scraper /work
USER scraper

ENTRYPOINT ["python", "/app/scrape.py"]
