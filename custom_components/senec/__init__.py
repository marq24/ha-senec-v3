"""The senec integration."""
import asyncio
import logging
import voluptuous as vol

from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_SCAN_INTERVAL, CONF_TYPE, CONF_USERNAME, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity import EntityDescription, Entity
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from custom_components.senec.pysenec_ha import Senec, Inverter, MySenecWebPortal

from .const import (
    DOMAIN,
    MANUFACTURE,
    DEFAULT_HOST,
    DEFAULT_NAME,
    CONF_USE_HTTPS,
    CONF_DEV_TYPE,
    CONF_DEV_NAME,
    CONF_DEV_SERIAL,
    CONF_DEV_VERSION,
    CONF_SYSTYPE_INVERTER,
    CONF_SYSTYPE_WEB
)

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(seconds=60)
CONFIG_SCHEMA = vol.Schema({DOMAIN: vol.Schema({})}, extra=vol.ALLOW_EXTRA)

PLATFORMS = ["sensor", "binary_sensor", "switch"]


async def async_setup(hass: HomeAssistant, config: dict):
    """Set up the senec component."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up senec from a config entry."""
    global SCAN_INTERVAL
    SCAN_INTERVAL = timedelta(seconds=entry.data.get(CONF_SCAN_INTERVAL, 60))

    session = async_get_clientsession(hass)

    coordinator = SenecDataUpdateCoordinator(hass, session, entry)

    await coordinator.async_refresh()

    if not coordinator.last_update_success:
        raise ConfigEntryNotReady

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    for platform in PLATFORMS:
        hass.async_create_task(hass.config_entries.async_forward_entry_setup(entry, platform))

    entry.add_update_listener(async_reload_entry)
    return True


class SenecDataUpdateCoordinator(DataUpdateCoordinator):
    """Define an object to hold Senec data."""

    def __init__(self, hass, session, entry):
        """Initialize."""
        if CONF_TYPE in entry.data and entry.data[CONF_TYPE] == CONF_SYSTYPE_INVERTER:
            self._host = entry.data[CONF_HOST]
            self.senec = Inverter(self._host, websession=session)
        if CONF_TYPE in entry.data and entry.data[CONF_TYPE] == CONF_SYSTYPE_WEB:
            self._host = "mein-senec.de"
            self.senec = MySenecWebPortal(user=entry.data[CONF_USERNAME], pwd=entry.data[CONF_PASSWORD], websession=session)
        else:
            self._host = entry.data[CONF_HOST]
            if CONF_USE_HTTPS in entry.data:
                self._use_https = entry.data[CONF_USE_HTTPS]
            else:
                self._use_https = False
            self.senec = Senec(host=self._host, use_https=self._use_https, websession=session)

        self.name = entry.title
        self._entry = entry

        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=SCAN_INTERVAL)

    async def _async_update_data(self):
        try:
            await self.senec.update()
            return self.senec
        except UpdateFailed as exception:
            raise UpdateFailed() from exception

    async def _async_switch_to_state(self, switch_key, state):
        try:
            await self.senec.switch(switch_key, state)
            return self.senec
        except UpdateFailed as exception:
            raise UpdateFailed() from exception


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


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)


class SenecEntity(Entity):
    """Defines a base Senec entity."""

    _attr_should_poll = False

    def __init__(
            self, coordinator: SenecDataUpdateCoordinator, description: EntityDescription
    ) -> None:
        self.coordinator = coordinator
        self.entity_description = description
        self._name = coordinator._entry.title
        self._state = None
        self._entry = coordinator._entry
        self._host = coordinator._host

    @property
    def device_info(self) -> dict:
        """Return info for device registry."""
        # Setup Device
        dtype = self._entry.options.get(CONF_DEV_TYPE, self._entry.data.get(CONF_DEV_TYPE))
        dserial = self._entry.options.get(CONF_DEV_SERIAL, self._entry.data.get(CONF_DEV_SERIAL))
        dmodel = self._entry.options.get(CONF_DEV_NAME, self._entry.data.get(CONF_DEV_NAME))
        device = self._name
        host = self._host
        # "hw_version": self._entry.options.get(CONF_DEV_NAME, self._entry.data.get(CONF_DEV_NAME)),
        return {
            "identifiers": {(DOMAIN, host, device)},
            "name": f"{dtype}: {device}",
            "model": f"{dmodel} [Serial: {dserial}]",
            "sw_version": self._entry.options.get(CONF_DEV_VERSION, self._entry.data.get(CONF_DEV_VERSION)),
            "manufacturer": MANUFACTURE,
        }

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

    @property
    def should_poll(self) -> bool:
        """Entities do not individually poll."""
        return False
