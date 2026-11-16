"""Mitutoyo U-WAVE measurement accessory groundwork.

Host-neutral: nothing here imports the ERP. The legacy U-WAVE-R codec, request
client, optional virtual-COM transport, visual asset linking and simulator are
implemented. No host capture provider or direct-USB driver binding is supplied,
and no physical hardware behavior is validated by these modules.
"""
