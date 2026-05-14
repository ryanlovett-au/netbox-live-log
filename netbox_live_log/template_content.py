from netbox.plugins import PluginTemplateExtension


class ScriptLiveLogExtension(PluginTemplateExtension):
    models = ["extras.script"]

    def buttons(self):
        return ""

    def full_width_page(self):
        return self.render("netbox_live_log/live_log_injection.html")


# NetBox 4.5 expects either `models = [...]` on the extension or a legacy
# `model = "..."` attribute. The injection targets `extras/script.html`, so
# we also expose a variant keyed on the legacy model name for compatibility
# with older template-rendering paths.
class ScriptLiveLogExtensionLegacy(PluginTemplateExtension):
    model = "extras.script"

    def full_width_page(self):
        return self.render("netbox_live_log/live_log_injection.html")


template_extensions = [ScriptLiveLogExtension, ScriptLiveLogExtensionLegacy]
