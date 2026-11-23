"""Writable on/off registers for the KWB Comfort 4 integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import KwbConfigEntry
from .entity import KwbEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: KwbConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    runtime = entry.runtime_data
    async_add_entities(
        KwbSwitch(runtime.coordinator, entry, spec)
        for spec in runtime.specs
        if spec.platform == Platform.SWITCH
    )


class KwbSwitch(KwbEntity, SwitchEntity):
    """Boiler on/off, one-time DHW charge and similar."""

    @property
    def is_on(self) -> bool | None:
        raw = self.raw
        return None if raw is None else raw != 0

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_write(self.reg, 1)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_write(self.reg, 0)
