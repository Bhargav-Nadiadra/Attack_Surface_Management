FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY pyproject.toml ./
RUN python -c "import tomllib; deps = tomllib.load(open('pyproject.toml', 'rb'))['project']['dependencies']; print('\n'.join(deps))" > requirements.txt \
    && pip install -r requirements.txt


FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

RUN groupadd --system app && useradd --system --gid app --home-dir /app --no-create-home app

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY --chown=app:app alembic.ini pyproject.toml ./
COPY --chown=app:app migrations ./migrations
COPY --chown=app:app app ./app

USER app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]


FROM runtime AS test

USER root
RUN python -c "import tomllib; deps = tomllib.load(open('pyproject.toml', 'rb'))['project']['optional-dependencies']['dev']; print('\n'.join(deps))" > /tmp/requirements-dev.txt \
    && pip install --no-cache-dir --disable-pip-version-check -r /tmp/requirements-dev.txt \
    && rm /tmp/requirements-dev.txt
COPY --chown=app:app tests ./tests
USER app

ENV COVERAGE_FILE=/tmp/.coverage

CMD ["pytest", "-p", "no:cacheprovider", "--cov=app", "--cov-report=term-missing"]
