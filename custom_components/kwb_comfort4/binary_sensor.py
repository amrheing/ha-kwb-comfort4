"""Binary sensors for the KWB Comfort 4 integration."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import KwbConfigEntry
from .entity import KwbEntity

PROBLEM_KEYS = {"ksm_anlage_stoerung", "kfk_i_stoerung"}
RUNNING_HINTS = ("pumpe", "motor", "sauger")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: KwbConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    runtime = entry.runtime_data
    async_add_entities(
        KwbBinarySensor(runtime.coordinator, entry, spec)
        for spec in runtime.specs
        if spec.platform == Platform.BINARY_SENSOR
    )


class KwbBinarySensor(KwbEntity, BinarySensorEntity):
    """An on/off or yes/no register."""

    def __init__(self, coordinator, entry, spec) -> None:
        super().__init__(coordinator, entry, spec)
        key = spec.reg.key
        if key in PROBLEM_KEYS:
            self._attr_device_class = BinarySensorDeviceClass.PROBLEM
        elif any(h in key for h in RUNNING_HINTS):
            self._attr_device_class = BinarySensorDeviceClass.RUNNING

    @property
    def is_on(self) -> bool | None:
        raw = self.raw
        return None if raw is None else raw != 0
