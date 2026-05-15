import json
import logging
import os
import time

from django.conf import settings

from .redis_client import get_redis_connection, redis_key

logger = logging.getLogger("netbox.plugins.netbox_live_log")

_VALID_LEVELS = {"debug", "info", "success", "warning", "failure"}


def _resolve_job_id_from_rq():
    """
    The canonical job identifier for the live-log Redis key.

    NetBox enqueues jobs with `job_id=str(job.job_id)` (see
    core.models.jobs.Job.enqueue in NetBox 4.5), so RQ's
    `get_current_job().id` is exactly `core.Job.job_id` — the UUID the SSE
    view BLPOPs by. Use that, not `self.request.id` (which is the
    per-HTTP-request middleware UUID and has no relation to the Job).
    """
    try:
        from rq import get_current_job
    except ImportError:
        return None
    try:
        rq_job = get_current_job()
    except Exception as exc:
        logger.debug("rq.get_current_job() failed: %s", exc)
        return None
    if rq_job is None:
        return None
    return str(rq_job.id) if rq_job.id else None


class LiveLogMixin:
    """
    Mixin for NetBox custom scripts. Streams log entries to the live-log
    SSE endpoint in addition to NetBox's normal logging machinery.

    Usage:

        class MyScript(LiveLogMixin, Script):
            def run(self, data, commit):
                self.log_live("Starting...")

    The mixin auto-wraps any `run()` defined on the subclass (via
    __init_subclass__) so that a `{"status": "done"}` sentinel is pushed
    into the Redis list when `run()` returns or raises. This is what
    closes the SSE stream cleanly on the browser side.
    """

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        own_run = cls.__dict__.get("run")
        if own_run is None or getattr(own_run, "_live_log_wrapped", False):
            return

        def wrapped_run(self, *args, **inner_kwargs):
            try:
                return own_run(self, *args, **inner_kwargs)
            finally:
                try:
                    self._live_log_sentinel()
                except Exception as exc:
                    logger.debug("live-log sentinel push failed: %s", exc)

        wrapped_run._live_log_wrapped = True
        wrapped_run.__wrapped__ = own_run
        wrapped_run.__name__ = getattr(own_run, "__name__", "run")
        wrapped_run.__doc__ = getattr(own_run, "__doc__", None)
        cls.run = wrapped_run

    # ------------------------------------------------------------------ #
    # Job-id resolution
    # ------------------------------------------------------------------ #

    def _live_log_job_id(self):
        cached = getattr(self, "_live_log_cached_job_id", None)
        if cached is not None:
            return cached

        job_id = _resolve_job_id_from_rq()
        if not job_id:
            env_job_id = os.environ.get("NETBOX_JOB_ID")
            if env_job_id:
                job_id = str(env_job_id)

        if job_id:
            self._live_log_cached_job_id = job_id
        return job_id

    def _live_log_ttl(self):
        cfg = getattr(settings, "PLUGINS_CONFIG", {}).get("netbox_live_log", {})
        return int(cfg.get("redis_ttl_seconds", 3600))

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def log_live(self, message, level="info"):
        """
        Push a log entry as JSON to the live-log Redis list for this job.

        Failures (Redis down, no job id, etc.) are swallowed so script
        execution is never interrupted by the live-log layer.
        """
        try:
            normalized = level if level in _VALID_LEVELS else "info"
            job_id = self._live_log_job_id()
            if not job_id:
                return

            conn = get_redis_connection()
            if conn is None:
                return

            entry = {
                "level": normalized,
                "message": str(message),
                "timestamp": time.time(),
            }
            key = redis_key(job_id)
            pipe = conn.pipeline()
            pipe.rpush(key, json.dumps(entry))
            pipe.expire(key, self._live_log_ttl())
            pipe.execute()
        except Exception as exc:
            logger.debug("log_live failed: %s", exc)

    def _live_log_sentinel(self):
        try:
            job_id = self._live_log_job_id()
            if not job_id:
                return
            conn = get_redis_connection()
            if conn is None:
                return
            key = redis_key(job_id)
            conn.rpush(key, json.dumps({"status": "done"}))
            conn.expire(key, self._live_log_ttl())
        except Exception as exc:
            logger.debug("live-log sentinel push failed: %s", exc)
