# netbox-live-log

A NetBox 4.5 plugin that streams **live log output** from custom scripts to
the results page as they run. Script authors call `self.log_live(...)` and
each entry appears in a **Live Log** card on the results page within a
second or two — no page refresh, no waiting for the job to finish. The
card mirrors NetBox's native Log table styling (Line / Time / Level /
Object / Message columns).

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
  Redis list  netbox_live_log:<Job.job_id>
        │
        │ BLPOP (2s)
        ▼
  SSE view  /plugins/live-log/stream/<pk-or-uuid>/
        │
        │ text/event-stream
        ▼
  EventSource opened by JS injected via plugin_head
        │
        ▼
  Rows appended to a dedicated "Live Log" card,
  mounted above the native Log card on the results page
```

The JS is injected via NetBox's `head()` plugin hook on every page, but
a server-side path regex returns an empty string on every page except
`/extras/scripts/results/<id>/` — so unrelated pages get no markup and
no JS parse cost.

When `run()` returns (or raises), the mixin pushes a `{"status": "done"}`
sentinel into Redis; the SSE view sees it and closes the stream cleanly.
The mixin uses `__init_subclass__` to wrap your script's `run()` method,
so the sentinel fires reliably regardless of how the subclass overrides
`run()`.

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
pip install git+https://github.com/ryanlovett-au/netbox-live-log.git@main
```

For NetBox upgrades to keep the plugin installed, add it to
`/opt/netbox/local_requirements.txt`:

```
git+https://github.com/ryanlovett-au/netbox-live-log.git@main
```

`/opt/netbox/upgrade.sh` will reinstall it on every upgrade. Pin to a
tag (e.g. `@v0.1.3`) for production rather than tracking `main`, so an
unrelated upgrade run can't pull in an in-progress commit.

> Some deployments use a release-managed layout (e.g.
> `/srv/netbox/current/venv-py3/`) instead of `/opt/netbox/venv/`.
> Activate whichever venv `uwsgi.ini` / your service file points at —
> the path is whatever `which python` resolves to after activation.

### From a local checkout (development)

```bash
source /opt/netbox/venv/bin/activate
pip install -e /path/to/netbox-live-log
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

If your deployment uses a templated RQ worker unit
(`netbox-rqworker@.service` with multiple instances) instead of the
single `netbox-rq.service`, restart all of them too:

```bash
sudo systemctl restart netbox 'netbox-rqworker@*'
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
- **Scoped injection.** The client JS is only emitted in the HTML of script
  results pages (gated server-side by request path). Every other page in
  NetBox gets no markup and no JS parse cost from this plugin.
- **HTMX-safe.** The Live Log card is mounted as a sibling above the
  native Log card, outside the HTMX-polled `<div hx-get>` region — HTMX's
  every-5-second wholesale swaps don't touch it.
- **Bounded streams.** Each SSE connection auto-terminates after
  `sse_max_duration_seconds` (default 30 minutes).
- **Bounded keys.** Each Redis list gets its TTL refreshed (default 1 hour)
  on every write, so abandoned keys from a crashed worker eventually expire.
- **Sentinel close.** A `{"status": "done"}` sentinel is pushed after
  `run()` returns or raises (via `__init_subclass__` wrapping), so the
  stream closes cleanly even on uncaught exceptions or `sys.exit()`.
- **Per-job isolation.** Keys are scoped by `core.Job.job_id` (the same
  UUID NetBox assigns to the RQ job), so concurrent scripts can't see
  each other's output.

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

**Live Log card appears but stays empty.**

The most common cause is a Redis key mismatch — usually a bespoke
mixin or older plugin pushing under a different identifier. To confirm
the canonical job id the SSE view BLPOPs from, on the NetBox box:

```bash
cd /opt/netbox/netbox  # or /srv/netbox/current/netbox
python manage.py shell -c "from core.models import Job; \
  print(Job.objects.order_by('-pk').first().job_id)"
```

That UUID should match a key returned by
`redis-cli --scan --pattern 'netbox_live_log:*'` while a script is
running. If they don't match, the worker side isn't using the same id.

**Stream connects but never closes.**

The mixin's `__init_subclass__` wraps your `run()` to push the done
sentinel in a `finally` block — so this should never happen. If it
does, your subclass may be defining `run` in a way that bypasses the
wrap (e.g. monkey-patching `cls.run` post-definition). The stream will
still terminate at `sse_max_duration_seconds` (default 30 min) as a
safety net.

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
