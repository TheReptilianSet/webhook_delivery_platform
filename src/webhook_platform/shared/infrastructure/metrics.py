from prometheus_client import Counter, Gauge, Histogram

HTTP_REQUESTS = Counter(
    "webhook_platform_http_requests_total", "HTTP requests", ["method", "route", "status"]
)
HTTP_DURATION = Histogram(
    "webhook_platform_http_request_duration_seconds", "HTTP request duration", ["method", "route"]
)
EVENTS_ACCEPTED = Counter("webhook_platform_events_total", "Events received", ["result"])
DELIVERY_OUTCOMES = Counter(
    "webhook_platform_delivery_outcomes_total", "Delivery outcomes", ["outcome"]
)
ATTEMPT_DURATION = Histogram(
    "webhook_platform_delivery_attempt_duration_seconds",
    "Outbound delivery attempt duration",
    ["outcome"],
)
RETRIES = Counter("webhook_platform_retries_total", "Retries scheduled")
DLQ_TRANSITIONS = Counter("webhook_platform_dlq_total", "Deliveries moved to dead letter")
OUTBOX_PUBLISH = Counter(
    "webhook_platform_outbox_publish_total", "Outbox publish outcomes", ["result"]
)
STALE_LEASES = Counter("webhook_platform_stale_leases_total", "Stale delivery leases repaired")
SSRF_REJECTIONS = Counter("webhook_platform_ssrf_rejections_total", "Unsafe destinations rejected")
LIMIT_REJECTIONS = Counter(
    "webhook_platform_limit_rejections_total", "Rate or capacity limits rejected", ["kind"]
)
WORKER_IN_FLIGHT = Gauge("webhook_platform_worker_in_flight", "Active delivery tasks")
CAPACITY_DEFERRALS = Counter(
    "webhook_platform_capacity_deferrals_total", "Endpoint concurrency capacity deferrals"
)
CLEANUP_ROWS = Counter(
    "webhook_platform_cleanup_rows_total", "Rows or previews affected by retention cleanup"
)
