"""Audio output device enumeration via sounddevice."""

from __future__ import annotations

from dataclasses import dataclass

import sounddevice as sd


@dataclass
class OutputDevice:
    index: int
    name: str
    is_default: bool = False


def list_output_devices() -> list[OutputDevice]:
    devices = sd.query_devices()
    try:
        default_index = sd.default.device[1]
    except Exception:
        default_index = -1

    out = []
    for idx, dev in enumerate(devices):
        if dev.get("max_output_channels", 0) > 0:
            out.append(OutputDevice(index=idx, name=dev["name"], is_default=(idx == default_index)))
    return out
