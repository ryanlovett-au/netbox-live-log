import json
import logging
import os
import time

from django.conf import settings

from .redis_client import get_redis_connection, redis_key

logger = logging.getLogger("netbox.plugins.netbox_live_log")

_VALID_LEVELS = {"debug", "info", "success", "warning", "failure"}


class LiveLogMixin:
    """
    Mixin for NetBox custom scripts that streams log entries to the live-log
    SSE endpoint in addition to NetBox's normal logging machinery.

    Usage:

        class MyScript(LiveLogMixin, Script):
            def run(self, data, commit):
                self.log_live("Starting...")
    """

    def _live_log_job_id(self):
        request = getattr(self, "request", None)
        if request is not None:
            job_id = getattr(request, "job_id", None) or getattr(request, "id", None)
            job = getattr(request, "job", None)
            if not job_id and job is not None:
                job_id = getattr(job, "job_id", None) or getattr(job, "id", None)
            if job_id:
                return str(job_id)
        env_job_id = os.environ.get("NETBOX_JOB_ID")
        return str(env_job_id) if env_job_id else None

    def _live_log_ttl(self):
        cfg = getattr(settings, "PLUGINS_CONFIG", {}).get("netbox_live_log", {})
        return int(cfg.get("redis_ttl_seconds", 3600))

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

    def run(self, *args, **kwargs):
        try:
            return super().run(*args, **kwargs)
        finally:
            self._live_log_sentinel()
