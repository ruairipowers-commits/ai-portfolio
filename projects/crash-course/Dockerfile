# Local image: the offline end-to-end run, or the learner site.
#   docker build -t crash-course . && docker run --rm crash-course                 # course all
#   docker run --rm -p 8810:8810 -e HOST=0.0.0.0 crash-course course serve
FROM python:3.11-slim
RUN useradd -m -u 1000 user && install -d -o user -g user /app
WORKDIR /app
COPY --chown=user . .
RUN pip install --no-cache-dir -e ".[ui]"
USER user
CMD ["course", "all"]
