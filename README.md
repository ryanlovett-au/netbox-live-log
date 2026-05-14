# netbox-live-log

A NetBox 4.5 plugin that streams **live log output** from custom scripts to
the results page as they run. Script authors call `self.log_live(...)` and
each entry appears in the existing `#script-log` table within a second or
two — no page refresh, no waiting for the job to finish.

No extra infrastructure required: it reuses NetBox's existing Redis
(via `django-rq`) and ships log entries to the browser over Server-Sent
Events.

---

## Why

NetBox custom scripts only render their log output once `run()` returns.
For long-running scripts (provisioning loops, multi-host SSH runs, batch
imports) that means staring at a spinner for minutes with no feedback,
and no way to tell whether the script is making progress or stuck.

`netbox_live_log` adds a thin streaming layer so you can watch progress
in real time, while leaving NetBox's normal `self.log_*` machinery
untouched.

## How it works

```
  RQ worker process                 Browser
  ─────────────────                 ───────
  LiveLogMixin.log_live()
        │
        │ RPUSH (JSON)
        ▼
  Redis list  netbox_live_log:<job_id>
        │
        │ BLPOP (2s)
        ▼
  SSE view  /plugins/live-log/stream/<job_id>/
        │
        │ text/event-stream
        ▼
  EventSource injected into extras/script.html
        │
        ▼
  Rows appended to #script-log, autoscrolled
```

When `run()` returns (or raises), the mixin pushes a `{"status": "done"}`
sentinel in a `finally` block, the SSE view sees it and closes the stream
cleanly.

## Requirements

| | |
| --- | --- |
| NetBox | 4.5.x |
| Python | 3.12+ |
| Django | 5.x (whatever NetBox 4.5 ships with) |
| Redis  | The one NetBox already uses |

## Installation

### From GitHub (recommended)

```bash
source /opt/netbox/venv/bin/activate
pip install git+https://github.com/ryanlovett-au/netbox-live-log.git@v0.1.0
```

For NetBox upgrades to keep the plugin installed, add it to
`/opt/netbox/local_requirements.txt`:

```
git+https://github.com/ryanlovett-au/netbox-live-log.git@v0.1.0
```

`/opt/netbox/upgrade.sh` will reinstall it on every upgrade.

### From a local checkout (development)

```bash
source /opt/netbox/venv/bin/activate
pip install -e /path/to/netbox-live-scripts
```

### Enable in NetBox

Edit `/opt/netbox/netbox/netbox/configuration.py`:

```python
PLUGINS = [
    "netbox_live_log",
]
```

Optional — only override if the defaults don't suit you:

```python
PLUGINS_CONFIG = {
    "netbox_live_log": {
        "redis_key_prefix": "netbox_live_log",
        "redis_ttl_seconds": 3600,         # per-key TTL, refreshed on each write
        "sse_max_duration_seconds": 1800,  # hard ceiling on a single SSE connection
        "blpop_timeout_seconds": 2,        # BLPOP poll interval
    },
}
```

### Restart

```bash
sudo systemctl restart netbox netbox-rq
```

No database migrations — the plugin has no models.

## Usage

Inherit `LiveLogMixin` **before** `Script` and call `self.log_live(...)`:

```python
from extras.scripts import Script, StringVar
from netbox_live_log.mixins import LiveLogMixin


class LiveDemoScript(LiveLogMixin, Script):
    class Meta:
        name = "Live Demo"

    hostname = StringVar(label="Hostname")

    def run(self, data, commit):
        self.log_live(f"Starting script for {data['hostname']}")
        # ... do work ...
        self.log_live("Done!", level="success")
```

Supported `level` values: `debug`, `info`, `success`, `warning`, `failure`.
Anything else is normalised to `info`.

A complete example lives at [`example_scripts/live_demo.py`](example_scripts/live_demo.py).

### `log_live` vs `log_info`

`log_live` is **additive** — it only drives the streaming UI. It does **not**
write to the persisted NetBox job log. If you want an entry to show up both
in the live stream **and** in the saved job log, call both:

```python
self.log_info("Connecting to device")
self.log_live("Connecting to device")
```

Or wrap it in a small helper on your script class.

## Endpoints

| URL | Purpose |
| --- | --- |
| `GET /plugins/live-log/stream/<job_id>/` | SSE stream for a script job. `@login_required`. Terminates on `{"status":"done"}` sentinel or after `sse_max_duration_seconds`. |

## Behaviour & guarantees

- **Failure-tolerant.** If Redis is unreachable, `log_live` silently no-ops.
  Scripts continue running normally; NetBox's standard logging is unaffected.
- **Bounded streams.** Each SSE connection auto-terminates after
  `sse_max_duration_seconds` (default 30 minutes).
- **Bounded keys.** Each Redis list gets its TTL refreshed (default 1 hour)
  on every write, so abandoned keys from a crashed worker eventually expire.
- **Sentinel close.** The mixin pushes `{"status": "done"}` in a `finally`
  block after `run()`, so the stream closes even on uncaught exceptions.
- **Per-job isolation.** Keys are scoped by job ID, so concurrent scripts
  don't see each other's output.

## Troubleshooting

**No live updates appear.**

`log_live` swallows failures by design, so a misconfigured Redis or
missing job ID just looks like silence. Check, in order:

```bash
# 1. Plugin is loaded
/opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py shell -c \
  "from django.conf import settings; print('netbox_live_log' in settings.PLUGINS)"

# 2. Redis is reachable from the NetBox venv
/opt/netbox/venv/bin/python -c \
  "import django, os; os.environ.setdefault('DJANGO_SETTINGS_MODULE','netbox.settings'); django.setup(); import django_rq; print(django_rq.get_connection('default').ping())"

# 3. The script is actually writing to Redis (run script, then in another shell)
redis-cli --scan --pattern 'netbox_live_log:*'
redis-cli lrange netbox_live_log:<job_id> 0 -1

# 4. The browser opened the SSE connection — DevTools → Network → filter "stream"
```

**Stream connects but never closes.**

Make sure `LiveLogMixin` comes **before** `Script` in the MRO — otherwise
the wrapped `run()` doesn't fire and the sentinel never gets pushed. The
stream will still terminate at `sse_max_duration_seconds`, but cleanly is
better.

**Behind nginx / a reverse proxy.**

SSE needs buffering off. The plugin sets `X-Accel-Buffering: no` which
nginx respects automatically. For other proxies, ensure response buffering
is disabled for `/plugins/live-log/stream/`.

## Configuration reference

| Key | Default | Meaning |
| --- | --- | --- |
| `redis_key_prefix` | `netbox_live_log` | Prefix for per-job list keys. |
| `redis_ttl_seconds` | `3600` | TTL applied to each list on every write. |
| `sse_max_duration_seconds` | `1800` | Hard ceiling on a single SSE connection. |
| `blpop_timeout_seconds` | `2` | BLPOP poll interval — also how often the loop checks for the duration ceiling. |

## Development

```bash
git clone https://github.com/ryanlovett-au/netbox-live-log.git
cd netbox-live-log
pip install -e ".[dev]"
```

Pull requests and issues welcome.

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).
