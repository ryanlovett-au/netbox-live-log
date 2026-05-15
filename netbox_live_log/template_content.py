from netbox.plugins import PluginTemplateExtension


class _LiveLogInject(PluginTemplateExtension):
    """Common renderer used by every registration target."""

    def _render(self):
        return self.render("netbox_live_log/live_log_injection.html")

    def full_width_page(self):
        return self._render()

    def right_page(self):
        return self._render()


# The script results page in NetBox 4.5 is rendered for a core.Job object,
# not for extras.Script. Register against both so the injection fires
# whichever template the running NetBox version actually invokes hooks on.
class JobLiveLogExtension(_LiveLogInject):
    models = ["core.job"]


class ScriptLiveLogExtension(_LiveLogInject):
    models = ["extras.script"]


class ScriptModuleLiveLogExtension(_LiveLogInject):
    models = ["extras.scriptmodule"]


template_extensions = [
    JobLiveLogExtension,
    ScriptLiveLogExtension,
    ScriptModuleLiveLogExtension,
]
