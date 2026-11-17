"""A small module for the host_check tests. ``--noisy`` writes raw text to stdout, which breaks the protocol."""

import sys

from open_erp_module import Module, ModuleError, Reading, run


class SampleGauge(Module):
    module_id = "sample-gauge"
    name = "Sample Gauge"
    version = "1.0.0"

    def initialize(self, context):
        print("print() output goes to the module log, not to Open ERP")
        self.report_status("ready", "Sample ready")

    def linked_assets(self):
        return ["A1"]

    def capture(self, request):
        if request.asset_id != "A1":
            raise ModuleError("This asset is not linked.", 1001)
        return Reading(2.5, request.units, "sample:1")


if __name__ == "__main__":
    if "--noisy" in sys.argv:
        print("debug: starting", flush=True)
    raise SystemExit(run(SampleGauge()))
