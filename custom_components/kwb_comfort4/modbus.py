"""Minimal asyncio Modbus TCP client for the KWB Comfort 4 controller.

Home Assistant pins its own pymodbus version for the core modbus integration,
so this integration carries a small, dependency free client instead. It keeps
one connection open (the controller allows only three clients and drops idle
connections after one minute) and serialises all requests.
"""

from __future__ import annotations

import asyncio
import logging
import struct

_LOGGER = logging.getLogger(__name__)

FC_READ_DISCRETE_INPUTS = 2
FC_READ_HOLDING = 3
FC_READ_INPUT = 4
FC_WRITE_MULTIPLE = 16

EXCEPTION_TEXT = {
    1: "illegal function",
    2: "illegal data address",
    3: "illegal data value",
    4: "server device failure",
    6: "server device busy",
    10: "gateway path unavailable",
    11: "gateway target failed to respond",
}


class ModbusError(Exception):
    """Communication problem (connection, timeout, malformed answer)."""


class ModbusExceptionResponse(ModbusError):
    """The controller answered with a Modbus exception code."""

    def __init__(self, function: int, code: int) -> None:
        super().__init__(
            f"function {function}: exception {code} ({EXCEPTION_TEXT.get(code, 'unknown')})"
        )
        self.code = code


class KwbModbusClient:
    """Modbus TCP client with a persistent connection."""

    def __init__(
        self,
        host: str,
        port: int = 502,
        unit_id: int = 1,
        timeout: float = 5.0,
        address_offset: int = 0,
    ) -> None:
        self.host = host
        self.port = port
        self.unit_id = unit_id
        self.timeout = timeout
        # Address in the KWB list -> protocol address: list_address + offset
        self.address_offset = address_offset
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._lock = asyncio.Lock()
        self._tid = 0

    @property
    def connected(self) -> bool:
        return self._writer is not None and not self._writer.is_closing()

    async def _connect(self) -> None:
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port), self.timeout
            )
        except (OSError, TimeoutError) as err:
            self._reader = self._writer = None
            raise ModbusError(f"cannot connect to {self.host}:{self.port}: {err}") from err
        _LOGGER.debug("Connected to %s:%s", self.host, self.port)

    async def close(self) -> None:
        async with self._lock:
            await self._close()

    async def _close(self) -> None:
        writer, self._writer, self._reader = self._writer, None, None
        if writer is not None:
            writer.close()
            try:
                await writer.wait_closed()
            except (OSError, ConnectionError):
                pass

    async def _request(self, pdu: bytes) -> bytes:
        async with self._lock:
            for attempt in (1, 2):
                if not self.connected:
                    await self._connect()
                assert self._reader and self._writer
                self._tid = (self._tid + 1) & 0xFFFF
                frame = struct.pack(">HHHB", self._tid, 0, len(pdu) + 1, self.unit_id) + pdu
                try:
                    self._writer.write(frame)
                    await self._writer.drain()
                    while True:
                        header = await asyncio.wait_for(
                            self._reader.readexactly(7), self.timeout
                        )
                        tid, _pid, length, _unit = struct.unpack(">HHHB", header)
                        body = await asyncio.wait_for(
                            self._reader.readexactly(length - 1), self.timeout
                        )
                        if tid == self._tid:
                            break
                        _LOGGER.debug("Discarding stale answer %s (want %s)", tid, self._tid)
                except (OSError, TimeoutError, asyncio.IncompleteReadError) as err:
                    await self._close()
                    if attempt == 2:
                        raise ModbusError(f"request failed: {err!r}") from err
                    # a connection closed by the controller after idling: retry once
                    continue
                function = pdu[0]
                if body[0] == function | 0x80:
                    raise ModbusExceptionResponse(function, body[1])
                if body[0] != function:
                    await self._close()
                    raise ModbusError(f"unexpected function {body[0]} for {function}")
                return body
        raise ModbusError("unreachable")  # pragma: no cover

    def _addr(self, address: int) -> int:
        addr = address + self.address_offset
        if not 0 <= addr <= 0xFFFF:
            raise ValueError(f"address {address} out of range")
        return addr

    async def read_registers(self, function: int, address: int, count: int) -> list[int]:
        """Read holding (3) or input (4) registers starting at a list address."""
        body = await self._request(struct.pack(">BHH", function, self._addr(address), count))
        if len(body) < 2 or body[1] != 2 * count or len(body) != 2 + 2 * count:
            raise ModbusError(f"short answer for {count} registers at {address}")
        return list(struct.unpack(f">{count}H", body[2:]))

    async def read_bits(self, function: int, address: int, count: int) -> list[bool]:
        """Read coils (1) or discrete inputs (2)."""
        body = await self._request(struct.pack(">BHH", function, self._addr(address), count))
        nbytes = (count + 7) // 8
        if len(body) != 2 + nbytes:
            raise ModbusError(f"short answer for {count} bits at {address}")
        data = body[2:]
        return [bool(data[i // 8] >> (i % 8) & 1) for i in range(count)]

    async def write_registers(self, address: int, values: list[int]) -> None:
        """Write multiple holding registers (function 16)."""
        pdu = struct.pack(
            f">BHHB{len(values)}H",
            FC_WRITE_MULTIPLE,
            self._addr(address),
            len(values),
            2 * len(values),
            *[v & 0xFFFF for v in values],
        )
        await self._request(pdu)
