FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir -e ".[anthropic,openai,aws]"
COPY . .
RUN useradd -m app && chown -R app /app
USER app
EXPOSE 8000
# Build the sample corpus and index, then serve the API (OpenAPI docs at /docs).
CMD ["sh", "-c", "rqa data && rqa ingest && rqa serve --host 0.0.0.0 --port 8000"]
