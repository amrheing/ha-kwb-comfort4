"""KWB Comfort 4 heating controller (Modbus TCP) integration."""

from __future__ import annotations

from dataclasses import dataclass
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.helpers.typing import ConfigType

from .const import CONF_BOILER_TYPE, DEFAULT_BOILER_TYPE, DOMAIN
from .coordinator import KwbCoordinator
from .fuel import REG_FUEL_CONSUMPTION, FuelBook, statistic_id_for
from .services import async_setup_services
from .entity import EntitySpec, build_specs, unique_id_for
from .registers import load_register_map

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]


@dataclass(slots=True)
class KwbRuntimeData:
    coordinator: KwbCoordinator
    specs: list[EntitySpec]
    fuel: FuelBook | None = None


type KwbConfigEntry = ConfigEntry[KwbRuntimeData]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: KwbConfigEntry) -> bool:
    regmap = await hass.async_add_executor_job(load_register_map)
    coordinator = KwbCoordinator(hass, entry, regmap)
    specs = build_specs(regmap, dict(entry.options))

    # Remove entities that the current options no longer create (other
    # modules, other access level -> other platform).
    registry = er.async_get(hass)
    expected = {(s.platform.value, unique_id_for(entry, s.reg)) for s in specs}
    base = entry.unique_id or entry.entry_id
    keep_suffix = (
        "_active_alarms",
        "_software_version",
        "_pellet_price",
        "_pellet_purchases",
    )
    enabled: set[int] = set()
    by_uid = {unique_id_for(entry, s.reg): s for s in specs}
    for reg_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
        if reg_entry.unique_id.startswith(base) and (
            reg_entry.unique_id.endswith(keep_suffix)
            or "_fuel_consumption_" in reg_entry.unique_id
            or "_fuel_cost_" in reg_entry.unique_id
        ):
            continue
        if (reg_entry.domain, reg_entry.unique_id) not in expected:
            _LOGGER.debug("Removing stale entity %s", reg_entry.entity_id)
            registry.async_remove(reg_entry.entity_id)
            continue
        spec = by_uid.get(reg_entry.unique_id)
        if spec and reg_entry.disabled_by is None:
            enabled.add(spec.reg.address)
    known = {e.unique_id for e in er.async_entries_for_config_entry(registry, entry.entry_id)}
    for spec in specs:
        if unique_id_for(entry, spec.reg) not in known and spec.reg.default:
            enabled.add(spec.reg.address)

    # Read what enabled entities need already in the first refresh.
    preload: list[int] = []
    for addr in enabled:
        reg = regmap.registers[addr]
        if reg.role == "button":
            continue
        preload.append(addr)
        if reg.status:
            preload.append(reg.status)
    coordinator.register(preload)

    fuel: FuelBook | None = None
    boiler = entry.options.get(CONF_BOILER_TYPE, DEFAULT_BOILER_TYPE)
    if REG_FUEL_CONSUMPTION in regmap.boiler_types[boiler]["registers"]:
        fuel = FuelBook(hass, entry.entry_id, statistic_id_for(base))
        await fuel.async_load()
        coordinator.register([REG_FUEL_CONSUMPTION])  # kept for the whole entry lifetime

        def _feed() -> None:
            if coordinator.data is not None:
                fuel.update_total(coordinator.data.values.get(REG_FUEL_CONSUMPTION))

        entry.async_on_unload(coordinator.async_add_listener(_feed))

    await coordinator.async_read_software_version()
    await coordinator.async_config_entry_first_refresh()
    if fuel is not None:
        fuel.update_total(coordinator.data.values.get(REG_FUEL_CONSUMPTION))
        fuel.async_update_statistics()
    entry.runtime_data = KwbRuntimeData(coordinator, specs, fuel)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # pre-registration is only for the first refresh; entities hold their own
    coordinator.unregister(preload)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: KwbConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: KwbConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.coordinator.client.close()
    return unloaded
