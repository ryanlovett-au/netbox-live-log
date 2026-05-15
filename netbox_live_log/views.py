import json
import logging
import time

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import StreamingHttpResponse
from django.utils.decorators import method_decorator
from django.views import View

from .redis_client import get_redis_connection, redis_key

logger = logging.getLogger("netbox.plugins.netbox_live_log")


def _plugin_cfg():
    return getattr(settings, "PLUGINS_CONFIG", {}).get("netbox_live_log", {})


def _sse_format(payload):
    return f"data: {payload}\n\n"


def _resolve_job_uuid(job_id):
    """
    The Redis key is the Job's UUID (job.job_id), but NetBox's results URL
    contains the Job's integer PK. Accept either form on the SSE endpoint
    and translate PK -> UUID via the core.Job model. Returns the canonical
    UUID string, or the input unchanged if we can't translate.
    """
    if not isinstance(job_id, str):
        job_id = str(job_id)
    if not job_id.isdigit():
        return job_id
    try:
        from core.models import Job
    except ImportError:
        try:
            from extras.models import Job  # NetBox <4.0 fallback (defensive)
        except ImportError:
            return job_id
    try:
        job = Job.objects.only("job_id").get(pk=int(job_id))
    except Exception as exc:
        logger.debug("Job pk=%s lookup failed: %s", job_id, exc)
        return job_id
    return str(getattr(job, "job_id", job_id))


@method_decorator(login_required, name="dispatch")
class LiveLogStreamView(View):
    """
    Server-Sent Events stream for a script job's live log.

    Polls the per-job Redis list with BLPOP and re-emits each entry as an
    SSE data line. Terminates on a {"status": "done"} sentinel or after the
    configured maximum duration.
    """

    def get(self, request, job_id):
        cfg = _plugin_cfg()
        max_duration = int(cfg.get("sse_max_duration_seconds", 1800))
        blpop_timeout = int(cfg.get("blpop_timeout_seconds", 2))

        # Translate PK -> UUID if the URL gave us an integer Job PK.
        resolved = _resolve_job_uuid(job_id)

        response = StreamingHttpResponse(
            self._event_stream(resolved, max_duration, blpop_timeout),
            content_type="text/event-stream",
        )
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"
        return response

    def _event_stream(self, job_id, max_duration, blpop_timeout):
        conn = get_redis_connection()
        if conn is None:
            yield _sse_format(json.dumps({"status": "error", "message": "Redis unavailable"}))
            yield _sse_format(json.dumps({"status": "done"}))
            return

        key = redis_key(job_id)
        start = time.monotonic()
        # Heartbeat keeps proxies from closing the connection on quiet jobs.
        last_heartbeat = start

        yield _sse_format(json.dumps({"status": "connected", "job_id": str(job_id)}))

        while True:
            if time.monotonic() - start > max_duration:
                yield _sse_format(json.dumps({"status": "timeout"}))
                yield _sse_format(json.dumps({"status": "done"}))
                return

            try:
                item = conn.blpop(key, timeout=blpop_timeout)
            except Exception as exc:
                logger.warning("BLPOP failed for %s: %s", key, exc)
                yield _sse_format(json.dumps({"status": "error", "message": "Stream error"}))
                yield _sse_format(json.dumps({"status": "done"}))
                return

            if item is None:
                # Timeout — emit a comment so the connection stays warm.
                now = time.monotonic()
                if now - last_heartbeat >= 15:
                    yield ": keep-alive\n\n"
                    last_heartbeat = now
                continue

            _key, raw = item
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", errors="replace")

            yield _sse_format(raw)

            try:
                parsed = json.loads(raw)
            except (ValueError, TypeError):
                parsed = None

            if isinstance(parsed, dict) and parsed.get("status") == "done":
                return
