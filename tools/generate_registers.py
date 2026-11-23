#!/usr/bin/env python3
"""Generate the register map and entity translations from KWB ModbusInfo files.

Usage:
    python tools/generate_registers.py ModbusInfo-en-V21.9.0.xlsx ModbusInfo-de-V21.9.0.xlsx

KWB publishes one ModbusInfo.xlsx per controller software version (on the SD
card of the Comfort 4 controller, or on request from KWB). The workbooks are
not part of this repository; only the derived register map is.

Writes:
    custom_components/kwb_comfort4/registers.json
    custom_components/kwb_comfort4/strings.json         (entity section)
    custom_components/kwb_comfort4/translations/en.json (entity section)
    custom_components/kwb_comfort4/translations/de.json (entity section)
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parent.parent
COMPONENT = ROOT / "custom_components" / "kwb_comfort4"

# English sheet name -> (kind, key)
BOILER_SHEETS = {
    "KWB Easyfire": "easyfire",
    "KWB Multifire": "multifire",
    "KWB Pelletfire+": "pelletfire_plus",
    "KWB Combifire": "combifire",
    "KWB CF 2": "cf2",
    "KWB CF 1": "cf1",
    "KWB CF 1.5": "cf1_5",
    "WMM Autonom": "wmm",
}
MODULE_SHEETS = {
    "Heating circuits": "heating_circuit",
    "Buffer storage tank": "buffer",
    "DHWC": "dhw",
    "Secondary heating sources": "secondary_heat",
    "Circulation": "circulation",
    "Solar": "solar",
    "Boiler master-and-slave circuit": "cascade",
    "Heat quantity meter": "heat_meter",
}
UNIVERSAL_SHEET = "Universal"
DE_SHEET = {
    "Heating circuits": "Heizkreise",
    "Buffer storage tank": "Pufferspeicher",
    "DHWC": "Brauchwasserspeicher",
    "Secondary heating sources": "Zweitwärmequellen",
    "Circulation": "Zirkulation",
    "Boiler master-and-slave circuit": "Kesselfolgeschaltung",
    "Heat quantity meter": "Wärmemengenzähler",
}

# Register whose ".status" decides whether an instance of a module is present.
PROBES = {
    "heating_circuit": "HK.i_vorlauf_temperatur.status",
    "buffer": "PUF.i_ist_temperatur_1.status",
    "dhw": "BOI.i_ist_temperatur.status",
    "secondary_heat": "ZK.i_temperatur.status",
    "circulation": "ZIRK.i_temperatur.status",
    "solar": "SOL.i_kollektor_temperatur.status",
}

# Entities enabled by default (all others are created disabled).
DEFAULT_ENABLED = {
    # universal / boiler
    "KSM.anlage_stoerung",
    "SYSTEM.alarme_offen",
    "SYSTEM.alarme_beheben_von_extern",
    "SYSTEM.i_aussen_temperatur.value",
    "KSM.i_kesseltemp_ist.value",
    "KSM.kesseltemp_soll",
    "KSM.DO_Kesselpumpe",
    "KSM.kesselpumpe_steuerstufe",
    "KSM.i_ruecklauftemp_ist.value",
    "KSM.brennerleistung",
    "KSM.kesselstatus_anzeige",
    "KSM.Betriebsminuten_Summe",
    "KSM.i_flammtemp_ist.value",
    "KSM.i_rauchgastemp_ist.value",
    "KSM.ServiceintervallReststunden",
    "KSM.aschefuellstand",
    "KSM.restmenge_brennstofflager",
    "FS.pelletsverbrauch",
    "AK.anlage_ein",
    "AK.kesselstatus_anzeige_ak",
    "CF2.kesselstatus_anzeige_sh",
    "CF2.kesseltemp_soll_1",
    # heating circuit
    "HK.i_vorlauf_temperatur.value",
    "HK.vorlauf_temperatur_soll",
    "HK.i_raum_temperatur.value",
    "HK.raum_temperatur_soll",
    "HK.o_pumpe",
    "HK.status",
    "HK.programm",
    "HK.raum_temperatur_soll_tag",
    "HK.raum_temperatur_soll_nacht",
    # buffer
    "PUF.i_ist_temperatur_1.value",
    "PUF.i_ist_temperatur_2.value",
    "PUF.i_ist_temperatur_3.value",
    "PUF.i_ist_temperatur_4.value",
    "PUF.i_ist_temperatur_5.value",
    "PUF.o_pumpe",
    "PUF.programm",
    # dhw
    "BOI.i_ist_temperatur.value",
    "BOI.soll_temperatur",
    "BOI.o_pumpe",
    "BOI.status",
    "BOI.programm",
    "BOI.schnellladung",
    # circulation / secondary
    "ZIRK.i_temperatur.value",
    "ZIRK.o_pumpe",
    "ZIRK.programm",
    "ZK.i_temperatur.value",
    "ZK.o_pumpe",
    # solar
    "SOL.status",
    "SOL.status_ursache",
    "SOL.i_kollektor_temperatur.value",
    "SOL.i_ist_temperatur_speicher_1.value",
    "SOL.o_pumpe_1",
    "SOL.pumpe_1_steuerstufe",
    "SOL.waermeleistung",
    "SOL.waermemenge_tag",
    "SOL.waermemenge_gesamt",
    # cascade
    "KFS.mittlere_puffertemperatur",
    "KFS.puffer_fuellgrad",
    "KFS.anzahl_angeforderte_kessel",
    # heat meter
    "MBUS.leistung",
    "MBUS.energie",
    "MBUS.vorlauftemp",
    "MBUS.ruecklauftemp",
}

# Registers that are only meaningful when Home Assistant acts as the Modbus
# master for output/temperature specification (needs the lifetick).
EXTERNAL_CONTROL = {
    "KSM.modbus_kesseltemp_vorgabe",
    "KSM.modbus_leistung_vorgabe",
    "KSM.modbus_kesselanforderung",
    "KSM.modbus_puffertemperatur_oben.value",
    "KSM.modbus_puffertemperatur_unten.value",
    "HK.modbus_anforderung",
    "HK.modbus_temperatur",
}
# Written by the integration itself, never exposed as entity.
INTERNAL = {"KSM.modbus_lifetick", "KSM.modbus_commit_lifetick"}
# Writable on/off registers that are momentary actions -> button.
BUTTONS = {"SYSTEM.alarme_beheben_von_extern"}

# Names that would clash with another entity or the device name
NAME_OVERRIDES = {
    "CF2.PM_Betriebsminuten_Summe": ("Full load hours pellet module", "Volllaststunden Pelletmodul"),
    "KFS.anlage_ein": ("Boiler cascade on/off", "Kesselfolgeschaltung Ein/Aus"),
}

UNIT_MAP = {
    "1/10°C": ("°C", 0.1),
    "1/10%": ("%", 0.1),
    "1/1000kW": ("kW", 0.001),
    "kWh": ("kWh", 1),
    "1/1000kWh": ("kWh", 0.001),
    "l/h": ("L/h", 1),
    "1/1000m³": ("m³", 0.001),
    "1/100l/min": ("L/min", 0.01),
    "min": ("min", 1),
    "h": ("h", 1),
    "rpm": ("rpm", 1),
    "kg": ("kg", 1),
    "1/10Pa": ("Pa", 0.1),
    "mm": ("mm", 1),
}


def slug(text: str) -> str:
    text = text.lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        text = text.replace(a, b)
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return text or "x"


def param_key(param: str) -> str:
    p = param[:-6] if param.endswith(".value") else param
    return slug(p)


def clean_name(name: str) -> str:
    name = re.sub(r"\s*\((value|Wert)\)\s*$", "", name).strip()
    return name


def rows(ws):
    it = ws.iter_rows(values_only=True)
    header = [h for h in next(it) if h is not None]
    for r in it:
        if r and r[0] is not None:
            d = dict(zip(header, r, strict=False))
            sa = d.get("StartingAddress")
            if isinstance(sa, str) and re.match(r"^\d+", sa):
                # the German sheets annotate some addresses like "8197 (8198)"
                d["StartingAddress"] = int(re.match(r"^\d+", sa).group(0))
            yield d


def index_label(idx: str | None) -> str | None:
    if not idx:
        return None
    return idx.split(" ", 1)[1]


def main(en_path: str, de_path: str) -> None:
    en = openpyxl.load_workbook(en_path, read_only=True)
    de = openpyxl.load_workbook(de_path, read_only=True)

    m = re.search(r"V(\d+\.\d+\.\d+)", Path(en_path).name)
    version = m.group(1) if m else "unknown"

    # value tables
    vt_en: dict[str, dict[int, str]] = defaultdict(dict)
    vt_de: dict[str, dict[int, str]] = defaultdict(dict)
    for r in rows(en["ValueTables"]):
        vt_en[r["ValueTable"]][int(r["Value"])] = str(r["Translation"]).strip()
    for r in rows(de["ValueTables"]):
        vt_de[r["ValueTable"]][int(r["Value"])] = str(r["Translation"]).strip()

    # Some tables (e.g. system_ein_aus_t) are missing on the ValueTables
    # sheet; take them from the "Values" column ("0-Off, 1-On").
    def parse_values(text):
        if not text or "(+" in str(text):
            return None
        out = {}
        for part in str(text).split(","):
            m = re.match(r"\s*(-?\d+)-(.*)", part)
            if not m:
                return None
            out[int(m.group(1))] = m.group(2).strip()
        return out or None

    for wb, target in ((en, vt_en), (de, vt_de)):
        for ws in wb.worksheets:
            if ws.title in ("Protocol", "Alarms", "ValueTables"):
                continue
            for r in rows(ws):
                table = r.get("Unit/ValueTable")
                if not table or not str(table).endswith("_t") or table in target:
                    continue
                parsed = parse_values(r.get("Values"))
                if parsed:
                    target[table] = parsed

    value_tables: dict[str, list[list]] = {}
    for table, values in vt_en.items():
        used: set[str] = set()
        opts = []
        for value, text in sorted(values.items()):
            key = slug(text)
            if key in used:
                key = f"{key}_{value}"
            used.add(key)
            opts.append([value, key, text, vt_de[table].get(value, text)])
        value_tables[table] = opts

    # German names by address per sheet
    def de_names(sheet_en: str) -> dict[int, str]:
        sheet = DE_SHEET.get(sheet_en, sheet_en)
        return {int(r["StartingAddress"]): str(r["Name"]) for r in rows(de[sheet])}

    registers: dict[int, dict] = {}
    names: dict[str, dict] = {}  # key -> {"en":..., "de":..., "indexed":bool}

    def add(sheet: str, r: dict, de_map: dict[int, str], module: str | None):
        addr = int(r["StartingAddress"])
        param = str(r["Parameter"])
        unit = r["Unit/ValueTable"]
        idx = r.get("Index") or None
        is_status = param.endswith(".status") and param.count(".") >= 2
        writable = "06" in str(r["Functions"]) or "16" in str(r["Functions"])
        rec = {
            "address": addr,
            "count": int(r["NumberOfRegisters"]),
            "type": str(r["Type"]),
            "fc": "holding" if writable else "input",
            "param": param,
            "key": param_key(param),
            "user_write": str(r["UserLevel"]).lower() == "readwrite",
            "expert_write": str(r["ExpertLevel"]).lower() == "readwrite",
        }
        if module:
            rec["module"] = module
        if idx:
            rec["index"] = index_label(str(idx))
            rec["index_raw"] = str(idx)
        if unit in UNIT_MAP:
            rec["unit"], rec["scale"] = UNIT_MAP[unit]
        elif unit and unit in value_tables:
            rec["value_table"] = unit
        elif unit:
            raise SystemExit(f"unknown unit {unit!r} at {addr}")
        if r.get("Min") not in (None, ""):
            rec["min"] = int(r["Min"])
        if r.get("Max") not in (None, ""):
            rec["max"] = int(r["Max"])
        if is_status:
            rec["role"] = "status"
        elif param in INTERNAL:
            rec["role"] = "internal"
        elif param in EXTERNAL_CONTROL:
            rec["role"] = "external_control"
        elif param in BUTTONS:
            rec["role"] = "button"
        else:
            rec["role"] = "entity"
        if param in DEFAULT_ENABLED:
            rec["default"] = True

        old = registers.get(addr)
        if old:
            if old["param"] != param:
                raise SystemExit(f"address {addr} differs: {old['param']} / {param}")
            return
        registers[addr] = rec
        if not is_status and rec["role"] != "internal":
            name_en = clean_name(str(r["Name"]))
            name_de = clean_name(de_map.get(addr, name_en))
            if param in NAME_OVERRIDES:
                name_en, name_de = NAME_OVERRIDES[param]
            k = rec["key"]
            # KFK registers are per cascade boiler (index "B n") on one device
            indexed = module == "cascade" and idx is not None
            if indexed:
                name_en = f"{name_en} boiler {{index}}"
                name_de = f"{name_de} Kessel {{index}}"
            if k in names and names[k]["en"] != name_en:
                # same parameter in several boiler sheets with other wording
                pass
            names.setdefault(k, {"en": name_en, "de": name_de, "regs": []})
            names[k]["regs"].append(addr)

    boiler_types: dict[str, dict] = {}
    for sheet, key in BOILER_SHEETS.items():
        dm = {int(r["StartingAddress"]): str(r["Name"]) for r in rows(de[sheet])}
        addrs = []
        for r in rows(en[sheet]):
            add(sheet, r, dm, None)
            addrs.append(int(r["StartingAddress"]))
        boiler_types[key] = {"title": sheet, "registers": sorted(addrs)}

    universal = []
    dm = {int(r["StartingAddress"]): str(r["Name"]) for r in rows(de[UNIVERSAL_SHEET])}
    for r in rows(en[UNIVERSAL_SHEET]):
        add(UNIVERSAL_SHEET, r, dm, None)
        universal.append(int(r["StartingAddress"]))

    modules: dict[str, dict] = {}
    for sheet, mkey in MODULE_SHEETS.items():
        dm = de_names(sheet)
        inst: dict[str, list[int]] = defaultdict(list)
        common: list[int] = []
        de_idx: dict[str, str] = {}
        de_rows = {int(r["StartingAddress"]): r for r in rows(de[DE_SHEET.get(sheet, sheet)])}
        for r in rows(en[sheet]):
            add(sheet, r, dm, mkey)
            addr = int(r["StartingAddress"])
            if mkey == "cascade":
                common.append(addr)
            elif r.get("Index"):
                inst[index_label(str(r["Index"]))].append(addr)
                drow = de_rows.get(addr)
                if drow and drow.get("Index"):
                    de_idx[index_label(str(r["Index"]))] = str(drow["Index"])
            else:
                common.append(addr)
        probe = None
        if mkey in PROBES:
            probe = {
                i: next(a for a in addrs if registers[a]["param"] == PROBES[mkey])
                for i, addrs in inst.items()
            }

        def sort_key(i: str):
            return tuple(int(p) for p in i.split("."))

        modules[mkey] = {
            "title": sheet,
            "instances": {i: sorted(inst[i]) for i in sorted(inst, key=sort_key)},
            "common": sorted(common),
            "probe": probe,
        }

    # link value registers to their status registers
    by_param_idx = {(v["param"], v.get("index_raw")): a for a, v in registers.items()}
    for v in registers.values():
        if v["param"].endswith(".value"):
            st = by_param_idx.get((v["param"][:-6] + ".status", v.get("index_raw")))
            if st:
                v["status"] = st

    alarms = []
    de_alarm = {int(r["StartingAddress"]): str(r["Translation"]) for r in rows(de["Alarms"])}
    for r in rows(en["Alarms"]):
        a = int(r["StartingAddress"])
        alarms.append([a, str(r["Alarm ID"]), str(r["Translation"]), de_alarm.get(a, "")])

    for v in registers.values():
        v.pop("index_raw", None)

    out = {
        "software_version": version,
        "boiler_types": boiler_types,
        "universal": sorted(universal),
        "modules": modules,
        "registers": {str(a): registers[a] for a in sorted(registers)},
        "value_tables": {k: [[o[0], o[1]] for o in v] for k, v in value_tables.items()},
        "alarms": alarms,
    }
    (COMPONENT / "registers.json").write_text(
        json.dumps(out, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8"
    )

    # ---- translations -------------------------------------------------
    def platforms(rec: dict) -> set[str]:
        res = set()
        vt = rec.get("value_table")
        onoff = vt in ("system_ein_aus_t", "system_yes_no_t")
        if rec["role"] == "button":
            res.add("button")
        if rec["role"] in ("entity", "external_control"):
            res.add("binary_sensor" if onoff else "sensor")
            if rec["fc"] == "holding" and (rec["user_write"] or rec["expert_write"]):
                res.add("switch" if onoff else ("select" if vt else "number"))
        return res

    def entity_section(lang: int) -> dict:
        sec: dict[str, dict] = defaultdict(dict)
        for key, info in names.items():
            recs = [registers[a] for a in info["regs"]]
            name = info["en"] if lang == 0 else info["de"]
            for rec in recs:
                for plat in platforms(rec):
                    entry = sec[plat].setdefault(key, {"name": name})
                    vt = rec.get("value_table")
                    if vt and plat in ("sensor", "select"):
                        entry["state"] = {
                            o[1]: (o[2] if lang == 0 else o[3]) for o in value_tables[vt]
                        }
        # extra, hand written entities
        extra_en = {
            "sensor": {
                "active_alarms": {"name": "Active alarms"},
                "software_version": {"name": "Software version"},
            },
            "binary_sensor": {"connection": {"name": "Modbus connection"}},
        }
        extra_de = {
            "sensor": {
                "active_alarms": {"name": "Aktive Alarme"},
                "software_version": {"name": "Softwareversion"},
            },
            "binary_sensor": {"connection": {"name": "Modbus-Verbindung"}},
        }
        for plat, ents in (extra_en if lang == 0 else extra_de).items():
            sec[plat].update(ents)
        return {p: dict(sorted(v.items())) for p, v in sorted(sec.items())}

    device_names = {
        "en": {
            "heating_circuit": "Heating circuit {index}",
            "buffer": "Buffer storage tank {index}",
            "dhw": "Domestic hot water {index}",
            "secondary_heat": "Secondary heat source {index}",
            "circulation": "Circulation {index}",
            "solar": "Solar {index}",
            "cascade": "Boiler cascade",
            "heat_meter": "Heat meter {index}",
        },
        "de": {
            "heating_circuit": "Heizkreis {index}",
            "buffer": "Pufferspeicher {index}",
            "dhw": "Brauchwasserspeicher {index}",
            "secondary_heat": "Zweitwärmequelle {index}",
            "circulation": "Zirkulation {index}",
            "solar": "Solar {index}",
            "cascade": "Kesselfolgeschaltung",
            "heat_meter": "Wärmemengenzähler {index}",
        },
    }

    for fname, lang, code in (
        ("strings.json", 0, "en"),
        ("translations/en.json", 0, "en"),
        ("translations/de.json", 1, "de"),
    ):
        path = COMPONENT / fname
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        data["entity"] = entity_section(lang)
        data["device"] = {k: {"name": v} for k, v in device_names[code].items()}
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    n_ent = sum(1 for v in registers.values() if v["role"] not in ("status", "internal"))
    print(f"V{version}: {len(registers)} registers ({n_ent} entity candidates), "
          f"{len(alarms)} alarms, {len(names)} translation keys")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    main(sys.argv[1], sys.argv[2])
