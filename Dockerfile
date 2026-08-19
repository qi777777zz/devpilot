FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

RUN useradd --create-home --uid 10001 devpilot \
    && mkdir -p /app/var /workspace \
    && chown -R devpilot:devpilot /app /workspace

USER devpilot
EXPOSE 8000
CMD ["uvicorn", "devpilot.api:app", "--host", "0.0.0.0", "--port", "8000"]

