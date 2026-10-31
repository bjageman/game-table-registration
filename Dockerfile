FROM python:3.12-slim AS api
WORKDIR /app
RUN pip install --no-cache-dir uv==0.13.6
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY alembic.ini ./
COPY backend ./backend
ENV PATH="/app/.venv/bin:$PATH" PYTHONPATH=/app/backend
RUN useradd --create-home app
USER app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
