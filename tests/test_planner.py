"""Tests for register decoding and read planning."""

from custom_components.kwb_comfort4.coordinator import Block, plan_blocks, split_block
from custom_components.kwb_comfort4.registers import load_register_map


def test_decode_32bit_word_order():
    regmap = load_register_map()
    reg = regmap.registers[24927]  # residual fuel, u32
    # real controllers (SW 24.7) send the high word first
    assert reg.encode(70000) == [1, 70000 & 0xFFFF]
    assert reg.decode([0, 4059]) == 4059
    assert reg.decode([70000 & 0xFFFF, 1], "little") == 70000
    assert reg.encode(70000, "little") == [70000 & 0xFFFF, 1]
    signed = regmap.registers[8197]
    assert signed.decode([0xFFF6]) == -10


def test_plan_and_split():
    regmap = load_register_map()
    regs = [regmap.registers[a] for a in (8197, 8198, 8201, 8208, 8209, 8233)]
    blocks = plan_blocks(regs, regmap)
    assert blocks == [Block("input", 8197, 14), Block("input", 8233, 2)]
    # 8206 is not defined for an Easyfire... but it is for other boilers,
    # so the strict split keeps one run; the run is split into singles next
    wanted = {8197, 8198, 8201, 8208, 8209}
    subs = split_block(Block("input", 8197, 14), regmap, wanted)
    assert all(s.fc == "input" for s in subs)
    covered = {a for s in subs for a in range(s.start, s.start + s.count)}
    assert wanted <= covered


def test_selected_registers_contains_modules():
    regmap = load_register_map()
    regs = regmap.selected_registers("easyfire", {"heating_circuit": ["1.1"], "buffer": ["1"]})
    addrs = {r.address for r in regs}
    assert {8260, 24589, 24624, 8710, 8197, 8254} <= addrs
    assert 8262 not in addrs  # HC 1.2 not selected
