"""A small fake KWB Comfort 4 Modbus TCP server for tests."""

from __future__ import annotations

import asyncio
import struct

from custom_components.kwb_comfort4.registers import load_register_map


class FakeKwb:
    """Serves the KWB register list; undefined addresses raise exception 2."""

    def __init__(self, offset: int = -1, boiler: str = "easyfire") -> None:
        self.regmap = load_register_map()
        boiler_addrs = set()
        for key, info in self.regmap.boiler_types.items():
            if key != boiler:
                boiler_addrs |= set(info["registers"])
        boiler_addrs -= set(self.regmap.boiler_types[boiler]["registers"])
        boiler_addrs -= set(self.regmap.universal)
        # protocol address = list address + offset
        self.offset = offset
        self.holding: dict[int, int] = {}
        self.input: dict[int, int] = {}
        self.bits: dict[int, bool] = {a[0]: False for a in self.regmap.alarms}
        self.requests: list[tuple[int, int, int]] = []
        self.writes: list[tuple[int, list[int]]] = []
        self.refuse_gaps = True
        for reg in self.regmap.registers.values():
            if reg.address in boiler_addrs:
                continue  # belongs to another boiler type only
            target = self.holding if reg.fc == "holding" else self.input
            for i in range(reg.count):
                target[reg.address + i] = 0
            if reg.role == "status":
                target[reg.address] = 1  # "missing" by default
        self.server: asyncio.base_events.Server | None = None
        self._writers: set[asyncio.StreamWriter] = set()
        self.port = 0

    # helpers -----------------------------------------------------------
    def set(self, address: int, value: int) -> None:
        reg = self.regmap.registers[address]
        target = self.holding if reg.fc == "holding" else self.input
        for i, word in enumerate(reg.encode(value)):
            target[address + i] = word

    def set_temp(self, address: int, celsius: float) -> None:
        self.set(address, round(celsius * 10))
        reg = self.regmap.registers[address]
        if reg.status:
            self.set(reg.status, 2)

    # server ------------------------------------------------------------
    async def start(self) -> None:
        self.server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        if self.server:
            self.server.close()
            for writer in list(self._writers):
                writer.close()
            await self.server.wait_closed()

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self._writers.add(writer)
        try:
            while True:
                header = await reader.readexactly(7)
                tid, pid, length, unit = struct.unpack(">HHHB", header)
                pdu = await reader.readexactly(length - 1)
                answer = self._process(pdu)
                writer.write(struct.pack(">HHHB", tid, pid, len(answer) + 1, unit) + answer)
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            self._writers.discard(writer)
            writer.close()

    def _process(self, pdu: bytes) -> bytes:
        fc = pdu[0]
        if fc in (2, 3, 4):
            wire, count = struct.unpack(">HH", pdu[1:5])
            addr = wire - self.offset
            self.requests.append((fc, addr, count))
            if fc == 2:
                bits = []
                for a in range(addr, addr + count):
                    if a not in self.bits and self.refuse_gaps:
                        return bytes([fc | 0x80, 2])
                    bits.append(self.bits.get(a, False))
                data = bytearray((count + 7) // 8)
                for i, b in enumerate(bits):
                    if b:
                        data[i // 8] |= 1 << (i % 8)
                return bytes([fc, len(data)]) + bytes(data)
            table = self.holding if fc == 3 else self.input
            words = []
            for a in range(addr, addr + count):
                if a not in table:
                    if self.refuse_gaps:
                        return bytes([fc | 0x80, 2])
                    words.append(0)
                else:
                    words.append(table[a])
            return bytes([fc, 2 * count]) + struct.pack(f">{count}H", *words)
        if fc == 16:
            wire, count, _n = struct.unpack(">HHB", pdu[1:6])
            addr = wire - self.offset
            values = list(struct.unpack(f">{count}H", pdu[6 : 6 + 2 * count]))
            for i in range(len(values)):
                if addr + i not in self.holding:
                    return bytes([fc | 0x80, 2])
            for i, v in enumerate(values):
                self.holding[addr + i] = v
            self.writes.append((addr, values))
            return bytes([fc]) + pdu[1:5]
        return bytes([fc | 0x80, 1])


def gerald_like() -> FakeKwb:
    """Easyfire with heating circuit 1.1, buffer 1 and solar 1."""
    kwb = FakeKwb()
    kwb.set(8192, 21)
    kwb.set(8193, 9)
    kwb.set(8194, 0)
    kwb.set_temp(8197, 51.9)  # boiler temp
    kwb.set(8208, 11)  # boiler status: ignite start suction
    kwb.set(8201, 460)  # boiler pump 46.0 %
    kwb.set(8233, 28220)  # fuel consumption kg
    kwb.set(8209, 3047 * 60)  # full load minutes
    kwb.set(24927, 4061)  # residual fuel
    kwb.set(24576, 1)  # boiler on
    kwb.set_temp(8260, 56.4)  # HC 1.1 forward flow
    kwb.set(8328, 576)
    kwb.set(8573, 1)  # comfort
    kwb.set(24589, 3)  # program comfort
    kwb.set(24624, 240)
    kwb.set(24659, 200)
    kwb.set_temp(8710, 58.0)  # BUF 1 temp 1
    kwb.set_temp(8778, 58.1)
    kwb.set_temp(9080, 1.9)  # SOL 1 collector
    kwb.set(9275, 71266000)  # heat amount total, 1/1000 kWh
    kwb.set(8254, 1)  # one pending alarm
    kwb.bits[7] = True  # battery empty
    return kwb
