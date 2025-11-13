import logging
from datetime import timedelta, datetime
import asyncio
import aiohttp
import json

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval, async_call_later
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    DOMAIN,
    CONF_TIBBER_API_TOKEN,
    CONF_PV_SENSOR,
    CONF_BATTERY_SOC_SENSOR,
    CONF_WORK_MODE_SELECTOR,
    CONF_EXPORT_LIMIT_SWITCH,
    CONF_CHARGE_HOURS,
    CONF_PV_THRESHOLD,
    DEFAULT_PV_THRESHOLD,
)

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up GoodWe Tibber Smart Charge from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    coordinator = GoodWeTibberSmartChargeCoordinator(hass, entry)
    await coordinator.async_setup()
    hass.data[DOMAIN][entry.entry_id] = coordinator

    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Unload a config entry."""
    coordinator: GoodWeTibberSmartChargeCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
    coordinator.async_unload()
    return True

class GoodWeTibberSmartChargeCoordinator:
    """Manages the Tibber price fetching and GoodWe control logic."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry):
        self.hass = hass
        self.entry = entry
        self.config = entry.data

        self.tibber_api_token = self.config[CONF_TIBBER_API_TOKEN]
        self.pv_sensor_entity_id = self.config[CONF_PV_SENSOR]
        self.battery_soc_sensor_entity_id = self.config[CONF_BATTERY_SOC_SENSOR]
        self.work_mode_selector_entity_id = self.config[CONF_WORK_MODE_SELECTOR]
        self.export_limit_switch_entity_id = self.config[CONF_EXPORT_LIMIT_SWITCH]
        self.charge_hours = self.config.get(CONF_CHARGE_HOURS, DEFAULT_CHARGE_HOURS)
        self.pv_threshold = self.config.get(CONF_PV_THRESHOLD, DEFAULT_PV_THRESHOLD)

        self.session = async_get_clientsession(hass)
        self._price_data = {}
        self._unsub_listeners = []

    async def async_setup(self):
        """Set up the coordinator."""
        # Setup listeners for time and Tibber price updates
        self._unsub_listeners.append(
            async_track_time_interval(self.hass, self._async_update_prices_and_control, timedelta(minutes=1))
        )
        # Initial run after setup
        await self._async_update_prices_and_control(None)

    def async_unload(self):
        """Unload the coordinator listeners."""
        for unsub in self._unsub_listeners:
            unsub()
        self._unsub_listeners = []

    async def _async_fetch_tibber_prices(self):
        """Fetch Tibber prices from the API."""
        url = "https://api.tibber.com/v1-beta/gql"
        headers = {
            "Authorization": self.tibber_api_token,
            "Content-Type": "application/json",
            "User-Agent": "HomeAssistant GoodWe Tibber Smart Charge"
        }
        payload = {
            "query": "{ viewer { homes { currentSubscription { status priceInfo (resolution: HOURLY) { current { total } today { total } tomorrow { total } } } } } }"
        }

        try:
            async with self.session.post(url, headers=headers, json=payload, timeout=10) as response:
                response.raise_for_status()
                data = await response.json()
                price_info = data["data"]["viewer"]["homes"][0]["currentSubscription"]["priceInfo"]
                self._price_data = price_info
                _LOGGER.debug("Successfully fetched Tibber prices: %s", price_info)
        except aiohttp.ClientError as e:
            _LOGGER.error("Error fetching Tibber prices: %s", e)
        except (json.JSONDecodeError, KeyError) as e:
            _LOGGER.error("Error parsing Tibber price data: %s", e)

    async def _async_get_current_states(self):
        """Get current states of relevant entities."""
        pv_power = self.hass.states.get(self.pv_sensor_entity_id)
        battery_soc = self.hass.states.get(self.battery_soc_sensor_entity_id)
        work_mode_selector = self.hass.states.get(self.work_mode_selector_entity_id)
        export_limit_switch = self.hass.states.get(self.export_limit_switch_entity_id)

        return {
            "pv_power": int(pv_power.state) if pv_power else 0,
            "battery_soc": int(battery_soc.state) if battery_soc else 100,
            "current_mode": work_mode_selector.state if work_mode_selector else None,
            "export_limit_active": export_limit_switch.state == 'on' if export_limit_switch else False,
        }

    async def _async_update_prices_and_control(self, now):
        """Main control loop."""
        # Fetch prices hourly, but only at minute 01 (similar to blueprint trigger)
        if now is None or now.minute == 1:
             await self._async_fetch_tibber_prices()

        if not self._price_data:
            _LOGGER.warning("No Tibber price data available. Skipping control loop.")
            return

        states = await self._async_get_current_states()
        pv_leistung = states["pv_power"]
        batterie_soc = states["battery_soc"]
        aktueller_modus = states["current_mode"]
        export_limit_active = states["export_limit_active"]

        # Determine if it's a cheap charging hour
        is_cheap_hour = await self._async_is_current_hour_cheap()

        # --- GoodWe Betriebsmodus Steuerung ---
        target_mode = None
        if is_cheap_hour and batterie_soc < 99 and pv_leistung <= 100:
            target_mode = "backup"
        else:
            target_mode = "general"

        if target_mode and aktueller_modus != target_mode:
            _LOGGER.info("Setting GoodWe work mode to '%s'", target_mode)
            await self.hass.services.async_call(
                "select", "select_option",
                {"entity_id": self.work_mode_selector_entity_id, "option": target_mode},
                blocking=True
            )

        # --- Exportsperre Steuerung ---
        if target_mode == "backup": # Laden aus dem Netz
            if export_limit_active:
                _LOGGER.info("Deactivating export limit for 'backup' mode.")
                await self.hass.services.async_call(
                    "switch", "turn_off",
                    {"entity_id": self.export_limit_switch_entity_id},
                    blocking=True
                )
        elif target_mode == "general": # Eigenverbrauch
            should_activate_export_limit = (batterie_soc < 99 and pv_leistung <= self.pv_threshold)
            should_deactivate_export_limit = (batterie_soc >= 99 or pv_leistung > self.pv_threshold)

            if should_activate_export_limit and not export_limit_active:
                _LOGGER.info("Activating export limit for 'general' mode (battery discharge/low PV).")
                await self.hass.services.async_call(
                    "switch", "turn_on",
                    {"entity_id": self.export_limit_switch_entity_id},
                    blocking=True
                )
            elif should_deactivate_export_limit and export_limit_active:
                _LOGGER.info("Deactivating export limit for 'general' mode (battery full/high PV).")
                await self.hass.services.async_call(
                    "switch", "turn_off",
                    {"entity_id": self.export_limit_switch_entity_id},
                    blocking=True
                )

    async def _async_is_current_hour_cheap(self):
        """Determine if the current hour is one of the cheapest for charging."""
        today_prices = self._price_data.get("today", [])
        tomorrow_prices = self._price_data.get("tomorrow", [])

        if not tomorrow_prices: # Not enough data for tomorrow, fall back to today only
            all_prices = today_prices
        else:
            # Combine today and tomorrow prices for sorting
            all_prices = today_prices + tomorrow_prices

        # Create price objects with actual timestamps for comparison
        combined_prices_with_time = []
        now = datetime.now()
        
        for i, price_data in enumerate(today_prices):
            timestamp = now.replace(hour=i, minute=0, second=0, microsecond=0).isoformat()
            combined_prices_with_time.append({"time": timestamp, "price": price_data["total"]})

        # For tomorrow's prices, assume it's for the next day's hours
        next_day = now + timedelta(days=1)
        for i, price_data in enumerate(tomorrow_prices):
            timestamp = next_day.replace(hour=i, minute=0, second=0, microsecond=0).isoformat()
            combined_prices_with_time.append({"time": timestamp, "price": price_data["total"]})
        
        if not combined_prices_with_time:
            _LOGGER.warning("No combined price data for calculating cheap hours.")
            return False

        # Sort prices and pick the cheapest hours
        sorted_prices = sorted(combined_prices_with_time, key=lambda x: x["price"])
        
        # Ensure we have enough prices to select from
        num_to_select = min(self.charge_hours, len(sorted_prices))
        cheapest_hours = sorted_prices[:num_to_select]

        current_hour_iso = now.replace(minute=0, second=0, microsecond=0).isoformat()
        
        for hour_info in cheapest_hours:
            if hour_info["time"] == current_hour_iso:
                return True
        return False
