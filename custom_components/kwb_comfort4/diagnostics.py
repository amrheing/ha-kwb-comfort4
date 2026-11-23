"""Diagnostics for the KWB Comfort 4 integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant

from . import KwbConfigEntry

TO_REDACT = {CONF_HOST}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: KwbConfigEntry
) -> dict[str, Any]:
    coordinator = entry.runtime_data.coordinator
    data = coordinator.data
    regs = coordinator.regmap.registers
    values = {}
    if data is not None:
        for addr, raw in sorted(data.values.items()):
            reg = regs.get(addr)
            values[str(addr)] = {"param": reg.param if reg else None, "index": reg.index if reg else None, "raw": raw}
    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "software_version": coordinator.software_version,
        "register_list_version": coordinator.regmap.software_version,
        "entities": len(entry.runtime_data.specs),
        "polled_registers": len(coordinator.wanted),
        "read_plan": [
            {"fc": b.fc, "start": b.start, "count": b.count} for b in (coordinator._plan or [])
        ],
        "split_blocks": {
            f"{b.fc}:{b.start}+{b.count}": [f"{s.start}+{s.count}" for s in subs]
            for b, subs in coordinator._split.items()
        },
        "stats": coordinator.stats,
        "values": values,
        "active_alarms": data.alarms if data else None,
    }
