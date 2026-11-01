ARG PYTHON_IMAGE=python:3.13-slim-bookworm@sha256:281d39ff02e3b389401586134ff9e6572954687822a58055ec07a60ded4e0b7f
FROM ${PYTHON_IMAGE}
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY bitcoin4funsite/requirements.txt ./
RUN pip install --no-cache-dir --require-hashes -r requirements.txt
COPY bitcoin4funsite/app.py bitcoin4funsite/market.py bitcoin4funsite/pricing.py bitcoin4funsite/contact.py bitcoin4funsite/bounded_http.py bitcoin4funsite/lookup_limit.py bitcoin4funsite/address_validation.py ./
COPY bitcoin4funsite/tag_access.py bitcoin4funsite/chain_activity.py ./
COPY bitcoin4funsite/templates/ ./templates/
COPY bitcoin4funsite/static/ ./static/
USER 1000:1000
EXPOSE 8080
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "2", "--threads", "2", "--timeout", "15", "--worker-tmp-dir", "/tmp", "--error-logfile", "-", "app:create_app()"]
