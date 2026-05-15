import re

from netbox.plugins import PluginTemplateExtension


# Matches NetBox 4.5's script results URL — either integer PK or UUID:
#   /extras/scripts/results/<id>/
#   /extras/script-results/<id>/   (older alias)
_RESULTS_URL_RE = re.compile(r"^/extras/(?:scripts/results|script-results)/[^/]+/?$")


class LiveLogHead(PluginTemplateExtension):
    """
    Inject the live-log client JS into <head>, but ONLY on the script
    results page. Every other page gets an empty string back, so the
    plugin adds no markup, no JS parse cost, and no network noise to
    unrelated views.

    The results template (extras/script_result.html) doesn't invoke any
    model-scoped hooks (full_width_page, right_page, buttons, alerts...),
    so a model-targeted PluginTemplateExtension can't render there. The
    global head() hook in base/base.html does fire, and we gate it on
    the request path here.
    """

    models = None  # head() is global; we gate on the request path.

    def head(self):
        try:
            path = self.context["request"].path
        except (AttributeError, KeyError, TypeError):
            return ""
        if not _RESULTS_URL_RE.match(path or ""):
            return ""
        return self.render("netbox_live_log/live_log_injection.html")


template_extensions = [LiveLogHead]
