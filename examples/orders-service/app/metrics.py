"""Prometheus metrics. Names follow the platform metrics contract the rollout
AnalysisTemplate and the Grafana dashboard query:

  http_requests_total{method,path,status}
  app_work_items_total{outcome="success"|"failure"|"rejected"}
  app_work_duration_seconds (histogram)
"""

from prometheus_client import Counter, Histogram

HTTP_REQUESTS = Counter(
    "http_requests_total", "HTTP requests served.", ["method", "path", "status"]
)
WORK_ITEMS = Counter("app_work_items_total", "Background work items processed.", ["outcome"])
WORK_DURATION = Histogram(
    "app_work_duration_seconds",
    "Time to process one work item.",
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5),
)

# Pre-create both label values so ratios are defined from the first scrape.
WORK_ITEMS.labels(outcome="success")
WORK_ITEMS.labels(outcome="failure")
WORK_ITEMS.labels(outcome="rejected")
