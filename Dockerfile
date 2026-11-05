FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY . .
RUN uv run --no-dev python manage.py collectstatic --noinput

EXPOSE 8080

CMD ["uv", "run", "--no-dev", "gunicorn", "config.wsgi:application", \
     "--bind", "0.0.0.0:8080", "--workers", "2", "--timeout", "60"]
