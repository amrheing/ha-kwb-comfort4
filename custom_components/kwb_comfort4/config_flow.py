"""Config flow for the KWB Comfort 4 integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_SCAN_INTERVAL
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)

from .const import (
    ACCESS_EXPERT,
    ACCESS_USER,
    CONF_ACCESS_LEVEL,
    CONF_ADDRESS_OFFSET,
    CONF_BOILER_TYPE,
    CONF_LIFETICK,
    CONF_MODULES,
    CONF_REQUEST_DELAY,
    CONF_UNIT_ID,
    CONF_WORD_ORDER,
    DEFAULT_BOILER_TYPE,
    DEFAULT_PORT,
    DEFAULT_REQUEST_DELAY,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_UNIT_ID,
    DEFAULT_WORD_ORDER,
    DOMAIN,
    MODULES,
)
from .coordinator import detect_address_offset, detect_modules
from .modbus import ModbusError
from .registers import RegisterMap, load_register_map

_LOGGER = logging.getLogger(__name__)


def _connection_schema(defaults: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, "")): TextSelector(),
            vol.Required(CONF_PORT, default=defaults.get(CONF_PORT, DEFAULT_PORT)): NumberSelector(
                NumberSelectorConfig(min=1, max=65535, mode=NumberSelectorMode.BOX)
            ),
            vol.Required(
                CONF_UNIT_ID, default=defaults.get(CONF_UNIT_ID, DEFAULT_UNIT_ID)
            ): NumberSelector(NumberSelectorConfig(min=1, max=255, mode=NumberSelectorMode.BOX)),
        }
    )


def _settings_schema(regmap: RegisterMap, defaults: dict[str, Any]) -> vol.Schema:
    modules: dict[str, list[str]] = defaults.get(CONF_MODULES, {})
    fields: dict[Any, Any] = {
        vol.Required(
            CONF_BOILER_TYPE, default=defaults.get(CONF_BOILER_TYPE, DEFAULT_BOILER_TYPE)
        ): SelectSelector(
            SelectSelectorConfig(
                options=list(regmap.boiler_types),
                translation_key=CONF_BOILER_TYPE,
                mode=SelectSelectorMode.DROPDOWN,
            )
        ),
        vol.Required(
            CONF_ACCESS_LEVEL, default=defaults.get(CONF_ACCESS_LEVEL, ACCESS_USER)
        ): SelectSelector(
            SelectSelectorConfig(
                options=[ACCESS_USER, ACCESS_EXPERT],
                translation_key=CONF_ACCESS_LEVEL,
                mode=SelectSelectorMode.LIST,
            )
        ),
    }
    for module in MODULES:
        info = regmap.modules[module]
        if info["instances"]:
            options = [SelectOptionDict(value=i, label=i) for i in info["instances"]]
        else:
            options = [SelectOptionDict(value="1", label="1")]
        fields[vol.Optional(module, default=modules.get(module, []))] = SelectSelector(
            SelectSelectorConfig(options=options, multiple=True, mode=SelectSelectorMode.DROPDOWN)
        )
    return vol.Schema(fields)


def _advanced_schema(defaults: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(
                CONF_SCAN_INTERVAL,
                default=defaults.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
            ): NumberSelector(
                NumberSelectorConfig(
                    min=10, max=600, step=1, unit_of_measurement="s", mode=NumberSelectorMode.BOX
                )
            ),
            vol.Required(
                CONF_REQUEST_DELAY,
                default=defaults.get(CONF_REQUEST_DELAY, DEFAULT_REQUEST_DELAY),
            ): NumberSelector(
                NumberSelectorConfig(
                    min=0, max=2, step=0.1, unit_of_measurement="s", mode=NumberSelectorMode.BOX
                )
            ),
            vol.Required(
                CONF_WORD_ORDER, default=defaults.get(CONF_WORD_ORDER, DEFAULT_WORD_ORDER)
            ): SelectSelector(
                SelectSelectorConfig(
                    options=["big", "little"],
                    translation_key=CONF_WORD_ORDER,
                    mode=SelectSelectorMode.LIST,
                )
            ),
            vol.Required(CONF_LIFETICK, default=defaults.get(CONF_LIFETICK, False)): BooleanSelector(),
        }
    )


def _split_settings(user_input: dict[str, Any]) -> dict[str, Any]:
    return {
        CONF_BOILER_TYPE: user_input[CONF_BOILER_TYPE],
        CONF_ACCESS_LEVEL: user_input[CONF_ACCESS_LEVEL],
        CONF_MODULES: {m: list(user_input.get(m, [])) for m in MODULES if user_input.get(m)},
    }


class KwbConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up a KWB Comfort 4 controller."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._detected: dict[str, list[str]] = {}
        self._sw_version: str | None = None

    async def _validate(self, user_input: dict[str, Any]) -> dict[str, str]:
        host = user_input[CONF_HOST].strip()
        port = int(user_input[CONF_PORT])
        unit = int(user_input[CONF_UNIT_ID])
        try:
            offset, version = await detect_address_offset(host, port, unit)
        except ModbusError as err:
            _LOGGER.debug("Connection test failed: %s", err)
            return {"base": "cannot_connect"}
        self._sw_version = version
        self._data = {
            CONF_HOST: host,
            CONF_PORT: port,
            CONF_UNIT_ID: unit,
            CONF_ADDRESS_OFFSET: offset,
        }
        return {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = await self._validate(user_input)
            if not errors:
                await self.async_set_unique_id(
                    f"{self._data[CONF_HOST]}_{self._data[CONF_UNIT_ID]}"
                )
                self._abort_if_unique_id_configured()
                regmap = await self.hass.async_add_executor_job(load_register_map)
                try:
                    self._detected = await detect_modules(
                        self._data[CONF_HOST],
                        self._data[CONF_PORT],
                        self._data[CONF_UNIT_ID],
                        self._data[CONF_ADDRESS_OFFSET],
                        regmap,
                    )
                except ModbusError as err:
                    _LOGGER.debug("Module detection failed: %s", err)
                    self._detected = {}
                return await self.async_step_settings()
        return self.async_show_form(
            step_id="user",
            data_schema=_connection_schema(user_input or {}),
            errors=errors,
        )

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        regmap = await self.hass.async_add_executor_job(load_register_map)
        if user_input is not None:
            options = _split_settings(user_input)
            options[CONF_SCAN_INTERVAL] = DEFAULT_SCAN_INTERVAL
            options[CONF_REQUEST_DELAY] = DEFAULT_REQUEST_DELAY
            options[CONF_LIFETICK] = False
            return self.async_create_entry(
                title=f"KWB {regmap.boiler_types[options[CONF_BOILER_TYPE]]['title'].removeprefix('KWB ')}",
                data=self._data,
                options=options,
            )
        return self.async_show_form(
            step_id="settings",
            data_schema=_settings_schema(regmap, {CONF_MODULES: self._detected}),
            description_placeholders={
                "version": self._sw_version or "?",
                "list_version": regmap.software_version,
            },
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = await self._validate(user_input)
            if not errors:
                return self.async_update_reload_and_abort(entry, data=self._data)
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_connection_schema(user_input or dict(entry.data)),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return KwbOptionsFlow()


class KwbOptionsFlow(OptionsFlow):
    """Change installation details and polling."""

    def __init__(self) -> None:
        self._options: dict[str, Any] = {}

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        regmap = await self.hass.async_add_executor_job(load_register_map)
        if user_input is not None:
            self._options = {**self.config_entry.options, **_split_settings(user_input)}
            return await self.async_step_advanced()
        return self.async_show_form(
            step_id="init",
            data_schema=_settings_schema(regmap, dict(self.config_entry.options)),
        )

    async def async_step_advanced(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._options.update(
                {
                    CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL]),
                    CONF_REQUEST_DELAY: float(user_input[CONF_REQUEST_DELAY]),
                    CONF_LIFETICK: bool(user_input[CONF_LIFETICK]),
                    CONF_WORD_ORDER: user_input[CONF_WORD_ORDER],
                }
            )
            return self.async_create_entry(data=self._options)
        return self.async_show_form(
            step_id="advanced", data_schema=_advanced_schema(dict(self.config_entry.options))
        )
