"""The senec integration."""
import asyncio
import logging
from datetime import timedelta

import async_timeout
import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_SCAN_INTERVAL, CONF_TYPE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity import Entity, EntityDescription
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from custom_components.senec.pysenec_ha import Senec, Inverter

from .const import DEFAULT_HOST, DEFAULT_NAME, DOMAIN, MANUFACTURE, CONF_DEV_TYPE, CONF_DEV_NAME, CONF_DEV_SERIAL, CONF_DEV_VERSION

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(seconds=60)
CONFIG_SCHEMA = vol.Schema({DOMAIN: vol.Schema({})}, extra=vol.ALLOW_EXTRA)

PLATFORMS = ["sensor"]


async def async_setup(hass: HomeAssistant, config: dict):
    """Set up the senec component."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):

    global SCAN_INTERVAL
    SCAN_INTERVAL = timedelta(seconds=entry.options.get(CONF_SCAN_INTERVAL, 60))

    """Set up senec from a config entry."""
    session = async_get_clientsession(hass)

    coordinator = SenecDataUpdateCoordinator(hass, session, entry)

    await coordinator.async_refresh()

    if not coordinator.last_update_success:
        raise ConfigEntryNotReady

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    for platform in PLATFORMS:
        hass.async_create_task(hass.config_entries.async_forward_entry_setup(entry, platform))

    return True


class SenecDataUpdateCoordinator(DataUpdateCoordinator):
    """Define an object to hold Senec data."""

    def __init__(self, hass, session, entry):
        """Initialize."""
        self._host = entry.data[CONF_HOST]

        if (CONF_TYPE in entry.data and entry.data[CONF_TYPE] == 'inverter'):
            self.senec = Inverter(self._host, websession=session)
        else:
            self.senec = Senec(self._host, websession=session)

        self.name = entry.title
        self._entry = entry

        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=SCAN_INTERVAL)

    async def _async_update_data(self):
        """Update data via library."""
        with async_timeout.timeout(20):
            await self.senec.update()
        return self.senec


async def async_unload_entry(hass, entry):
    """Unload Senec config entry."""
    unload_ok = all(
        await asyncio.gather(
            *[
                hass.config_entries.async_forward_entry_unload(entry, component)
                for component in PLATFORMS
            ]
        )
    )
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok


class SenecEntity(Entity):
    """Defines a base Senec entity."""

    _attr_should_poll = False

    def __init__(
        self, coordinator: SenecDataUpdateCoordinator, description: EntityDescription
    ) -> None:
        """Initialize the Atag entity."""
        self.coordinator = coordinator
        self._name = coordinator._entry.title
        self._state = None
        self._entry = coordinator._entry
        self.entity_description = description

    @property
    def device_info(self) -> dict:
        """Return info for device registry."""
        # Setup Device
        dtype = self._entry.options.get(CONF_DEV_TYPE, self._entry.data.get(CONF_DEV_TYPE))
        dserial = self._entry.options.get(CONF_DEV_SERIAL, self._entry.data.get(CONF_DEV_SERIAL))
        device = self._name
        return {
            "identifiers": {(DOMAIN, device)},
            "name": "SENEC.Home V3 System",
            "model": f"{dtype} [Serial: {dserial}]",
            "hw_version": self._entry.options.get(CONF_DEV_NAME, self._entry.data.get(CONF_DEV_NAME)),
            "sw_version": self._entry.options.get(CONF_DEV_VERSION, self._entry.data.get(CONF_DEV_VERSION)),
            "manufacturer": MANUFACTURE,
        }

    @property
    def state(self):
        """Return the current state."""
        sensor = self.entity_description.key
        value = getattr(self.coordinator.senec, sensor)
        try:
            rounded_value = round(float(value), 2)
            return rounded_value
        except (ValueError, TypeError):
            return value

    @property
    def available(self):
        """Return True if entity is available."""
        return self.coordinator.last_update_success

    @property
    def unique_id(self):
        """Return a unique ID to use for this entity."""
        sensor = self.entity_description.key
        return f"{self._name}_{sensor}"

    async def async_added_to_hass(self):
        """Connect to dispatcher listening for entity data notifications."""
        self.async_on_remove(self.coordinator.async_add_listener(self.async_write_ha_state))

    async def async_update(self):
        """Update entity."""
        await self.coordinator.async_request_refresh()
