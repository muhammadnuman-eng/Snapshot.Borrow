FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    pytest==8.3.4 \
    pytest-cov==6.0.0 \
    ruff==0.8.4

CMD ["python", "-m", "pytest", "-q"]
