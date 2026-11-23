"""Actions (services) for pellet purchases."""

from __future__ import annotations

from datetime import date
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN

ATTR_CONFIG_ENTRY_ID = "config_entry_id"
ATTR_DATE = "date"
ATTR_AMOUNT = "amount_kg"
ATTR_PRICE = "price_per_t"
ATTR_TOTAL = "total_price"
ATTR_NOTE = "note"
ATTR_ADD_TO_STOCK = "add_to_stock"

REG_RESIDUAL_FUEL = 24927

ADD_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Required(ATTR_DATE): cv.date,
        vol.Required(ATTR_AMOUNT): vol.All(vol.Coerce(float), vol.Range(min=1)),
        vol.Optional(ATTR_PRICE): vol.All(vol.Coerce(float), vol.Range(min=0)),
        vol.Optional(ATTR_TOTAL): vol.All(vol.Coerce(float), vol.Range(min=0)),
        vol.Optional(ATTR_NOTE): cv.string,
        vol.Optional(ATTR_ADD_TO_STOCK, default=False): cv.boolean,
    }
)
DELETE_SCHEMA = vol.Schema(
    {vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string, vol.Required(ATTR_DATE): cv.date}
)
ATTR_PERIOD = "period"
ATTR_CURRENT = "current_kg"
ATTR_LAST = "last_kg"
SET_CONSUMPTION_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Required(ATTR_PERIOD): vol.In(["day", "month", "year"]),
        vol.Optional(ATTR_CURRENT): vol.All(vol.Coerce(float), vol.Range(min=0)),
        vol.Optional(ATTR_LAST): vol.All(vol.Coerce(float), vol.Range(min=0)),
    }
)
LIST_SCHEMA = vol.Schema({vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string})


def _entry(hass: HomeAssistant, call: ServiceCall):
    entries = [
        e
        for e in hass.config_entries.async_entries(DOMAIN)
        if e.state is ConfigEntryState.LOADED
    ]
    wanted = call.data.get(ATTR_CONFIG_ENTRY_ID)
    if wanted:
        entries = [e for e in entries if e.entry_id == wanted]
    if len(entries) != 1:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="select_entry"
        )
    entry = entries[0]
    if entry.runtime_data.fuel is None:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="no_fuel")
    return entry


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    async def add_purchase(call: ServiceCall) -> ServiceResponse:
        entry = _entry(hass, call)
        amount: float = call.data[ATTR_AMOUNT]
        if ATTR_PRICE in call.data:
            price = call.data[ATTR_PRICE]
        elif ATTR_TOTAL in call.data:
            price = call.data[ATTR_TOTAL] / amount * 1000
        else:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="price_missing")
        when: date = call.data[ATTR_DATE]
        item = await entry.runtime_data.fuel.async_add_purchase(
            when, amount, price, call.data.get(ATTR_NOTE)
        )
        if call.data[ATTR_ADD_TO_STOCK]:
            coordinator = entry.runtime_data.coordinator
            reg = coordinator.regmap.registers[REG_RESIDUAL_FUEL]
            current = coordinator.data.values.get(REG_RESIDUAL_FUEL) if coordinator.data else None
            if current is None:
                raise ServiceValidationError(
                    translation_domain=DOMAIN, translation_key="stock_unknown"
                )
            await coordinator.async_write(reg, int(current + round(amount)))
        return {"purchase": item}

    async def delete_purchase(call: ServiceCall) -> ServiceResponse:
        entry = _entry(hass, call)
        removed = await entry.runtime_data.fuel.async_delete_purchase(call.data[ATTR_DATE])
        return {"removed": removed}

    async def list_purchases(call: ServiceCall) -> ServiceResponse:
        entry = _entry(hass, call)
        book = entry.runtime_data.fuel
        result: dict[str, Any] = {
            "purchases": book.purchases,
            "price_per_t": book.price,
            "price_history": [{"date": d, "price_per_t": p} for d, p in book.price_points().items()],
        }
        return result

    async def set_consumption(call: ServiceCall) -> None:
        entry = _entry(hass, call)
        try:
            await entry.runtime_data.fuel.async_set_consumption(
                call.data[ATTR_PERIOD], call.data.get(ATTR_CURRENT), call.data.get(ATTR_LAST)
            )
        except ValueError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="total_unknown"
            ) from err

    hass.services.async_register(
        DOMAIN, "set_consumption", set_consumption, SET_CONSUMPTION_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, "add_purchase", add_purchase, ADD_SCHEMA, supports_response=SupportsResponse.OPTIONAL
    )
    hass.services.async_register(
        DOMAIN, "delete_purchase", delete_purchase, DELETE_SCHEMA, supports_response=SupportsResponse.OPTIONAL
    )
    hass.services.async_register(
        DOMAIN, "list_purchases", list_purchases, LIST_SCHEMA, supports_response=SupportsResponse.ONLY
    )
