"""Writable numeric registers for the KWB Comfort 4 integration."""

from __future__ import annotations

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.const import PERCENTAGE, Platform, UnitOfMass, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import KwbConfigEntry
from .entity import KwbEntity, device_info
from .fuel import FuelBook

# unit -> (native unit, device class, default min, default max) in display units
UNITS = {
    "°C": (UnitOfTemperature.CELSIUS, NumberDeviceClass.TEMPERATURE, 0, 95),
    "%": (PERCENTAGE, None, 0, 100),
    "kg": (UnitOfMass.KILOGRAMS, NumberDeviceClass.WEIGHT, 0, 100000),
}
# nicer steps for room temperatures
STEPS = {
    "hk_raum_temperatur_soll_tag": 0.5,
    "hk_raum_temperatur_soll_nacht": 0.5,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: KwbConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    runtime = entry.runtime_data
    entities: list[NumberEntity] = [
        KwbNumber(runtime.coordinator, entry, spec)
        for spec in runtime.specs
        if spec.platform == Platform.NUMBER
    ]
    if runtime.fuel is not None:
        entities.append(KwbPelletPriceNumber(runtime.coordinator, entry, runtime.fuel))
    async_add_entities(entities)


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


class KwbPelletPriceNumber(NumberEntity):
    """Current pellet price per tonne (kept by Home Assistant, not the boiler)."""

    _attr_has_entity_name = True
    _attr_translation_key = "pellet_price"
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 0
    _attr_native_max_value = 2000
    _attr_native_step = 0.01
    _attr_native_unit_of_measurement = "EUR/t"
    _attr_icon = "mdi:currency-eur"
    _attr_should_poll = False

    def __init__(self, coordinator, entry: KwbConfigEntry, book: FuelBook) -> None:
        base = entry.unique_id or entry.entry_id
        self.book = book
        self._attr_unique_id = f"{base}_pellet_price"
        self._attr_device_info = device_info(entry, coordinator, None)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.book.async_add_listener(self.async_write_ha_state))

    @property
    def native_value(self) -> float | None:
        return self.book.price

    async def async_set_native_value(self, value: float) -> None:
        await self.book.async_set_price(round(value, 2))
