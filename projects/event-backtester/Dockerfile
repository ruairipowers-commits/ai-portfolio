# Batch / CLI container (the AWS path runs this on ECS Fargate or AWS Batch). Builds the C++ kernel, then drops the compiler.
FROM python:3.11-slim AS build
RUN apt-get update && apt-get install -y --no-install-recommends build-essential && rm -rf /var/lib/apt/lists/*
WORKDIR /src
COPY . .
RUN pip wheel --no-cache-dir --no-deps -w /wheels .

FROM python:3.11-slim
RUN useradd -m -u 1000 app
WORKDIR /app
COPY --from=build /wheels /wheels
RUN pip install --no-cache-dir /wheels/*.whl && rm -rf /wheels
COPY config config
COPY prompts prompts
COPY evals evals
COPY scripts scripts
USER app
ENTRYPOINT ["event-backtester"]
CMD ["all"]
