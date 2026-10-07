FROM python:3.11-slim
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir -e ".[anthropic,aws,hub,api,mcp,orchestration]"
RUN useradd -m app && chown -R app /app
USER app
ENTRYPOINT ["dlp"]
CMD ["all"]
