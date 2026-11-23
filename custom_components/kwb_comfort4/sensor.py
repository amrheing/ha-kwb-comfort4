"""Sensors for the KWB Comfort 4 integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    REVOLUTIONS_PER_MINUTE,
    EntityCategory,
    Platform,
    UnitOfEnergy,
    UnitOfLength,
    UnitOfMass,
    UnitOfPower,
    UnitOfPressure,
    UnitOfTemperature,
    UnitOfTime,
    UnitOfVolume,
    UnitOfVolumeFlowRate,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import KwbConfigEntry
from .const import REG_ALARMS_PENDING
from .coordinator import KwbCoordinator
from .entity import KwbEntity, device_info
from .fuel import FuelBook

# unit -> (native unit, device class, state class)
UNITS: dict[str, tuple[str | None, SensorDeviceClass | None, SensorStateClass | None]] = {
    "°C": (UnitOfTemperature.CELSIUS, SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT),
    "%": (PERCENTAGE, None, SensorStateClass.MEASUREMENT),
    "kW": (UnitOfPower.KILO_WATT, SensorDeviceClass.POWER, SensorStateClass.MEASUREMENT),
    "kWh": (UnitOfEnergy.KILO_WATT_HOUR, SensorDeviceClass.ENERGY, SensorStateClass.TOTAL_INCREASING),
    "L/h": (UnitOfVolumeFlowRate.LITERS_PER_HOUR, SensorDeviceClass.VOLUME_FLOW_RATE, SensorStateClass.MEASUREMENT),
    "m³": (UnitOfVolume.CUBIC_METERS, SensorDeviceClass.VOLUME, SensorStateClass.TOTAL_INCREASING),
    "L/min": (UnitOfVolumeFlowRate.LITERS_PER_MINUTE, SensorDeviceClass.VOLUME_FLOW_RATE, SensorStateClass.MEASUREMENT),
    "min": (UnitOfTime.MINUTES, SensorDeviceClass.DURATION, SensorStateClass.TOTAL_INCREASING),
    "h": (UnitOfTime.HOURS, SensorDeviceClass.DURATION, SensorStateClass.MEASUREMENT),
    "rpm": (REVOLUTIONS_PER_MINUTE, None, SensorStateClass.MEASUREMENT),
    "kg": (UnitOfMass.KILOGRAMS, SensorDeviceClass.WEIGHT, SensorStateClass.MEASUREMENT),
    "Pa": (UnitOfPressure.PA, SensorDeviceClass.PRESSURE, SensorStateClass.MEASUREMENT),
    "mm": (UnitOfLength.MILLIMETERS, SensorDeviceClass.DISTANCE, SensorStateClass.MEASUREMENT),
}
# counters that only grow
TOTAL_INCREASING_KEYS = {"fs_pelletsverbrauch"}
SUGGESTED_UNIT = {"min": UnitOfTime.HOURS}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: KwbConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    runtime = entry.runtime_data
    entities: list[SensorEntity] = [
        KwbSensor(runtime.coordinator, entry, spec)
        for spec in runtime.specs
        if spec.platform == Platform.SENSOR
    ]
    entities.append(KwbActiveAlarmsSensor(runtime.coordinator, entry))
    entities.append(KwbSoftwareVersionSensor(runtime.coordinator, entry))
    book = runtime.fuel
    if book is not None:
        for name in ("today", "yesterday", "month", "last_month", "year", "last_year"):
            entities.append(KwbFuelSensor(runtime.coordinator, entry, book, f"fuel_consumption_{name}"))
        for name in ("today", "month", "year", "last_year"):
            entities.append(KwbFuelSensor(runtime.coordinator, entry, book, f"fuel_cost_{name}"))
        entities.append(KwbPurchasesSensor(runtime.coordinator, entry, book))
    async_add_entities(entities)


class KwbSensor(KwbEntity, SensorEntity):
    """A register shown as sensor."""

    def __init__(self, coordinator, entry, spec) -> None:
        super().__init__(coordinator, entry, spec)
        reg = spec.reg
        if reg.value_table:
            self._attr_device_class = SensorDeviceClass.ENUM
            self._attr_options = coordinator.regmap.options(reg.value_table)
        elif reg.unit:
            unit, dclass, sclass = UNITS[reg.unit]
            self._attr_native_unit_of_measurement = unit
            self._attr_device_class = dclass
            self._attr_state_class = sclass
            if reg.key in TOTAL_INCREASING_KEYS:
                self._attr_state_class = SensorStateClass.TOTAL_INCREASING
            if reg.unit in SUGGESTED_UNIT:
                self._attr_suggested_unit_of_measurement = SUGGESTED_UNIT[reg.unit]
            if reg.scale != 1:
                self._attr_suggested_display_precision = {0.1: 1, 0.01: 2, 0.001: 2}.get(
                    reg.scale, 1
                )
        else:
            self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self) -> Any:
        if self.reg.value_table:
            raw = self.raw
            if raw is None:
                return None
            return self.coordinator.regmap.option_for(self.reg.value_table, raw)
        return self.scaled


class KwbActiveAlarmsSensor(CoordinatorEntity[KwbCoordinator], SensorEntity):
    """Number of pending alarms, with their texts as attribute."""

    _attr_has_entity_name = True
    _attr_translation_key = "active_alarms"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:alert-circle-outline"

    def __init__(self, coordinator: KwbCoordinator, entry: KwbConfigEntry) -> None:
        super().__init__(coordinator)
        base = entry.unique_id or entry.entry_id
        self._attr_unique_id = f"{base}_active_alarms"
        self._attr_device_info = device_info(entry, coordinator, None)
        self._texts = {a[0]: a for a in coordinator.regmap.alarms}

    @property
    def native_value(self) -> int | None:
        data = self.coordinator.data
        if data is None:
            return None
        return data.values.get(REG_ALARMS_PENDING)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        data = self.coordinator.data
        if data is None or data.alarms is None:
            return None
        german = (self.hass.config.language or "").startswith("de")
        alarms = []
        for addr in data.alarms:
            _a, alarm_id, text_en, text_de = self._texts[addr]
            alarms.append({"id": alarm_id, "text": (text_de or text_en) if german else text_en})
        return {"alarms": alarms}


class KwbSoftwareVersionSensor(CoordinatorEntity[KwbCoordinator], SensorEntity):
    """Controller software version."""

    _attr_has_entity_name = True
    _attr_translation_key = "software_version"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:chip"

    def __init__(self, coordinator: KwbCoordinator, entry: KwbConfigEntry) -> None:
        super().__init__(coordinator)
        base = entry.unique_id or entry.entry_id
        self._attr_unique_id = f"{base}_software_version"
        self._attr_device_info = device_info(entry, coordinator, None)

    @property
    def native_value(self) -> str | None:
        return self.coordinator.software_version


class KwbFuelSensor(CoordinatorEntity[KwbCoordinator], SensorEntity):
    """Pellet consumption or cost for a period, computed by the integration."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: KwbCoordinator, entry: KwbConfigEntry, book: FuelBook, kind: str) -> None:
        super().__init__(coordinator)
        base = entry.unique_id or entry.entry_id
        self.book = book
        self.kind = kind  # e.g. "fuel_consumption_today", "fuel_cost_month"
        self._attr_translation_key = kind
        self._attr_unique_id = f"{base}_{kind}"
        self._attr_device_info = device_info(entry, coordinator, None)
        if kind.startswith("fuel_cost"):
            self._attr_device_class = SensorDeviceClass.MONETARY
            self._attr_native_unit_of_measurement = "EUR"
            self._attr_suggested_display_precision = 2
            self._attr_icon = "mdi:cash"
        else:
            self._attr_device_class = SensorDeviceClass.WEIGHT
            self._attr_native_unit_of_measurement = UnitOfMass.KILOGRAMS
            self._attr_icon = "mdi:fire"
        if kind in ("fuel_consumption_today", "fuel_consumption_month", "fuel_consumption_year"):
            self._attr_state_class = SensorStateClass.TOTAL_INCREASING

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self.book.async_add_listener(self.async_write_ha_state))

    def _kg(self, name: str) -> int | None:
        period = {"today": "day", "yesterday": "day", "month": "month",
                  "last_month": "month", "year": "year", "last_year": "year"}[name]
        if name in ("yesterday", "last_month", "last_year"):
            return self.book.last(period)
        return self.book.current(period)

    @property
    def available(self) -> bool:
        return self.native_value is not None

    @property
    def native_value(self) -> float | int | None:
        if self.kind.startswith("fuel_cost_"):
            return self.book.cost(self._kg(self.kind.removeprefix("fuel_cost_")))
        return self._kg(self.kind.removeprefix("fuel_consumption_"))


class KwbPurchasesSensor(SensorEntity):
    """Recorded pellet purchases (state: number of purchases)."""

    _attr_has_entity_name = True
    _attr_translation_key = "pellet_purchases"
    _attr_icon = "mdi:truck-delivery"
    _attr_should_poll = False

    def __init__(self, coordinator: KwbCoordinator, entry: KwbConfigEntry, book: FuelBook) -> None:
        base = entry.unique_id or entry.entry_id
        self.book = book
        self._attr_unique_id = f"{base}_pellet_purchases"
        self._attr_device_info = device_info(entry, coordinator, None)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.book.async_add_listener(self.async_write_ha_state))

    @property
    def native_value(self) -> int:
        return len(self.book.purchases)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        purchases = self.book.purchases
        return {
            "purchases": purchases,
            "total_kg": sum(p["amount_kg"] for p in purchases),
            "total_eur": round(sum(p["total"] for p in purchases), 2),
            "price_statistic_id": self.book.statistic_id,
        }
