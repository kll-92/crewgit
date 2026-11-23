# syntax=docker/dockerfile:1
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install .

RUN useradd --create-home --uid 10001 crew
USER crew

# Mount a repository that already has .crewgit/ initialized.
WORKDIR /workspace
EXPOSE 7878

ENTRYPOINT ["crewgit"]
CMD ["serve", "--host", "0.0.0.0", "--port", "7878", "--read-only"]
