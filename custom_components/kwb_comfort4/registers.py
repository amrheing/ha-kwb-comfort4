"""Register map of the KWB Comfort 4 controller (generated from ModbusInfo.xlsx)."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import cache
import json
from pathlib import Path
from typing import Any

from .const import (
    ACCESS_EXPERT,
    MODULE_CASCADE,
)

ONOFF_TABLES = ("system_ein_aus_t", "system_yes_no_t")
STATUS_OK = 2


@dataclass(frozen=True, slots=True)
class Register:
    """One parameter in the KWB Modbus list."""

    address: int
    count: int
    type: str
    fc: str  # "input" or "holding"
    param: str
    key: str
    role: str  # entity, status, internal, external_control, button
    user_write: bool = False
    expert_write: bool = False
    module: str | None = None
    index: str | None = None
    unit: str | None = None
    scale: float = 1
    value_table: str | None = None
    min: int | None = None
    max: int | None = None
    status: int | None = None
    default: bool = False

    @property
    def signed(self) -> bool:
        return self.type.startswith("s")

    @property
    def is_onoff(self) -> bool:
        return self.value_table in ONOFF_TABLES

    def writable(self, access_level: str) -> bool:
        if self.fc != "holding":
            return False
        return self.expert_write if access_level == ACCESS_EXPERT else self.user_write

    def decode(self, words: list[int], word_order: str = "big") -> int:
        """Decode raw words.

        The KWB manual says 32 bit values come low word first, but controllers
        with software 24.x send the high word first, so this is configurable.
        """
        if self.count == 2:
            low, high = (words[1], words[0]) if word_order == "big" else (words[0], words[1])
            value = low | (high << 16)
            if self.signed and value & 0x80000000:
                value -= 1 << 32
            return value
        value = words[0]
        if self.type == "u8":
            return value & 0xFF
        if self.signed and value & 0x8000:
            value -= 1 << 16
        return value

    def encode(self, value: int, word_order: str = "big") -> list[int]:
        if self.count == 2:
            value &= 0xFFFFFFFF
            low, high = value & 0xFFFF, value >> 16
            return [high, low] if word_order == "big" else [low, high]
        return [value & 0xFFFF]


@dataclass(slots=True)
class RegisterMap:
    software_version: str
    registers: dict[int, Register]
    boiler_types: dict[str, dict[str, Any]]
    universal: list[int]
    modules: dict[str, dict[str, Any]]
    value_tables: dict[str, list[tuple[int, str]]]
    alarms: list[tuple[int, str, str, str]]
    # address -> register covering it (for 32 bit second words, too)
    covered: dict[int, Register] = field(default_factory=dict)

    def options(self, table: str) -> list[str]:
        return [key for _value, key in self.value_tables[table]]

    def option_for(self, table: str, value: int) -> str | None:
        for val, key in self.value_tables[table]:
            if val == value:
                return key
        return None

    def value_for(self, table: str, option: str) -> int:
        for val, key in self.value_tables[table]:
            if key == option:
                return val
        raise ValueError(option)

    def selected_registers(
        self, boiler_type: str, modules: dict[str, list[str]]
    ) -> list[Register]:
        """All registers relevant for a configured installation."""
        addrs: list[int] = list(self.universal)
        addrs += self.boiler_types[boiler_type]["registers"]
        for module, indices in modules.items():
            info = self.modules.get(module)
            if not info or not indices:
                continue
            addrs += info["common"]
            if module == MODULE_CASCADE:
                continue
            for index in indices:
                addrs += info["instances"].get(index, [])
        seen: set[int] = set()
        result = []
        for addr in addrs:
            if addr not in seen:
                seen.add(addr)
                result.append(self.registers[addr])
        return result


def _load(path: Path) -> RegisterMap:
    raw = json.loads(path.read_text(encoding="utf-8"))
    registers = {int(a): Register(**r) for a, r in raw["registers"].items()}
    covered: dict[int, Register] = {}
    for reg in registers.values():
        for i in range(reg.count):
            covered[reg.address + i] = reg
    return RegisterMap(
        software_version=raw["software_version"],
        registers=registers,
        boiler_types=raw["boiler_types"],
        universal=raw["universal"],
        modules=raw["modules"],
        value_tables={k: [tuple(o) for o in v] for k, v in raw["value_tables"].items()},
        alarms=[tuple(a) for a in raw["alarms"]],
        covered=covered,
    )


@cache
def load_register_map() -> RegisterMap:
    """Load the bundled register map (blocking, run in executor)."""
    return _load(Path(__file__).parent / "registers.json")
