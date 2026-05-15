from netbox.plugins import PluginConfig


class NetBoxLiveLogConfig(PluginConfig):
    name = "netbox_live_log"
    verbose_name = "NetBox Live Log"
    description = "Live log tailing for custom script output via Server-Sent Events."
    version = "0.1.2"
    author = "Sol1"
    base_url = "live-log"
    min_version = "4.5.0"
    max_version = "4.5.99"
    required_settings = []
    default_settings = {
        "redis_key_prefix": "netbox_live_log",
        "redis_ttl_seconds": 3600,
        "sse_max_duration_seconds": 1800,
        "blpop_timeout_seconds": 2,
    }


config = NetBoxLiveLogConfig
