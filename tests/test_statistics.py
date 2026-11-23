"""Price history as long term statistics (needs the recorder)."""

import pytest

from .test_init import _entry


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(recorder_mock, enable_custom_integrations):
    """Recorder must start before hass for this module."""
    yield


async def test_price_history_statistics(hass, kwb):
    from homeassistant.components.recorder.statistics import list_statistic_ids
    from pytest_homeassistant_custom_component.components.recorder.common import (
        async_wait_recording_done,
    )

    entry = _entry(kwb)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await hass.services.async_call(
        "kwb_comfort4", "add_purchase",
        {"date": "2023-05-02", "amount_kg": 6000, "price_per_t": 310},
        blocking=True,
    )
    await async_wait_recording_done(hass)
    ids = await hass.async_add_executor_job(list_statistic_ids, hass)
    stat_ids = {i["statistic_id"] for i in ids}
    assert "kwb_comfort4:pellet_price_127_0_0_1_1" in stat_ids
