"""Pellet bookkeeping: consumption periods, price, purchases and price history.

Everything here is computed and stored by Home Assistant; the controller only
provides the total fuel consumption counter (register 8233).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timedelta
import logging
import re
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
REG_FUEL_CONSUMPTION = 8233
PERIODS = ("day", "month", "year")


def period_key(period: str, day: date) -> str:
    if period == "day":
        return day.isoformat()
    if period == "month":
        return f"{day.year:04d}-{day.month:02d}"
    return f"{day.year:04d}"


def previous_key(period: str, day: date) -> str:
    if period == "day":
        return (day - timedelta(days=1)).isoformat()
    if period == "month":
        first = day.replace(day=1) - timedelta(days=1)
        return f"{first.year:04d}-{first.month:02d}"
    return f"{day.year - 1:04d}"


class FuelBook:
    """Persistent pellet data of one config entry."""

    def __init__(self, hass: HomeAssistant, entry_id: str, statistic_id: str) -> None:
        self.hass = hass
        self.statistic_id = statistic_id
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry_id}.fuel"
        )
        self.data: dict[str, Any] = {"price": None, "purchases": [], "prices": [], "periods": {}}
        self.total: int | None = None
        self._listeners: list[Callable[[], None]] = []

    async def async_load(self) -> None:
        stored = await self._store.async_load()
        if stored:
            self.data.update(stored)

    def _save(self) -> None:
        self._store.async_delay_save(lambda: self.data, 5)

    @callback
    def async_add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    def _notify(self) -> None:
        for listener in list(self._listeners):
            listener()

    # ---- consumption ------------------------------------------------
    @callback
    def update_total(self, total: int | None) -> None:
        """Feed the controller's consumption counter, roll periods."""
        if total is None:
            return
        self.total = total
        today = dt_util.now().date()
        periods: dict[str, dict[str, Any]] = self.data.setdefault("periods", {})
        changed = False
        for period in PERIODS:
            key = period_key(period, today)
            info = periods.get(period)
            if info is None:
                periods[period] = {"key": key, "start": total, "last": None, "last_key": None}
                changed = True
                continue
            if info["key"] != key:
                if info["key"] == previous_key(period, today):
                    info["last"] = max(total - info["start"], 0)
                    info["last_key"] = info["key"]
                else:
                    info["last"] = None
                    info["last_key"] = None
                info["key"] = key
                info["start"] = total
                changed = True
            elif total < info["start"]:
                # counter was reset on the controller
                info["start"] = total
                changed = True
        if changed:
            self._save()

    def current(self, period: str) -> int | None:
        info = self.data.get("periods", {}).get(period)
        if info is None or self.total is None:
            return None
        return max(self.total - info["start"], 0)

    def last(self, period: str) -> int | None:
        info = self.data.get("periods", {}).get(period)
        return None if info is None else info.get("last")

    async def async_set_consumption(
        self, period: str, current: float | None = None, last: float | None = None
    ) -> None:
        """Correct a period, e.g. to take over values from an older meter."""
        if self.total is None:
            raise ValueError("total unknown")
        today = dt_util.now().date()
        periods: dict[str, dict[str, Any]] = self.data.setdefault("periods", {})
        info = periods.setdefault(
            period, {"key": period_key(period, today), "start": self.total, "last": None, "last_key": None}
        )
        if current is not None:
            info["key"] = period_key(period, today)
            info["start"] = self.total - round(current)
        if last is not None:
            info["last"] = round(last)
            info["last_key"] = previous_key(period, today)
        self._save()
        self._notify()

    # ---- price ------------------------------------------------------
    @property
    def price(self) -> float | None:
        return self.data.get("price")

    async def async_set_price(self, price: float, when: date | None = None) -> None:
        when = when or dt_util.now().date()
        self.data["price"] = price
        prices: list[dict[str, Any]] = self.data.setdefault("prices", [])
        prices[:] = [p for p in prices if p["date"] != when.isoformat()]
        prices.append({"date": when.isoformat(), "price_per_t": price})
        prices.sort(key=lambda p: p["date"])
        self._save()
        self._notify()
        self.async_update_statistics()

    def cost(self, kg: int | None) -> float | None:
        if kg is None or self.price is None:
            return None
        return round(kg * self.price / 1000, 2)

    # ---- purchases --------------------------------------------------
    @property
    def purchases(self) -> list[dict[str, Any]]:
        return self.data.setdefault("purchases", [])

    async def async_add_purchase(
        self, when: date, amount_kg: float, price_per_t: float, note: str | None = None
    ) -> dict[str, Any]:
        item = {
            "date": when.isoformat(),
            "amount_kg": round(amount_kg),
            "price_per_t": round(price_per_t, 2),
            "total": round(amount_kg * price_per_t / 1000, 2),
        }
        if note:
            item["note"] = note
        self.purchases.append(item)
        self.purchases.sort(key=lambda p: p["date"])
        # the newest purchase sets the current price
        if self.purchases[-1] is item:
            self.data["price"] = item["price_per_t"]
        self._save()
        self._notify()
        self.async_update_statistics()
        return item

    async def async_delete_purchase(self, when: date) -> int:
        before = len(self.purchases)
        self.data["purchases"] = [p for p in self.purchases if p["date"] != when.isoformat()]
        removed = before - len(self.purchases)
        if removed:
            self._save()
            self._notify()
            if "recorder" in self.hass.config.components:
                from homeassistant.components.recorder import get_instance  # noqa: PLC0415

                get_instance(self.hass).async_clear_statistics([self.statistic_id])
            self.async_update_statistics()
        return removed

    # ---- price history as long term statistics ------------------------
    def price_points(self) -> dict[str, float]:
        """Date -> price per tonne from purchases and manual price changes."""
        points: dict[str, float] = {}
        for item in self.data.get("prices", []):
            points[item["date"]] = item["price_per_t"]
        for item in self.purchases:
            points[item["date"]] = item["price_per_t"]  # purchases win
        return dict(sorted(points.items()))

    @callback
    def async_update_statistics(self) -> None:
        """Write the price history as external statistic (for a graph card)."""
        if "recorder" not in self.hass.config.components:
            return
        from homeassistant.components.recorder.models import (  # noqa: PLC0415
            StatisticData,
            StatisticMeanType,
            StatisticMetaData,
        )
        from homeassistant.components.recorder.statistics import (  # noqa: PLC0415
            async_add_external_statistics,
        )

        points = self.price_points()
        if not points:
            return
        tz = dt_util.get_default_time_zone()
        stats = []
        for day, price in points.items():
            start = datetime.fromisoformat(day).replace(hour=12, tzinfo=tz)
            stats.append(StatisticData(start=start, mean=price, min=price, max=price))
        metadata = StatisticMetaData(
            mean_type=StatisticMeanType.ARITHMETIC,
            has_sum=False,
            name="Pelletpreis",
            source=DOMAIN,
            statistic_id=self.statistic_id,
            unit_class=None,
            unit_of_measurement="EUR/t",
        )
        async_add_external_statistics(self.hass, metadata, stats)


def statistic_id_for(unique: str) -> str:
    return f"{DOMAIN}:pellet_price_{re.sub(r'[^a-z0-9_]+', '_', unique.lower()).strip('_')}"
