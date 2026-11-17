# Batch / CLI container (the AWS path runs this on ECS Fargate). Builds the Rust engine, then drops the toolchain.
FROM python:3.11-slim-bookworm AS build
RUN apt-get update && apt-get install -y --no-install-recommends build-essential && rm -rf /var/lib/apt/lists/*
# Toolchain from the official Rust image (no piped install script), same Debian release as the Python base.
COPY --from=rust:1-slim-bookworm /usr/local/rustup /usr/local/rustup
COPY --from=rust:1-slim-bookworm /usr/local/cargo /usr/local/cargo
ENV RUSTUP_HOME=/usr/local/rustup CARGO_HOME=/usr/local/cargo PATH=/usr/local/cargo/bin:$PATH
RUN pip install --no-cache-dir maturin
WORKDIR /src
COPY . .
RUN maturin build --release -o /wheels

FROM python:3.11-slim-bookworm
RUN useradd -m -u 1000 app
WORKDIR /app
COPY --from=build /wheels /wheels
RUN pip install --no-cache-dir /wheels/*.whl && rm -rf /wheels
COPY config config
COPY prompts prompts
COPY evals evals
COPY scripts scripts
USER app
ENTRYPOINT ["lob-matching-engine"]
CMD ["all"]
