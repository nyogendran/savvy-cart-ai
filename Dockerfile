FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8080

WORKDIR /app

COPY pyproject.toml ./
COPY src ./src
COPY fixtures ./fixtures

# Editable install keeps src/ next to fixtures/, which the app resolves relative to its source.
RUN pip install -e . "uvicorn>=0.30" \
    && useradd --create-home --uid 10001 app

USER app
EXPOSE 8080

CMD exec uvicorn savvycart.http:app --host 0.0.0.0 --port ${PORT:-8080}
