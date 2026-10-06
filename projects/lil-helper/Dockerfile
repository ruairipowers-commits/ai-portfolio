# The household server: the API the phone app talks to, plus the weekly jobs. Runs at home (the EVO-X1).
#   docker build -t lil-helper . && docker run -p 8650:8650 --env-file .env \
#     -v $PWD/config/household.yaml:/app/config/household.yaml:ro -v lilhelper-data:/app/warehouse lil-helper
# The real household file is mounted read-only and never baked into the image; the database lives in a volume.
FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b \
      fonts-dejavu-core && rm -rf /var/lib/apt/lists/* \
    && useradd -m -u 1000 user && install -d -o user -g user /app
ENV HOME=/home/user PATH=/home/user/.local/bin:$PATH PYTHONUNBUFFERED=1
WORKDIR /app
COPY --chown=user . .
RUN rm -rf app && mkdir -p warehouse output logs && chown -R user /app
USER user
RUN pip install --no-cache-dir --user -e ".[anthropic,openai]"
# Production: refuses to sign anything without HELPER_SECRET; the scheduler runs in this process
ENV HELPER_ENV=production HELPER_SCHEDULER=1 HOST=0.0.0.0 PORT=8650
EXPOSE 8650
CMD ["helper", "serve"]
