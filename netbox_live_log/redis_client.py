import logging

from django.conf import settings

logger = logging.getLogger("netbox.plugins.netbox_live_log")


def get_redis_connection():
    """
    Return a Redis connection.

    Prefer django-rq's existing connection pool so we share NetBox's configured
    Redis instance. Fall back to constructing one from RQ_PARAMS / REDIS settings
    if django-rq isn't importable for some reason.

    Returns None if no connection can be established — callers must treat the
    returned value as optional.
    """
    try:
        import django_rq
        return django_rq.get_connection("default")
    except Exception as exc:
        logger.debug("django_rq.get_connection failed (%s); falling back to RQ_PARAMS", exc)

    try:
        import redis
    except ImportError:
        logger.warning("redis package not available; live log disabled")
        return None

    params = _resolve_redis_params()
    if params is None:
        return None

    try:
        return redis.Redis(**params)
    except Exception as exc:
        logger.warning("Could not create Redis connection: %s", exc)
        return None


def _resolve_redis_params():
    rq_params = getattr(settings, "RQ_PARAMS", None)
    if not rq_params:
        redis_cfg = getattr(settings, "REDIS", {}) or {}
        rq_params = redis_cfg.get("tasks") or redis_cfg.get("default") or None
    if not rq_params:
        return None

    return {
        "host": rq_params.get("HOST", rq_params.get("host", "localhost")),
        "port": int(rq_params.get("PORT", rq_params.get("port", 6379))),
        "db": int(rq_params.get("DB", rq_params.get("db", 0))),
        "password": rq_params.get("PASSWORD", rq_params.get("password")) or None,
        "ssl": bool(rq_params.get("SSL", rq_params.get("ssl", False))),
        "socket_connect_timeout": 2,
        "socket_timeout": 5,
    }


def redis_key(job_id):
    from django.conf import settings as _settings
    prefix = (
        _settings.PLUGINS_CONFIG.get("netbox_live_log", {}).get("redis_key_prefix", "netbox_live_log")
        if hasattr(_settings, "PLUGINS_CONFIG")
        else "netbox_live_log"
    )
    return f"{prefix}:{job_id}"
