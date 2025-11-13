"""Constants for the GoodWe Tibber Smart Charge integration."""

DOMAIN = "goodwe_tibber_smartcharge"

CONF_TIBBER_API_TOKEN = "tibber_api_token"
CONF_PV_SENSOR = "pv_sensor"
CONF_BATTERY_SOC_SENSOR = "battery_soc_sensor"
CONF_WORK_MODE_SELECTOR = "work_mode_selector"
CONF_EXPORT_LIMIT_SWITCH = "export_limit_switch"
CONF_CHARGE_HOURS = "charge_hours"
CONF_PV_THRESHOLD = "pv_threshold" # z.B. 50W

DEFAULT_CHARGE_HOURS = 3
DEFAULT_PV_THRESHOLD = 50

# Event names
EVENT_CHARGE_UPDATE = f"{DOMAIN}_charge_update"
