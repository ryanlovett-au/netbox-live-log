import time

from extras.scripts import Script, StringVar

from netbox_live_log.mixins import LiveLogMixin


class LiveDemoScript(LiveLogMixin, Script):
    class Meta:
        name = "Live Demo"
        description = "Demonstrates streaming log output via netbox_live_log."

    hostname = StringVar(label="Hostname")

    def run(self, data, commit):
        self.log_live(f"Starting script for {data['hostname']}")

        # Exercise every level so the Live Log card's badge styling can be
        # verified against the native NetBox Log table at a glance.
        self.log_live("Debug-level entry",   level="debug")
        self.log_live("Info-level entry",    level="info")
        self.log_live("Warning-level entry", level="warning")
        self.log_live("Failure-level entry", level="failure")

        for step in range(1, 4):
            self.log_live(f"Step {step} running...")
            time.sleep(1)

        self.log_live("Done!", level="success")
