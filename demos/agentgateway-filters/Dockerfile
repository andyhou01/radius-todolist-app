FROM docker.io/library/python:3.13.12-alpine3.23@sha256:bb1f2fdb1065c85468775c9d680dcd344f6442a2d1181ef7916b60a623f11d40
ARG PIP_INDEX_URL=https://packagefeedproxy.microsoft.io/pypi/simple
RUN pip install --no-cache-dir --index-url "$PIP_INDEX_URL" redis==5.2.1
WORKDIR /app
COPY app/ /app/
USER 10001:10001
ENV PYTHONUNBUFFERED=1
