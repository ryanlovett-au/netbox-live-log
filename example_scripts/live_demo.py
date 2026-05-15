import time

from extras.scripts import Script, StringVar

from netbox_live_log.mixins import LiveLogMixin


class LiveDemoScript(LiveLogMixin, Script):
    class Meta:
        name = "Live Demo"
        description = "Demonstrates streaming log output via netbox_live_log."

    hostname = StringVar(label="Hostname")

    def run(self, data, commit):
        # Headline message — shows on both panels.
        self.log_info(f"Starting script for {data['hostname']}")
        self.log_live(f"Starting script for {data['hostname']}")

        # Exercise every level so the Live Log card's badge styling can be
        # verified side-by-side against the native NetBox Log table.
        # NetBox's persisted log methods are: log_debug, log_info,
        # log_success, log_warning, log_failure.
        self.log_debug("Debug-level entry")
        self.log_live("Debug-level entry",   level="debug")

        self.log_info("Info-level entry")
        self.log_live("Info-level entry",    level="info")

        self.log_warning("Warning-level entry")
        self.log_live("Warning-level entry", level="warning")

        self.log_failure("Failure-level entry")
        self.log_live("Failure-level entry", level="failure")

        for step in range(1, 4):
            self.log_info(f"Step {step} running...")
            self.log_live(f"Step {step} running...")
            time.sleep(1)

        self.log_success("Done!")
        self.log_live("Done!", level="success")
