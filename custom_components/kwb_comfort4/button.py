"""Buttons for the KWB Comfort 4 integration."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
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
        KwbButton(runtime.coordinator, entry, spec)
        for spec in runtime.specs
        if spec.platform == Platform.BUTTON
    )


class KwbButton(KwbEntity, ButtonEntity):
    """Acknowledge (rectify) pending alarms."""

    _attr_icon = "mdi:alarm-light-off-outline"

    def __init__(self, coordinator, entry, spec) -> None:
        super().__init__(coordinator, entry, spec)
        self._addresses = []  # write only

    @property
    def available(self) -> bool:
        # write-only action, does not need a value
        return self.coordinator.last_update_success

    async def async_press(self) -> None:
        await self.coordinator.async_write(self.reg, 1)
        await self.coordinator.async_request_refresh()
