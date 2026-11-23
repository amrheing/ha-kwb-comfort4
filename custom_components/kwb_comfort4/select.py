"""Writable enumerations (programs, modes) for the KWB Comfort 4 integration."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
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
        KwbSelect(runtime.coordinator, entry, spec)
        for spec in runtime.specs
        if spec.platform == Platform.SELECT
    )


class KwbSelect(KwbEntity, SelectEntity):
    """A program selection."""

    def __init__(self, coordinator, entry, spec) -> None:
        super().__init__(coordinator, entry, spec)
        self._attr_options = coordinator.regmap.options(spec.reg.value_table)

    @property
    def current_option(self) -> str | None:
        raw = self.raw
        if raw is None:
            return None
        return self.coordinator.regmap.option_for(self.reg.value_table, raw)

    async def async_select_option(self, option: str) -> None:
        value = self.coordinator.regmap.value_for(self.reg.value_table, option)
        await self.coordinator.async_write(self.reg, value)
