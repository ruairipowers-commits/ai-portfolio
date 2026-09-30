FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir -e ".[anthropic,openai,aws]"
COPY . .
RUN useradd -m app && chown -R app /app
USER app
ENTRYPOINT ["altdata-triage"]
CMD ["all"]
