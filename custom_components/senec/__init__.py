"""The senec integration."""
import asyncio
import logging
import voluptuous as vol

from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_SCAN_INTERVAL, CONF_TYPE, CONF_NAME, CONF_USERNAME, CONF_PASSWORD
from homeassistant.core import HomeAssistant, Event
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity import EntityDescription, Entity
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers import entity_registry, event
from homeassistant.util import slugify


from custom_components.senec.pysenec_ha import Senec, Inverter, MySenecWebPortal

from .const import (
    DOMAIN,
    MANUFACTURE,
    DEFAULT_HOST,
    DEFAULT_NAME,
    DEFAULT_SCAN_INTERVAL_SENECV2,
    CONF_USE_HTTPS,
    CONF_DEV_TYPE,
    CONF_DEV_NAME,
    CONF_DEV_SERIAL,
    CONF_DEV_VERSION,
    CONF_SYSTYPE_SENEC,
    CONF_SYSTYPE_SENEC_V2,
    CONF_SYSTYPE_INVERTER,
    CONF_SYSTYPE_WEB,
    CONF_DEV_MASTER_NUM,
    MAIN_SENSOR_TYPES,
    QUERY_WALLBOX_KEY,
    QUERY_SPARE_CAPACITY_KEY,
)

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(seconds=60)
CONFIG_SCHEMA = vol.Schema({DOMAIN: vol.Schema({})}, extra=vol.ALLOW_EXTRA)

PLATFORMS = ["sensor", "binary_sensor", "switch", "number"]


async def async_setup(hass: HomeAssistant, config: dict):
    """Set up the senec component."""
    return True


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry):
    """Set up senec from a config entry."""
    global SCAN_INTERVAL

    # update_interval can be adjusted in the options (not for WebAPI)
    SCAN_INTERVAL = timedelta(seconds=config_entry.options.get(CONF_SCAN_INTERVAL,
                                                               config_entry.data.get(CONF_SCAN_INTERVAL,
                                                                                     DEFAULT_SCAN_INTERVAL_SENECV2)))

    _LOGGER.info("Starting "+str(config_entry.data.get(CONF_NAME))+" with interval: "+str(SCAN_INTERVAL))

    session = async_get_clientsession(hass)

    coordinator = SenecDataUpdateCoordinator(hass, session, config_entry)

    await coordinator.async_refresh()

    if not coordinator.last_update_success:
        raise ConfigEntryNotReady

    # after the refresh we should know if the lala.cgi return STATISTIC data
    # or not...
    if CONF_TYPE not in config_entry.data or config_entry.data[CONF_TYPE] in (
            CONF_SYSTYPE_SENEC, CONF_SYSTYPE_SENEC_V2):
        coordinator._statistics_available = coordinator.senec.grid_total_export is not None

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][config_entry.entry_id] = coordinator

    for platform in PLATFORMS:
        hass.async_create_task(hass.config_entries.async_forward_entry_setup(config_entry, platform))

    config_entry.add_update_listener(async_reload_entry)
    return True


class SenecDataUpdateCoordinator(DataUpdateCoordinator):
    """Define an object to hold Senec data."""

    def __init__(self, hass: HomeAssistant, session, config_entry):
        """Initialize."""

        # Build-In INVERTER
        if CONF_TYPE in config_entry.data and config_entry.data[CONF_TYPE] == CONF_SYSTYPE_INVERTER:
            # host can be changed in the options...
            self._host = config_entry.options.get(CONF_HOST, config_entry.data[CONF_HOST])
            self.senec = Inverter(self._host, websession=session)

        # WEB-API Version...
        if CONF_TYPE in config_entry.data and config_entry.data[CONF_TYPE] == CONF_SYSTYPE_WEB:
            self._host = "mein-senec.de"

            a_master_plant_number = 0
            if CONF_DEV_MASTER_NUM in config_entry.data:
                a_master_plant_number = config_entry.data[CONF_DEV_MASTER_NUM]

            # user & pwd can be changed via the options...
            user = config_entry.options.get(CONF_USERNAME, config_entry.data[CONF_USERNAME])
            pwd = config_entry.options.get(CONF_PASSWORD, config_entry.data[CONF_PASSWORD])

            # we need to know if the 'spare_capacity' code should be called or not?!
            opt = {QUERY_SPARE_CAPACITY_KEY: False}
            if hass is not None and config_entry.title is not None:
                sce_id = f"number.{slugify(config_entry.title)}_spare_capacity"

                # we do not need to listen to changed to the entity - since the integration will be automatically
                # restarted when an Entity of the integration will be disabled/enabled via the GUI (cool!) - but for
                # now I keep this for debugging why during initial setup of the integration the control 'spare_capacity'
                # will not be added [only 13 Entities - after restart there are 14!]
                event.async_track_entity_registry_updated_event(hass=hass, entity_ids=sce_id, action=self)

                # this is enough to check the current enabled/disabled status of the 'spare_capacity' control
                registry = entity_registry.async_get(hass)
                if registry is not None:
                    spare_capacity_entity = registry.async_get(sce_id)
                    if spare_capacity_entity is not None:
                        if spare_capacity_entity.disabled_by is None:
                            _LOGGER.info("***** QUERY_SPARE_CAPACITY! ********")
                            opt[QUERY_SPARE_CAPACITY_KEY] = True

            self.senec = MySenecWebPortal(user=user, pwd=pwd, websession=session,
                                          master_plant_number=a_master_plant_number,
                                          options=opt)
        # lala.cgi Version...
        else:
            # host can be changed in the options...
            self._host = config_entry.options.get(CONF_HOST, config_entry.data[CONF_HOST])
            if CONF_USE_HTTPS in config_entry.data:
                self._use_https = config_entry.data[CONF_USE_HTTPS]
            else:
                self._use_https = False

            # check if any of the wallbox-sensors is enabled... and only THEN
            # we will include the 'WALLBOX' in our POST to the lala.cgi
            opt = {QUERY_WALLBOX_KEY: False}
            if hass is not None and config_entry.title is not None:
                registry = entity_registry.async_get(hass)
                if registry is not None:
                    sluged_title = slugify(config_entry.title)
                    for description in MAIN_SENSOR_TYPES:
                        if not opt[QUERY_WALLBOX_KEY] and 'wallbox_' in description.key:
                            a_sensor_id = f"sensor.{sluged_title}_{description.key}"
                            a_entity = registry.async_get(a_sensor_id)
                            if a_entity is not None and a_entity.disabled_by is None:
                                _LOGGER.info("***** QUERY_WALLBOX-DATA ********")
                                opt[QUERY_WALLBOX_KEY] = True

            self.senec = Senec(host=self._host, use_https=self._use_https, websession=session, options=opt)

        self.name = config_entry.title
        self._config_entry = config_entry
        self._statistics_available = False
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=SCAN_INTERVAL)

    # Callable[[Event], Any]
    def __call__(self, evt: Event) -> bool:
        # just as testing the 'event.async_track_entity_registry_updated_event'
        _LOGGER.warning(str(evt))
        return True

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


async def async_unload_entry(hass: HomeAssistant, config_entry: ConfigEntry):
    """Unload Senec config entry."""
    unload_ok = all(
        await asyncio.gather(
            *[
                hass.config_entries.async_forward_entry_unload(config_entry, component)
                for component in PLATFORMS
            ]
        )
    )
    if unload_ok:
        hass.data[DOMAIN].pop(config_entry.entry_id)
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> None:
    """Reload config entry."""
    await async_unload_entry(hass, config_entry)
    await async_setup_entry(hass, config_entry)


class SenecEntity(Entity):
    """Defines a base Senec entity."""

    _attr_should_poll = False

    def __init__(
            self, coordinator: SenecDataUpdateCoordinator, description: EntityDescription
    ) -> None:
        self.coordinator = coordinator
        self.entity_description = description
        self._name = coordinator._config_entry.title
        self._state = None

    @property
    def device_info(self) -> dict:
        """Return info for device registry."""
        # Setup Device
        dtype = self.coordinator._config_entry.options.get(CONF_DEV_TYPE,
                                                           self.coordinator._config_entry.data.get(CONF_DEV_TYPE))
        dserial = self.coordinator._config_entry.options.get(CONF_DEV_SERIAL,
                                                             self.coordinator._config_entry.data.get(CONF_DEV_SERIAL))
        dmodel = self.coordinator._config_entry.options.get(CONF_DEV_NAME,
                                                            self.coordinator._config_entry.data.get(CONF_DEV_NAME))
        device = self._name
        # "hw_version": self.coordinator._config_entry.options.get(CONF_DEV_NAME, self.coordinator._config_entry.data.get(CONF_DEV_NAME)),
        return {
            "identifiers": {(DOMAIN, self.coordinator._host, device)},
            "name": f"{dtype}: {device}",
            "model": f"{dmodel} [Serial: {dserial}]",
            "sw_version": self.coordinator._config_entry.options.get(CONF_DEV_VERSION,
                                                                     self.coordinator._config_entry.data.get(
                                                                         CONF_DEV_VERSION)),
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
