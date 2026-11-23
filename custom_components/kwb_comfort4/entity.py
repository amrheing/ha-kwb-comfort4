"""Entity helpers for the KWB Comfort 4 integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ACCESS_USER,
    CONF_ACCESS_LEVEL,
    CONF_BOILER_TYPE,
    CONF_LIFETICK,
    CONF_MODULES,
    DEFAULT_BOILER_TYPE,
    DOMAIN,
    MANUFACTURER,
    MODULE_CASCADE,
)
from .coordinator import KwbCoordinator
from .registers import STATUS_OK, Register, RegisterMap


@dataclass(frozen=True, slots=True)
class EntitySpec:
    platform: Platform
    reg: Register
    writable: bool


def platform_for(reg: Register, writable: bool) -> Platform | None:
    if reg.role == "button":
        return Platform.BUTTON if writable else None
    if reg.role not in ("entity", "external_control"):
        return None
    if writable:
        if reg.is_onoff:
            return Platform.SWITCH
        if reg.value_table:
            return Platform.SELECT
        return Platform.NUMBER
    return Platform.BINARY_SENSOR if reg.is_onoff else Platform.SENSOR


def build_specs(regmap: RegisterMap, options: dict[str, Any]) -> list[EntitySpec]:
    """All entities for a config entry, derived from the options."""
    access = options.get(CONF_ACCESS_LEVEL, ACCESS_USER)
    external = options.get(CONF_LIFETICK, False)
    specs = []
    for reg in regmap.selected_registers(
        options.get(CONF_BOILER_TYPE, DEFAULT_BOILER_TYPE), options.get(CONF_MODULES, {})
    ):
        if reg.role == "external_control" and not external:
            continue
        writable = reg.writable(access)
        platform = platform_for(reg, writable)
        if platform is not None:
            specs.append(EntitySpec(platform, reg, writable))
    return specs


def unique_id_for(entry: ConfigEntry, reg: Register) -> str:
    return f"{entry.unique_id or entry.entry_id}_{reg.address}"


def device_info(entry: ConfigEntry, coordinator: KwbCoordinator, reg: Register | None) -> DeviceInfo:
    base = entry.unique_id or entry.entry_id
    boiler = coordinator.regmap.boiler_types[
        entry.options.get(CONF_BOILER_TYPE, DEFAULT_BOILER_TYPE)
    ]["title"]
    if reg is None or reg.module is None:
        return DeviceInfo(
            identifiers={(DOMAIN, base)},
            manufacturer=MANUFACTURER,
            model=boiler,
            name=boiler,
            sw_version=coordinator.software_version,
            configuration_url=None,
        )
    index = "1" if reg.module == MODULE_CASCADE else reg.index
    return DeviceInfo(
        identifiers={(DOMAIN, f"{base}_{reg.module}_{index}")},
        manufacturer=MANUFACTURER,
        model="Comfort 4",
        translation_key=reg.module,
        translation_placeholders={"index": str(index)},
        via_device=(DOMAIN, base),
    )


class KwbEntity(CoordinatorEntity[KwbCoordinator]):
    """Base entity bound to one register."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: KwbCoordinator, entry: ConfigEntry, spec: EntitySpec) -> None:
        super().__init__(coordinator)
        self.reg = spec.reg
        self._attr_unique_id = unique_id_for(entry, spec.reg)
        self._attr_translation_key = spec.reg.key
        if spec.reg.module == MODULE_CASCADE and spec.reg.index:
            self._attr_translation_placeholders = {"index": spec.reg.index}
        self._attr_device_info = device_info(entry, coordinator, spec.reg)
        self._attr_entity_registry_enabled_default = spec.reg.default
        if not spec.reg.default and spec.writable:
            self._attr_entity_category = EntityCategory.CONFIG
        self._addresses = [spec.reg.address] + ([spec.reg.status] if spec.reg.status else [])

    async def async_added_to_hass(self) -> None:
        self.coordinator.register(self._addresses)
        await super().async_added_to_hass()
        data = self.coordinator.data
        if self._addresses and data is not None and self.reg.address not in data.values:
            # entity enabled while running: fetch its register soon
            await self.coordinator.async_request_refresh()

    async def async_will_remove_from_hass(self) -> None:
        self.coordinator.unregister(self._addresses)
        await super().async_will_remove_from_hass()

    @property
    def raw(self) -> int | None:
        data = self.coordinator.data
        if data is None:
            return None
        return data.values.get(self.reg.address)

    @property
    def available(self) -> bool:
        if not super().available or self.raw is None:
            return False
        if self.reg.status:
            status = self.coordinator.data.values.get(self.reg.status)
            if status is not None and status != STATUS_OK:
                return False
        return True

    @property
    def scaled(self) -> float | int | None:
        raw = self.raw
        if raw is None:
            return None
        if self.reg.scale == 1:
            return raw
        decimals = {0.1: 1, 0.01: 2, 0.001: 3}.get(self.reg.scale, 3)
        return round(raw * self.reg.scale, decimals)
