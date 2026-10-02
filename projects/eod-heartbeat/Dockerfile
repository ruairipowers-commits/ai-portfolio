# App / CLI image. Uses the Postgres from docker compose (EOD_DATABASE_URL), not the embedded server.
FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir -e ".[ui,anthropic,aws]"
COPY . .
RUN useradd -m app && chown -R app /app
USER app
EXPOSE 8501
CMD ["sh", "-c", "eodhb all && streamlit run src/eod_heartbeat/ui.py --server.port=8501 --server.address=0.0.0.0 --server.headless=true"]
