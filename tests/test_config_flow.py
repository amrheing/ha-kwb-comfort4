"""Config flow tests against the fake controller."""

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.data_entry_flow import FlowResultType

from custom_components.kwb_comfort4.const import (
    CONF_ADDRESS_OFFSET,
    CONF_MODULES,
    CONF_UNIT_ID,
    DOMAIN,
)


async def test_user_flow_detects_offset_and_modules(hass, kwb):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "127.0.0.1", CONF_PORT: kwb.port, CONF_UNIT_ID: 1}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "settings"
    assert result["description_placeholders"]["version"] == "21.9.0"
    schema = result["data_schema"]({})  # defaults
    assert schema["heating_circuit"] == ["1.1"]
    assert schema["buffer"] == ["1"]
    assert schema["solar"] == ["1"]
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"boiler_type": "easyfire", "access_level": "user", **{k: v for k, v in schema.items() if k not in ("boiler_type", "access_level")}},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "KWB Easyfire"
    assert result["data"][CONF_ADDRESS_OFFSET] == -1
    assert result["options"][CONF_MODULES] == {
        "heating_circuit": ["1.1"],
        "buffer": ["1"],
        "solar": ["1"],
    }


async def test_offset_zero(hass, kwb):
    kwb.offset = 0
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "127.0.0.1", CONF_PORT: kwb.port, CONF_UNIT_ID: 1}
    )
    assert result["step_id"] == "settings"
    flow = hass.config_entries.flow._progress[result["flow_id"]]
    assert flow._data[CONF_ADDRESS_OFFSET] == 0


async def test_cannot_connect(hass, socket_enabled):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "127.0.0.1", CONF_PORT: 1, CONF_UNIT_ID: 1}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}
