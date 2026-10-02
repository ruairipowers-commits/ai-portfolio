FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir -e ".[postgres]"
COPY . .
RUN useradd -m app && chown -R app /app
USER app
ENV HOST=0.0.0.0 PORT=8600
EXPOSE 8600
CMD ["govconsole", "serve"]
