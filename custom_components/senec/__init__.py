"""The senec integration."""
import asyncio
import logging
import voluptuous as vol

from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_SCAN_INTERVAL, CONF_TYPE, CONF_NAME, CONF_USERNAME, CONF_PASSWORD
from homeassistant.core import HomeAssistant, Event
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity import EntityDescription, Entity
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers import entity_registry, event
from homeassistant.util import slugify

from custom_components.senec.pysenec_ha import Senec, Inverter, MySenecWebPortal
from custom_components.senec.pysenec_ha.constants import (
    SENEC_SECTION_BMS,
    SENEC_SECTION_ENERGY,
    SENEC_SECTION_FAN_SPEED,
    SENEC_SECTION_STATISTIC,
    SENEC_SECTION_PM1OBJ1,
    SENEC_SECTION_PM1OBJ2,
    SENEC_SECTION_PV1,
    SENEC_SECTION_PWR_UNIT,
    SENEC_SECTION_TEMPMEASURE,
    SENEC_SECTION_WALLBOX
)
from . import service as SenecService

from .const import (
    DOMAIN,
    MANUFACTURE,
    DEFAULT_HOST,
    DEFAULT_NAME,
    DEFAULT_SCAN_INTERVAL_SENECV2,

    SYSTYPE_NAME_SENEC,
    SYSTYPE_NAME_INVERTER,
    SYSTYPE_NAME_WEBAPI,

    CONF_USE_HTTPS,
    CONF_DEV_TYPE,
    CONF_DEV_MODEL,
    CONF_DEV_SERIAL,
    CONF_DEV_VERSION,
    CONF_SYSTYPE_SENEC,
    CONF_SYSTYPE_SENEC_V2,
    CONF_SYSTYPE_INVERTER,
    CONF_SYSTYPE_WEB,
    CONF_DEV_MASTER_NUM,
    CONF_IGNORE_SYSTEM_STATE,

    MAIN_SENSOR_TYPES,
    MAIN_BIN_SENSOR_TYPES,
    QUERY_BMS_KEY,
    QUERY_FANDATA_KEY,
    QUERY_WALLBOX_KEY,
    QUERY_SPARE_CAPACITY_KEY,
    QUERY_PEAK_SHAVING_KEY,
    IGNORE_SYSTEM_STATE_KEY,

    SERVICE_SET_PEAKSHAVING,
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

    _LOGGER.info("Starting " + str(config_entry.data.get(CONF_NAME)) + " with interval: " + str(SCAN_INTERVAL))

    coordinator = SenecDataUpdateCoordinator(hass, config_entry)
    await coordinator.async_refresh()
    if not coordinator.last_update_success:
        raise ConfigEntryNotReady

    if CONF_TYPE not in config_entry.data or config_entry.data[CONF_TYPE] in (
            CONF_SYSTYPE_SENEC, CONF_SYSTYPE_SENEC_V2):
        # after the refresh we should know if the lala.cgi return STATISTIC data
        # or not...
        coordinator._statistics_available = coordinator.senec.grid_total_export is not None

        await coordinator.senec.update_version()
        coordinator._device_type = SYSTYPE_NAME_SENEC
        coordinator._device_model = f"{coordinator.senec.device_type}  | {coordinator.senec.batt_type}"
        coordinator._device_serial = f"S{coordinator.senec.device_id}"
        coordinator._device_version = coordinator.senec.versions

    elif CONF_TYPE in config_entry.data and config_entry.data[CONF_TYPE] == CONF_SYSTYPE_INVERTER:
        await coordinator.senec.update_version()
        coordinator._device_type = SYSTYPE_NAME_INVERTER
        coordinator._device_model = f"{coordinator.senec.device_name} Netbios: {coordinator.senec.device_netbiosname}"
        coordinator._device_serial = coordinator.senec.device_serial
        coordinator._device_version = coordinator.senec.device_versions

    elif CONF_TYPE in config_entry.data and config_entry.data[CONF_TYPE] == CONF_SYSTYPE_WEB:
        await coordinator.senec.update_context()
        coordinator._device_type = SYSTYPE_NAME_WEBAPI
        coordinator._device_model = f"{coordinator.senec.product_name} | SENEC.Num: {coordinator.senec.senec_num}"
        coordinator._device_serial = coordinator.senec.serial_number
        coordinator._device_version = None  # senec_web_client.firmwareVersion

        # Register Services
        service = SenecService.SenecService(hass, config_entry, coordinator)
        hass.services.async_register(DOMAIN, SERVICE_SET_PEAKSHAVING, service.set_peakshaving)

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][config_entry.entry_id] = coordinator

    for platform in PLATFORMS:
        hass.async_create_task(hass.config_entries.async_forward_entry_setup(config_entry, platform))

    config_entry.add_update_listener(async_reload_entry)

    return True


class SenecDataUpdateCoordinator(DataUpdateCoordinator):
    """Define an object to hold Senec data."""

    def __init__(self, hass: HomeAssistant, config_entry):
        """Initialize."""
        # Build-In INVERTER
        if CONF_TYPE in config_entry.data and config_entry.data[CONF_TYPE] == CONF_SYSTYPE_INVERTER:
            # host can be changed in the options...
            self._host = config_entry.options.get(CONF_HOST, config_entry.data[CONF_HOST])
            self.senec = Inverter(self._host, web_session=async_get_clientsession(hass))

        # WEB-API Version...
        elif CONF_TYPE in config_entry.data and config_entry.data[CONF_TYPE] == CONF_SYSTYPE_WEB:
            self._host = "mein-senec.de"

            a_master_plant_number = 0
            if CONF_DEV_MASTER_NUM in config_entry.data:
                a_master_plant_number = config_entry.data[CONF_DEV_MASTER_NUM]

            # user & pwd can be changed via the options...
            user = config_entry.options.get(CONF_USERNAME, config_entry.data[CONF_USERNAME])
            pwd = config_entry.options.get(CONF_PASSWORD, config_entry.data[CONF_PASSWORD])

            # we need to know if the 'spare_capacity' and 'peak_shaving' code should be called or not?!
            opt = {QUERY_SPARE_CAPACITY_KEY: False, QUERY_PEAK_SHAVING_KEY: False}
            if hass is not None and config_entry.title is not None:
                sce_id = f"number.{slugify(config_entry.title)}_spare_capacity".lower()
                ps_gridlimit_id = f"sensor.{slugify(config_entry.title)}_gridexport_limit".lower()
                ps_mode_id = f"sensor.{slugify(config_entry.title)}_peakshaving_mode".lower()
                ps_capacity_id = f"sensor.{slugify(config_entry.title)}_peakshaving_capacitylimit".lower()
                ps_end_id = f"sensor.{slugify(config_entry.title)}_peakshaving_enddate".lower()

                # we do not need to listen to changed to the entity - since the integration will be automatically
                # restarted when an Entity of the integration will be disabled/enabled via the GUI (cool!) - but for
                # now I keep this for debugging why during initial setup of the integration the control 'spare_capacity'
                # will not be added [only 13 Entities - after restart there are 14!]
                # event.async_track_entity_registry_updated_event(hass=hass, entity_ids=sce_id, action=self)

                # this is enough to check the current enabled/disabled status of the 'spare_capacity' control
                registry = entity_registry.async_get(hass)

                if registry is not None:
                    # Spare Capacity
                    spare_capacity_entity = registry.async_get(sce_id)
                    if spare_capacity_entity is not None:
                        if spare_capacity_entity.disabled_by is None:
                            _LOGGER.info("***** QUERY_SPARE_CAPACITY! ********")
                            opt[QUERY_SPARE_CAPACITY_KEY] = True
                    # Peak Shaving
                    ps_gridlimit = registry.async_get(ps_gridlimit_id)
                    ps_mode = registry.async_get(ps_mode_id)
                    ps_capacity = registry.async_get(ps_capacity_id)
                    ps_end = registry.async_get(ps_end_id)

                    if ps_gridlimit is not None and ps_mode is not None and ps_capacity is not None and ps_end is not None:
                        if ps_gridlimit.disabled_by is None or ps_mode.disabled_by is None or ps_capacity.disabled_by is None or ps_end is None:
                            _LOGGER.info("***** QUERY_PEAK_SHAVING! ********")
                            opt[QUERY_PEAK_SHAVING_KEY] = True

            self.senec = MySenecWebPortal(user=user, pwd=pwd, web_session=async_create_clientsession(hass),
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

            opt = {
                IGNORE_SYSTEM_STATE_KEY: config_entry.options.get(CONF_IGNORE_SYSTEM_STATE, False),
                QUERY_WALLBOX_KEY: False,
                QUERY_BMS_KEY: False,
                QUERY_FANDATA_KEY: False
            }
            # check if any of the wallbox-sensors is enabled... and only THEN
            # we will include the 'WALLBOX' in our POST to the lala.cgi
            if hass is not None and config_entry.title is not None:
                registry = entity_registry.async_get(hass)
                if registry is not None:
                    sluged_title = slugify(config_entry.title)
                    for description in MAIN_SENSOR_TYPES:
                        if not opt[QUERY_WALLBOX_KEY] and SENEC_SECTION_WALLBOX == description.senec_lala_section:
                            a_sensor_id = f"sensor.{sluged_title}_{description.key}".lower()
                            a_entity = registry.async_get(a_sensor_id)
                            if a_entity is not None and a_entity.disabled_by is None:
                                _LOGGER.info("***** QUERY_WALLBOX-DATA ********")
                                opt[QUERY_WALLBOX_KEY] = True

                        if not opt[QUERY_BMS_KEY] and SENEC_SECTION_BMS == description.senec_lala_section:
                            a_sensor_id = f"sensor.{sluged_title}_{description.key}".lower()
                            a_entity = registry.async_get(a_sensor_id)
                            if a_entity is not None and a_entity.disabled_by is None:
                                _LOGGER.info("***** QUERY_BMS-DATA ********")
                                opt[QUERY_BMS_KEY] = True

                        # yes - currently only the 'MAIN_BIN_SENSOR's will contain the SENEC_SECTION_FAN_SPEED but
                        # I want to have here the complete code/overview 'what should be checked'
                        if not opt[QUERY_FANDATA_KEY] and SENEC_SECTION_FAN_SPEED == description.senec_lala_section:
                            a_sensor_id = f"sensor.{sluged_title}_{description.key}".lower()
                            a_entity = registry.async_get(a_sensor_id)
                            if a_entity is not None and a_entity.disabled_by is None:
                                _LOGGER.info("***** QUERY_FANSPEED-DATA ********")
                                opt[QUERY_FANDATA_KEY] = True

                    for description in MAIN_BIN_SENSOR_TYPES:
                        if not opt[QUERY_WALLBOX_KEY] and SENEC_SECTION_WALLBOX == description.senec_lala_section:
                            a_sensor_id = f"binary_sensor.{sluged_title}_{description.key}".lower()
                            a_entity = registry.async_get(a_sensor_id)
                            if a_entity is not None and a_entity.disabled_by is None:
                                _LOGGER.info("***** QUERY_WALLBOX-DATA ********")
                                opt[QUERY_WALLBOX_KEY] = True

                        if not opt[QUERY_FANDATA_KEY] and SENEC_SECTION_FAN_SPEED == description.senec_lala_section:
                            a_sensor_id = f"binary_sensor.{sluged_title}_{description.key}".lower()
                            a_entity = registry.async_get(a_sensor_id)
                            if a_entity is not None and a_entity.disabled_by is None:
                                _LOGGER.info("***** QUERY_FANSPEED-DATA ********")
                                opt[QUERY_FANDATA_KEY] = True

            self.senec = Senec(host=self._host, use_https=self._use_https, web_session=async_get_clientsession(hass),
                               lang=hass.config.language.lower(), options=opt)

        self.name = config_entry.title
        self._config_entry = config_entry

        self._device_type = None
        self._device_model = None
        self._device_serial = None
        self._device_version = None
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
        hass.services.async_remove(DOMAIN, SERVICE_SET_PEAKSHAVING) # Remove Service on unload
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

    @property
    def device_info(self) -> dict:
        """Return info for device registry."""
        # Setup Device

        dtype = self.coordinator._device_type
        if dtype is None:
            dtype = self.coordinator._config_entry.options.get(CONF_DEV_TYPE,
                                                               self.coordinator._config_entry.data.get(CONF_DEV_TYPE))

        dmodel = self.coordinator._device_model
        if dmodel is None:
            dmodel = self.coordinator._config_entry.options.get(CONF_DEV_MODEL,
                                                                self.coordinator._config_entry.data.get(CONF_DEV_MODEL))

        dserial = self.coordinator._device_serial
        if dserial is None:
            dserial = self.coordinator._config_entry.options.get(CONF_DEV_SERIAL,
                                                                 self.coordinator._config_entry.data.get(
                                                                     CONF_DEV_SERIAL))

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
