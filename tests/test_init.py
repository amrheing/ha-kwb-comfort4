"""Setup, entity and write tests against the fake controller."""

from homeassistant.const import CONF_HOST, CONF_PORT, CONF_SCAN_INTERVAL, STATE_UNAVAILABLE
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.kwb_comfort4.const import (
    CONF_ACCESS_LEVEL,
    CONF_ADDRESS_OFFSET,
    CONF_BOILER_TYPE,
    CONF_LIFETICK,
    CONF_MODULES,
    CONF_REQUEST_DELAY,
    CONF_UNIT_ID,
    DOMAIN,
)


def _entry(kwb, **options) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id="127.0.0.1_1",
        title="KWB Easyfire",
        data={CONF_HOST: "127.0.0.1", CONF_PORT: kwb.port, CONF_UNIT_ID: 1, CONF_ADDRESS_OFFSET: -1},
        options={
            CONF_BOILER_TYPE: "easyfire",
            CONF_ACCESS_LEVEL: "user",
            CONF_MODULES: {"heating_circuit": ["1.1"], "buffer": ["1"], "solar": ["1"]},
            CONF_SCAN_INTERVAL: 30,
            CONF_REQUEST_DELAY: 0,
            CONF_LIFETICK: False,
            **options,
        },
    )


def _eid(hass, platform, address):
    registry = er.async_get(hass)
    return registry.async_get_entity_id(platform, DOMAIN, f"127.0.0.1_1_{address}")


async def test_setup_and_states(hass, kwb):
    entry = _entry(kwb)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(_eid(hass, "sensor", 8260))
    assert state.state == "56.4"
    assert state.attributes["unit_of_measurement"] == "°C"
    assert state.attributes["friendly_name"] == "Heating circuit 1.1 Forward flow temp., act."

    assert hass.states.get(_eid(hass, "sensor", 8208)).state == "ignite_start_suction"
    assert hass.states.get(_eid(hass, "sensor", 8201)).state == "46.0"
    assert hass.states.get(_eid(hass, "sensor", 9275)).state == "71266.0"
    assert hass.states.get(_eid(hass, "sensor", 8233)).state == "28220"
    # writable at user level -> number / select / switch
    assert hass.states.get(_eid(hass, "number", 24927)).state == "4061"
    assert hass.states.get(_eid(hass, "number", 24624)).state == "24.0"
    assert hass.states.get(_eid(hass, "select", 24589)).state == "comfort"
    assert hass.states.get(_eid(hass, "switch", 24576)).state == "on"
    # sensor whose status register says "missing" is unavailable
    assert hass.states.get(_eid(hass, "sensor", 8202)).state == STATE_UNAVAILABLE
    # expert-only setpoint is a read-only sensor at user level, disabled by default
    assert _eid(hass, "sensor", 24577) is not None
    assert _eid(hass, "number", 24577) is None

    alarms = hass.states.get("sensor.kwb_easyfire_active_alarms")
    assert alarms.state == "1"
    assert alarms.attributes["alarms"] == [{"id": "0.7", "text": "Battery empty"}]
    assert hass.states.get("sensor.kwb_easyfire_software_version").state == "21.9.0"


async def test_writes(hass, kwb):
    entry = _entry(kwb)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    await hass.services.async_call(
        "number", "set_value", {"entity_id": _eid(hass, "number", 24624), "value": 22.5}, blocking=True
    )
    assert kwb.holding[24624] == 225
    await hass.services.async_call(
        "number", "set_value", {"entity_id": _eid(hass, "number", 24927), "value": 70000}, blocking=True
    )
    assert (kwb.holding[24927], kwb.holding[24928]) == (1, 70000 & 0xFFFF)
    await hass.services.async_call(
        "select", "select_option", {"entity_id": _eid(hass, "select", 24589), "option": "reduct"}, blocking=True
    )
    assert kwb.holding[24589] == 4
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": _eid(hass, "switch", 24576)}, blocking=True
    )
    assert kwb.holding[24576] == 0
    await hass.services.async_call(
        "button", "press", {"entity_id": _eid(hass, "button", 24582)}, blocking=True
    )
    assert (24582, [1]) in kwb.writes


async def test_expert_and_lifetick(hass, kwb):
    entry = _entry(kwb, **{CONF_ACCESS_LEVEL: "expert", CONF_LIFETICK: True})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert _eid(hass, "number", 24577) is not None
    assert _eid(hass, "number", 24851) is not None  # modbus boiler temperature
    assert any(addr == 24849 for addr, _ in kwb.writes)


async def test_gaps_refused_are_split(hass, kwb):
    entry = _entry(kwb)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coordinator = entry.runtime_data.coordinator
    # Easyfire has no 8206 -> the merged boiler block was refused and split
    assert coordinator._split
    kwb.requests.clear()
    await coordinator.async_refresh()
    refused = [r for r in kwb.requests if r[1] <= 8206 < r[1] + r[2] and r[0] == 4]
    assert refused == []


async def test_options_change_removes_entities(hass, kwb):
    entry = _entry(kwb)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert _eid(hass, "sensor", 8710) is not None
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_MODULES: {"heating_circuit": ["1.1"]}}
    )
    await hass.async_block_till_done()
    assert _eid(hass, "sensor", 8710) is None
    assert _eid(hass, "sensor", 8260) is not None


async def test_connection_lost(hass, kwb):
    entry = _entry(kwb)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await kwb.stop()
    coordinator = entry.runtime_data.coordinator
    await coordinator.client.close()
    kwb.port_closed = True
    coordinator.client.port = 1
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(_eid(hass, "sensor", 8260)).state == STATE_UNAVAILABLE


async def test_fuel_today_yesterday(hass, kwb):
    from datetime import timedelta

    from homeassistant.util import dt as dt_util

    entry = _entry(kwb)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    today_id = "sensor.kwb_easyfire_fuel_consumption_today"
    yesterday_id = "sensor.kwb_easyfire_fuel_consumption_yesterday"
    assert hass.states.get(today_id).state == "0"
    coordinator = entry.runtime_data.coordinator
    kwb.set(8233, 28250)
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(today_id).state == "30"
    # pretend the day started yesterday -> next update rolls over
    for ent in hass.data["entity_components"]["sensor"].entities:
        if getattr(ent, "period", None):
            ent._day = dt_util.now().date() - timedelta(days=1)
    kwb.set(8233, 28262)
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(yesterday_id).state == "42"
    assert hass.states.get(today_id).state == "0"
