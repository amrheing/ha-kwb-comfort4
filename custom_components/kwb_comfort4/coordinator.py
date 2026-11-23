"""Polling coordinator for the KWB Comfort 4 integration."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import timedelta
import logging
import time
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_ADDRESS_OFFSET,
    CONF_LIFETICK,
    CONF_REQUEST_DELAY,
    CONF_UNIT_ID,
    DEFAULT_REQUEST_DELAY,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_BIT_GAP,
    MAX_BLOCK_BITS,
    MAX_BLOCK_GAP,
    MAX_BLOCK_REGISTERS,
    REG_ALARMS_PENDING,
    REG_LIFETICK,
    REG_SW_MAJOR,
    RETRY_FAILED_AFTER,
)
from .modbus import (
    FC_READ_DISCRETE_INPUTS,
    FC_READ_HOLDING,
    FC_READ_INPUT,
    KwbModbusClient,
    ModbusError,
    ModbusExceptionResponse,
)
from .registers import Register, RegisterMap

_LOGGER = logging.getLogger(__name__)

PROBE_DELAY = 0.3
FC = {"input": FC_READ_INPUT, "holding": FC_READ_HOLDING}


@dataclass(frozen=True, slots=True)
class Block:
    """A contiguous read request."""

    fc: str
    start: int
    count: int


@dataclass(slots=True)
class KwbData:
    values: dict[int, int] = field(default_factory=dict)
    # list addresses of active alarms, None when not read
    alarms: list[int] | None = None


def plan_blocks(
    registers: Iterable[Register],
    regmap: RegisterMap,
    max_gap: int = MAX_BLOCK_GAP,
    max_len: int = MAX_BLOCK_REGISTERS,
) -> list[Block]:
    """Group registers of the same function into as few reads as possible."""
    blocks: list[Block] = []
    by_fc: dict[str, list[Register]] = {}
    for reg in registers:
        by_fc.setdefault(reg.fc, []).append(reg)
    for fc, regs in sorted(by_fc.items()):
        regs.sort(key=lambda r: r.address)
        start = end = None
        for reg in regs:
            r_end = reg.address + reg.count  # exclusive
            if start is not None and reg.address - end <= max_gap and r_end - start <= max_len:
                end = max(end, r_end)
                continue
            if start is not None:
                blocks.append(Block(fc, start, end - start))
            start, end = reg.address, r_end
        if start is not None:
            blocks.append(Block(fc, start, end - start))
    return blocks


def split_block(block: Block, regmap: RegisterMap, wanted: set[int]) -> list[Block]:
    """Split a block that the controller refused.

    First into runs of addresses that are all defined in the register list (a
    read across undefined addresses is usually what fails), then into single
    registers.
    """
    covered = regmap.covered
    runs: list[Block] = []
    start = None
    addr = block.start
    end = block.start + block.count
    while addr < end:
        reg = covered.get(addr)
        ok = reg is not None and reg.fc == block.fc
        if ok and start is None:
            start = addr
        if not ok and start is not None:
            runs.append(Block(block.fc, start, addr - start))
            start = None
        addr += 1
    if start is not None:
        runs.append(Block(block.fc, start, end - start))
    # drop runs that hold no wanted register
    runs = [
        r for r in runs if any(a in wanted for a in range(r.start, r.start + r.count))
    ]
    if len(runs) == 1 and runs[0] == block:
        # already a clean run -> single registers
        singles = []
        for a in range(block.start, block.start + block.count):
            if a in wanted:
                reg = regmap.registers[a]
                singles.append(Block(block.fc, a, reg.count))
        return singles
    return runs


class KwbCoordinator(DataUpdateCoordinator[KwbData]):
    """Reads all registers needed by enabled entities."""

    config_entry: ConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, regmap: RegisterMap
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(
                seconds=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            ),
        )
        self.regmap = regmap
        self.client = KwbModbusClient(
            entry.data[CONF_HOST],
            entry.data[CONF_PORT],
            entry.data[CONF_UNIT_ID],
            address_offset=entry.data.get(CONF_ADDRESS_OFFSET, 0),
        )
        self.request_delay: float = entry.options.get(
            CONF_REQUEST_DELAY, DEFAULT_REQUEST_DELAY
        )
        self.lifetick_enabled: bool = entry.options.get(CONF_LIFETICK, False)
        self._lifetick = 0
        self._wanted: dict[int, int] = {}  # address -> number of entities using it
        self._always: set[int] = {REG_ALARMS_PENDING}
        self._plan: list[Block] | None = None
        self._split: dict[Block, list[Block]] = {}
        self._failed: dict[int, float] = {}  # address -> monotonic time of failure
        self._bit_split: dict[Block, list[Block]] = {}
        self.read_alarms = True
        self._last_request = 0.0
        self.software_version: str | None = None
        self.stats: dict[str, Any] = {"requests": 0, "errors": 0, "last_duration": None}

    # ---- registration of needed registers ---------------------------
    def register(self, addresses: Iterable[int]) -> None:
        for addr in addresses:
            self._wanted[addr] = self._wanted.get(addr, 0) + 1
        self._plan = None

    def unregister(self, addresses: Iterable[int]) -> None:
        for addr in addresses:
            n = self._wanted.get(addr, 0) - 1
            if n <= 0:
                self._wanted.pop(addr, None)
            else:
                self._wanted[addr] = n
        self._plan = None

    @property
    def wanted(self) -> set[int]:
        return set(self._wanted) | self._always

    # ---- requests ----------------------------------------------------
    async def _pace(self) -> None:
        wait = self._last_request + self.request_delay - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)
        self._last_request = time.monotonic()

    async def _read(self, block: Block) -> list[int]:
        await self._pace()
        self.stats["requests"] += 1
        return await self.client.read_registers(FC[block.fc], block.start, block.count)

    async def _read_block(self, block: Block, values: dict[int, int], wanted: set[int]) -> None:
        if block in self._split:
            for sub in self._split[block]:
                await self._read_block(sub, values, wanted)
            return
        if block.count <= 2 and block.start in self._failed:
            if time.monotonic() - self._failed[block.start] < RETRY_FAILED_AFTER:
                return
        try:
            words = await self._read(block)
        except ModbusExceptionResponse as err:
            self.stats["errors"] += 1
            reg = self.regmap.registers.get(block.start)
            if reg is not None and block.count == reg.count:
                _LOGGER.debug("Register %s (%s) not readable: %s", block.start, reg.param, err)
                self._failed[block.start] = time.monotonic()
                return
            subs = split_block(block, self.regmap, wanted)
            _LOGGER.debug("Block %s refused (%s), splitting into %s", block, err, subs)
            self._split[block] = subs
            for sub in subs:
                await self._read_block(sub, values, wanted)
            return
        self._failed.pop(block.start, None)
        for offset in range(block.count):
            addr = block.start + offset
            reg = self.regmap.registers.get(addr)
            if reg is None or addr not in wanted:
                continue
            if offset + reg.count > block.count:
                continue
            values[addr] = reg.decode(words[offset : offset + reg.count])

    async def _read_alarms(self) -> list[int]:
        addrs = [a[0] for a in self.regmap.alarms]
        blocks: list[Block] = []
        start = end = None
        for addr in addrs:
            if start is not None and addr - end <= MAX_BIT_GAP and addr + 1 - start <= MAX_BLOCK_BITS:
                end = addr + 1
                continue
            if start is not None:
                blocks.append(Block("di", start, end - start))
            start, end = addr, addr + 1
        if start is not None:
            blocks.append(Block("di", start, end - start))
        alarm_set = set(addrs)
        active: list[int] = []

        async def read(block: Block) -> None:
            if block in self._bit_split:
                for sub in self._bit_split[block]:
                    await read(sub)
                return
            await self._pace()
            self.stats["requests"] += 1
            try:
                bits = await self.client.read_bits(
                    FC_READ_DISCRETE_INPUTS, block.start, block.count
                )
            except ModbusExceptionResponse:
                self.stats["errors"] += 1
                if block.count == 1:
                    return
                # split into runs of defined alarm addresses
                subs: list[Block] = []
                s = None
                for a in range(block.start, block.start + block.count + 1):
                    inside = a in alarm_set and a < block.start + block.count
                    if inside and s is None:
                        s = a
                    elif not inside and s is not None:
                        subs.append(Block("di", s, a - s))
                        s = None
                if subs == [block]:
                    subs = [Block("di", a, 1) for a in range(block.start, block.start + block.count)]
                self._bit_split[block] = subs
                for sub in subs:
                    await read(sub)
                return
            for i, bit in enumerate(bits):
                if bit and block.start + i in alarm_set:
                    active.append(block.start + i)

        for block in blocks:
            await read(block)
        return active

    async def _async_update_data(self) -> KwbData:
        started = time.monotonic()
        wanted = self.wanted
        if self._plan is None:
            regs = [self.regmap.registers[a] for a in wanted if a in self.regmap.registers]
            self._plan = plan_blocks(regs, self.regmap)
            _LOGGER.debug("Reading %s registers in %s blocks", len(regs), len(self._plan))
        values: dict[int, int] = {}
        try:
            if self.lifetick_enabled:
                self._lifetick = self._lifetick % 0xFFFF + 1
                await self._pace()
                await self.client.write_registers(REG_LIFETICK, [self._lifetick])
            for block in self._plan:
                await self._read_block(block, values, wanted)
            alarms = None
            if self.read_alarms:
                alarms = []
                if values.get(REG_ALARMS_PENDING, 0) > 0:
                    alarms = await self._read_alarms()
        except ModbusError as err:
            self.stats["errors"] += 1
            raise UpdateFailed(f"Modbus communication failed: {err}") from err
        self.stats["last_duration"] = round(time.monotonic() - started, 2)
        return KwbData(values=values, alarms=alarms)

    async def async_read_software_version(self) -> str | None:
        try:
            await self._pace()
            words = await self.client.read_registers(FC_READ_INPUT, REG_SW_MAJOR, 3)
        except ModbusError:
            return None
        self.software_version = f"{words[0]}.{words[1]}.{words[2]}"
        return self.software_version

    async def async_write(self, reg: Register, raw: int) -> None:
        """Write a register and update the cached value."""
        try:
            await self._pace()
            await self.client.write_registers(reg.address, reg.encode(raw))
        except ModbusError as err:
            raise HomeAssistantError(
                f"Writing {reg.param} ({reg.address}) failed: {err}"
            ) from err
        if self.data is not None:
            self.data.values[reg.address] = raw
            self.async_update_listeners()

    async def async_shutdown(self) -> None:
        await super().async_shutdown()
        await self.client.close()


async def detect_address_offset(
    host: str, port: int, unit_id: int
) -> tuple[int, str]:
    """Find out how list addresses map to protocol addresses.

    The KWB list is documented as 1-based. Depending on firmware and client,
    the documented address is either sent as is or minus one. The software
    version registers (8192-8194) tell us which mapping is right.
    Returns (offset, software_version).
    """
    client = KwbModbusClient(host, port, unit_id)
    try:
        words = await client.read_registers(FC_READ_INPUT, REG_SW_MAJOR - 1, 5)
    except ModbusExceptionResponse:
        # 8191 may be undefined; fall back to reading 8192.. only
        words = [0] + await client.read_registers(FC_READ_INPUT, REG_SW_MAJOR, 4)
    finally:
        await client.close()

    def plausible(major: int, minor: int) -> bool:
        return 15 <= major <= 60 and 0 <= minor <= 30

    # words[0]=8191, words[1]=8192 ...
    if plausible(words[1], words[2]):
        return 0, f"{words[1]}.{words[2]}.{words[3]}"
    if plausible(words[0], words[1]):
        # protocol address 8191 holds the documented 8192 -> offset -1
        return -1, f"{words[0]}.{words[1]}.{words[2]}"
    if plausible(words[2], words[3]):
        return 1, f"{words[2]}.{words[3]}.{words[4]}"
    raise ModbusError(f"no KWB software version found (read {words})")


async def detect_modules(
    host: str, port: int, unit_id: int, offset: int, regmap: RegisterMap
) -> dict[str, list[str]]:
    """Suggest present module instances from their sensor status registers."""
    client = KwbModbusClient(host, port, unit_id, address_offset=offset)
    found: dict[str, list[str]] = {}
    try:
        for module, info in regmap.modules.items():
            probe = info.get("probe")
            if module == "cascade":
                try:
                    await asyncio.sleep(PROBE_DELAY)
                    words = await client.read_registers(FC_READ_INPUT, 9499, 1)
                    if words[0] & 0xFF:
                        found[module] = ["1"]
                except ModbusExceptionResponse:
                    pass
                continue
            if not probe:
                continue
            addrs = sorted(probe.values())
            values: dict[int, int] = {}
            try:
                await asyncio.sleep(PROBE_DELAY)
                words = await client.read_registers(
                    FC_READ_INPUT, addrs[0], addrs[-1] - addrs[0] + 1
                )
                values = {addrs[0] + i: w for i, w in enumerate(words)}
            except ModbusExceptionResponse:
                for addr in addrs:
                    try:
                        await asyncio.sleep(PROBE_DELAY)
                        values[addr] = (await client.read_registers(FC_READ_INPUT, addr, 1))[0]
                    except ModbusExceptionResponse:
                        continue
            present = [i for i, a in probe.items() if values.get(a) == 2]
            if present:
                found[module] = present
    finally:
        await client.close()
    return found
