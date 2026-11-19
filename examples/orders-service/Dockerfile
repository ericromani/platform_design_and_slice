# Platform Python preset image: slim, non-root (uid 10001 matches the chart's
# securityContext), read-only-root-filesystem friendly (writes only to /tmp).
FROM docker.io/library/python:3.12-slim AS build
WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM docker.io/library/python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin app
COPY --from=build /install /usr/local
WORKDIR /srv
COPY app ./app
USER 10001
EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--no-access-log"]
