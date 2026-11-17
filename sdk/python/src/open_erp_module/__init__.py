"""Write an Open ERP measurement module in Python.

Subclass :class:`Module`, implement the methods your device supports and call :func:`run`::

    from open_erp_module import Module, Reading, run

    class MyGauge(Module):
        module_id = "my-gauge"
        name = "My Gauge"
        version = "1.0.0"

        def linked_assets(self):
            return ["asset-id-from-setup"]

        def capture(self, request):
            return Reading(value=12.7, units=request.units, source_id="my-gauge:1")

    if __name__ == "__main__":
        raise SystemExit(run(MyGauge()))

See ``PROTOCOL.md`` for the contract this library implements.
"""

from .runtime import (
    PROTOCOL_VERSION,
    CaptureRequest,
    Context,
    Equipment,
    Module,
    ModuleError,
    Reading,
    run,
    serve,
)

__all__ = [
    "PROTOCOL_VERSION", "CaptureRequest", "Context", "Equipment", "Module", "ModuleError", "Reading", "run", "serve",
]
__version__ = "1.0.0"
