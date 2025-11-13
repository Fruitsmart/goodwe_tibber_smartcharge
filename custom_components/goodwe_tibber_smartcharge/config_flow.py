import logging
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.const import CONF_NAME

from .const import (
    DOMAIN,
    CONF_TIBBER_API_TOKEN,
    CONF_PV_SENSOR,
    CONF_BATTERY_SOC_SENSOR,
    CONF_WORK_MODE_SELECTOR,
    CONF_EXPORT_LIMIT_SWITCH,
    CONF_CHARGE_HOURS,
    CONF_PV_THRESHOLD,
    DEFAULT_CHARGE_HOURS,
    DEFAULT_PV_THRESHOLD,
)

_LOGGER = logging.getLogger(__name__)

class GoodWeTibberSmartChargeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for GoodWe Tibber Smart Charge."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}
        if user_input is not None:
            # Hier könnte man den Tibber API Token validieren
            # await self._validate_tibber_token(user_input[CONF_TIBBER_API_TOKEN])
            return self.async_create_entry(title=user_input[CONF_NAME], data=user_input)

        data_schema = vol.Schema({
            vol.Required(CONF_NAME, default="GoodWe Tibber Smart Charge"): str,
            vol.Required(CONF_TIBBER_API_TOKEN): str,
            vol.Required(CONF_PV_SENSOR): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor", device_class="power")),
            vol.Required(CONF_BATTERY_SOC_SENSOR): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor", device_class="battery")),
            vol.Required(CONF_WORK_MODE_SELECTOR): selector.EntitySelector(selector.EntitySelectorConfig(domain="select")),
            vol.Required(CONF_EXPORT_LIMIT_SWITCH): selector.EntitySelector(selector.EntitySelectorConfig(domain="switch")),
            vol.Optional(CONF_CHARGE_HOURS, default=DEFAULT_CHARGE_HOURS): int,
            vol.Optional(CONF_PV_THRESHOLD, default=DEFAULT_PV_THRESHOLD): int,
        })
        return self.async_show_form(step_id="user", data_schema=data_schema, errors=errors)

    # Optional: Eine Methode zur Validierung des Tibber Tokens
    # async def _validate_tibber_token(self, token):
    #     """Validate the Tibber token."""
    #     try:
    #         # Beispiel: Testanfrage an Tibber API
    #         # req = await aiohttp.ClientSession().post(...)
    #         # if req.status == 200: return True
    #         return True # Platzhalter
    #     except Exception:
    #         raise ValueError("Invalid Tibber API Token")
