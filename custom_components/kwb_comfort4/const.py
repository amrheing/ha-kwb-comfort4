"""Constants for the KWB Comfort 4 integration."""

from __future__ import annotations

DOMAIN = "kwb_comfort4"
MANUFACTURER = "KWB"

CONF_UNIT_ID = "unit_id"
CONF_ADDRESS_OFFSET = "address_offset"
CONF_BOILER_TYPE = "boiler_type"
CONF_ACCESS_LEVEL = "access_level"
CONF_MODULES = "modules"
CONF_REQUEST_DELAY = "request_delay"
CONF_LIFETICK = "lifetick"
CONF_WORD_ORDER = "word_order"

ACCESS_USER = "user"
ACCESS_EXPERT = "expert"

DEFAULT_PORT = 502
DEFAULT_UNIT_ID = 1
DEFAULT_SCAN_INTERVAL = 30  # seconds; controller drops idle connections after 60 s
DEFAULT_REQUEST_DELAY = 0.5  # seconds between requests (KWB recommends 0.5 to 1 s)
DEFAULT_BOILER_TYPE = "easyfire"
# High word first. The manual says low word first, real controllers (SW 24.x)
# send high word first.
DEFAULT_WORD_ORDER = "big"

MODULE_HEATING_CIRCUIT = "heating_circuit"
MODULE_BUFFER = "buffer"
MODULE_DHW = "dhw"
MODULE_SECONDARY_HEAT = "secondary_heat"
MODULE_CIRCULATION = "circulation"
MODULE_SOLAR = "solar"
MODULE_CASCADE = "cascade"
MODULE_HEAT_METER = "heat_meter"

MODULES = (
    MODULE_HEATING_CIRCUIT,
    MODULE_BUFFER,
    MODULE_DHW,
    MODULE_SOLAR,
    MODULE_CIRCULATION,
    MODULE_SECONDARY_HEAT,
    MODULE_HEAT_METER,
    MODULE_CASCADE,
)

# Universal registers used by the integration itself
REG_SW_MAJOR = 8192
REG_SW_MINOR = 8193
REG_SW_PATCH = 8194
REG_ALARMS_PENDING = 8254
REG_LIFETICK = 24849
REG_CASCADE_BOILERS = 9499

# Block reading
MAX_BLOCK_REGISTERS = 100
MAX_BLOCK_GAP = 8
MAX_BLOCK_BITS = 1600
MAX_BIT_GAP = 130
RETRY_FAILED_AFTER = 600  # seconds before a register that failed is tried again
