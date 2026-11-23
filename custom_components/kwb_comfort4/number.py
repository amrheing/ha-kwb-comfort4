"""Writable numeric registers for the KWB Comfort 4 integration."""

from __future__ import annotations

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.const import PERCENTAGE, Platform, UnitOfMass, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import KwbConfigEntry
from .entity import KwbEntity

# unit -> (native unit, device class, default min, default max) in display units
UNITS = {
    "°C": (UnitOfTemperature.CELSIUS, NumberDeviceClass.TEMPERATURE, 0, 95),
    "%": (PERCENTAGE, None, 0, 100),
    "kg": (UnitOfMass.KILOGRAMS, NumberDeviceClass.WEIGHT, 0, 100000),
}
# nicer steps for room temperatures
STEPS = {"hk_raum_temperatur_soll_tag": 0.5, "hk_raum_temperatur_soll_nacht": 0.5}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: KwbConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    runtime = entry.runtime_data
    async_add_entities(
        KwbNumber(runtime.coordinator, entry, spec)
        for spec in runtime.specs
        if spec.platform == Platform.NUMBER
    )


class KwbNumber(KwbEntity, NumberEntity):
    """A writable setpoint."""

    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator, entry, spec) -> None:
        super().__init__(coordinator, entry, spec)
        reg = spec.reg
        unit, dclass, lo, hi = UNITS.get(reg.unit or "", (reg.unit, None, 0, 65535))
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = dclass
        self._attr_native_min_value = reg.min * reg.scale if reg.min is not None else lo
        self._attr_native_max_value = reg.max * reg.scale if reg.max is not None else hi
        self._attr_native_step = STEPS.get(reg.key, reg.scale)

    @property
    def native_value(self) -> float | None:
        return self.scaled

    async def async_set_native_value(self, value: float) -> None:
        raw = round(value / self.reg.scale)
        await self.coordinator.async_write(self.reg, raw)
