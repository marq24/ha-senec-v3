"""The senec integration."""
import logging
from datetime import timedelta
from typing import Final

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_SCAN_INTERVAL, CONF_TYPE, CONF_NAME, CONF_USERNAME, CONF_PASSWORD
from homeassistant.core import HomeAssistant, Event
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as config_val, entity_registry
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.entity import EntityDescription, Entity
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.loader import Integration, async_get_integration

from custom_components.senec.pysenec_ha import SenecLocal, InverterLocal, SenecOnline, util
from custom_components.senec.pysenec_ha.constants import (
    SENEC_SECTION_BMS,
    SENEC_SECTION_BMS_CELLS,
    SENEC_SECTION_ENERGY,
    SENEC_SECTION_FAN_SPEED,
    SENEC_SECTION_STATISTIC,
    SENEC_SECTION_PV1,
    SENEC_SECTION_PM1OBJ1,
    SENEC_SECTION_PM1OBJ2,
    SENEC_SECTION_PWR_UNIT,
    SENEC_SECTION_SOCKETS,
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
    MAIN_SWITCH_TYPES,
    MAIN_NUMBER_TYPES,
    MAIN_SELECT_TYPES,
    QUERY_BMS_KEY,
    QUERY_BMS_CELLS_KEY,
    QUERY_PV1_KEY,
    QUERY_PM1OBJ1_KEY,
    QUERY_PM1OBJ2_KEY,
    QUERY_FANDATA_KEY,
    QUERY_WALLBOX_KEY,
    QUERY_SOCKETS_KEY,
    QUERY_SPARE_CAPACITY_KEY,
    QUERY_PEAK_SHAVING_KEY,
    IGNORE_SYSTEM_STATE_KEY,
    SERVICE_SET_PEAKSHAVING,
    CONFIG_VERSION, CONFIG_MINOR_VERSION
)

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(seconds=60)

PLATFORMS = ["binary_sensor", "button", "number", "select", "sensor", "switch"]
CONFIG_SCHEMA = config_val.removed(DOMAIN, raise_if_present=False)


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry):
    if config_entry.version < CONFIG_VERSION:
        if config_entry.data is not None and len(config_entry.data) > 0:
            _LOGGER.debug(f"Migrating configuration from version {config_entry.version}.{config_entry.minor_version}")
            if config_entry.options is not None and len(config_entry.options):
                new_data = {**config_entry.data, **config_entry.options}
            else:
                new_data = config_entry.data
            hass.config_entries.async_update_entry(config_entry, data=new_data, options={}, version=CONFIG_VERSION, minor_version=CONFIG_MINOR_VERSION)
            _LOGGER.debug(f"Migration to configuration version {config_entry.version}.{config_entry.minor_version} successful")
    return True


async def async_setup(hass: HomeAssistant, config: dict):
    """Set up the senec component."""
    return True


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry):
    """Set up senec from a config entry."""
    global SCAN_INTERVAL
    # update_interval can be adjusted in the options (not for WebAPI)
    SCAN_INTERVAL = timedelta(seconds=config_entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_SENECV2))
    _LOGGER.info(f"Starting SENEC.Home Integration '{config_entry.data.get(CONF_NAME)}' with interval:{SCAN_INTERVAL} - ConfigEntry: {util.mask_map(dict(config_entry.as_dict()))}")

    if DOMAIN not in hass.data:
        value = "UNKOWN"
        hass.data.setdefault(DOMAIN, {"manifest_version": value})

    # check if we have a valid manifest_version
    the_integration = await async_get_integration(hass, DOMAIN)
    intg_version = the_integration.version if the_integration is not None else "UNKNOWN"
    coordinator = SenecDataUpdateCoordinator(hass, config_entry, intg_version)

    if CONF_TYPE in config_entry.data and config_entry.data[CONF_TYPE] == CONF_SYSTYPE_WEB:
        # we need to log in into the SenecApp and authenticate the user via the web-portal
        await coordinator.senec.authenticate_all()
        _LOGGER.info(f"authenticate_all() completed -> main data: {coordinator.senec.get_debug_login_data()}")

    await coordinator.async_refresh()
    if not coordinator.last_update_success:
        raise ConfigEntryNotReady
    else:
        # here we can do some init stuff (like read all data)...
        pass

    hass.data[DOMAIN][config_entry.entry_id] = coordinator

    if CONF_TYPE not in config_entry.data or config_entry.data[CONF_TYPE] in [CONF_SYSTYPE_SENEC, CONF_SYSTYPE_SENEC_V2]:
        # after the refresh, we should know if the lala.cgi return STATISTIC data
        # or not...
        coordinator._statistics_available = coordinator.senec.grid_total_export is not None
        await coordinator.senec.update_version()

        coordinator._device_type = SYSTYPE_NAME_SENEC
        temp_device_type = coordinator.senec.device_type
        if temp_device_type is None or temp_device_type == "UNKNOWN":
            temp_device_type = SYSTYPE_NAME_SENEC
        coordinator._device_model = f"{temp_device_type} | {coordinator.senec.batt_type}"
        coordinator._device_serial = f"S{coordinator.senec.device_id}"
        coordinator._device_version = coordinator.senec.versions

    elif CONF_TYPE in config_entry.data and config_entry.data[CONF_TYPE] == CONF_SYSTYPE_INVERTER:
        await coordinator.senec.update_version()
        coordinator._device_type = SYSTYPE_NAME_INVERTER
        coordinator._device_model = f"{coordinator.senec.device_name} Netbios: {coordinator.senec.device_netbiosname}"
        coordinator._device_serial = coordinator.senec.device_serial
        coordinator._device_version = coordinator.senec.device_versions

    elif CONF_TYPE in config_entry.data and config_entry.data[CONF_TYPE] == CONF_SYSTYPE_WEB:

        if coordinator.senec.product_name is None or coordinator.senec.product_name == "UNKNOWN_PROD_NAME":
            await coordinator.app_get_system_details()

        coordinator._device_type = SYSTYPE_NAME_WEBAPI
        coordinator._device_model = f"{coordinator.senec.product_name} | SENEC.Case: {coordinator.senec.senec_num}"
        coordinator._device_serial = coordinator.senec.serial_number
        coordinator._device_version = coordinator.senec.versions

        # Register Services
        senec_services = SenecService.SenecService(hass, config_entry, coordinator)
        hass.services.async_register(DOMAIN, SERVICE_SET_PEAKSHAVING, senec_services.set_peakshaving)

    await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)

    config_entry.async_on_unload(config_entry.add_update_listener(entry_update_listener))
    return True


async def get_integration_version(self, hass: HomeAssistant):
    try:
        integration: Integration = await hass.async_get_integration(DOMAIN)
        return integration.version
    except Exception:
        return "UNKNOWN"

# Map platforms to their corresponding search lists
PLATFORM_MAPPING: Final = {
    "sensor": MAIN_SENSOR_TYPES,
    "binary_sensor": MAIN_BIN_SENSOR_TYPES,
    "switch": MAIN_SWITCH_TYPES,
    "number": MAIN_NUMBER_TYPES,
    "select": MAIN_SELECT_TYPES
}
SECTION_MAPPING: Final = {
    SENEC_SECTION_PV1:      (QUERY_PV1_KEY,     "***** QUERY_PV1-DATA ********"),
    SENEC_SECTION_PM1OBJ1:  (QUERY_PM1OBJ1_KEY, "***** QUERY_PM1OBJ1-DATA ********"),
    SENEC_SECTION_PM1OBJ2:  (QUERY_PM1OBJ2_KEY, "***** QUERY_PM1OBJ2-DATA ********"),
    SENEC_SECTION_WALLBOX:  (QUERY_WALLBOX_KEY, "***** QUERY_WALLBOX-DATA ********"),
    SENEC_SECTION_BMS:      (QUERY_BMS_KEY,     "***** QUERY_BMS-DATA ********"),
    SENEC_SECTION_BMS_CELLS:(QUERY_BMS_CELLS_KEY,"***** QUERY_BMS-CELLS-DATA ********"),
    SENEC_SECTION_FAN_SPEED:(QUERY_FANDATA_KEY, "***** QUERY_FAN-DATA ********"),
    SENEC_SECTION_SOCKETS:  (QUERY_SOCKETS_KEY, "***** QUERY_SOCKET-DATA ********")
}

class SenecDataUpdateCoordinator(DataUpdateCoordinator):
    """Define an object to hold Senec data."""

    def __init__(self, hass: HomeAssistant, config_entry, intg_version: str):
        self._integration_version = intg_version
        """Initialize."""
        # Build-In INVERTER
        if CONF_TYPE in config_entry.data and config_entry.data[CONF_TYPE] == CONF_SYSTYPE_INVERTER:
            # host can be changed in the options...
            self._host = config_entry.data[CONF_HOST]
            self.senec = InverterLocal(host=self._host, inv_session=async_create_clientsession(hass), integ_version=self._integration_version)

        # WEB-API Version...
        elif CONF_TYPE in config_entry.data and config_entry.data[CONF_TYPE] == CONF_SYSTYPE_WEB:
            self._host = "mein-senec.de"

            app_master_plant_number = -1
            if CONF_DEV_MASTER_NUM in config_entry.data:
                app_master_plant_number = int(config_entry.data[CONF_DEV_MASTER_NUM])

            # user & pwd can be changed via the options...
            user = config_entry.data[CONF_USERNAME]
            pwd = config_entry.data[CONF_PASSWORD]

            # we need to know if the 'spare_capacity' and 'peak_shaving' code should be called or not?!
            opt = {
                QUERY_WALLBOX_KEY: False,
                QUERY_SPARE_CAPACITY_KEY: False,
                QUERY_PEAK_SHAVING_KEY: False
            }

            if hass is not None and config_entry.title is not None:
                # we do not need to listen to changed to the entity - since the integration will be automatically
                # restarted when an Entity of the integration will be disabled/enabled via the GUI (cool!) - but for
                # now I keep this for debugging why during initial setup of the integration the control 'spare_capacity'
                # will not be added [only 13 Entities - after restart there are 14!]
                # event.async_track_entity_registry_updated_event(hass=hass, entity_ids=sce_id, action=self)

                # this is enough to check the current enabled/disabled status of the 'spare_capacity' control
                registry = entity_registry.async_get(hass)

                if registry is not None:
                    all_entities = entity_registry.async_entries_for_config_entry(registry, config_entry.entry_id)
                    _LOGGER.debug(f"all entities for config_entry {config_entry.entry_id} [{config_entry.title}] fetched - total number is: {len(all_entities)}")
                    for a_entity in all_entities:
                        if a_entity.disabled_by is None:
                            _LOGGER.debug(f"Entity '{a_entity.entity_id}' is enabled for {config_entry.title}")

                            # Spare Capacity
                            if not opt[QUERY_SPARE_CAPACITY_KEY] and a_entity.entity_id.startswith("number."):
                                if a_entity.entity_id.endswith("_spare_capacity"):
                                    _LOGGER.info("***** QUERY_SPARE_CAPACITY! ********")
                                    opt[QUERY_SPARE_CAPACITY_KEY] = True

                            # Peak Shaving
                            if not opt[QUERY_PEAK_SHAVING_KEY] and a_entity.entity_id.startswith("sensor."):
                                a_id = a_entity.entity_id
                                if any(a_id.endswith(suffix) for suffix in ("_gridexport_limit", "_peakshaving_mode", "_peakshaving_capacitylimit", "_peakshaving_enddate")):
                                    _LOGGER.info("***** QUERY_PEAK_SHAVING! ********")
                                    opt[QUERY_PEAK_SHAVING_KEY] = True

                            # when we have both, we can break the loop
                            if opt[QUERY_PEAK_SHAVING_KEY] and opt[QUERY_SPARE_CAPACITY_KEY]:
                                break

                    # we need to check, if there are any Wallbox entities...
                    # opt[QUERY_WALLBOX_KEY] = True

            # we will not set the master_plant number any longer - we will always use "autodetect" option, since the
            # The SenecApp use a master_plant_id while the MeinSenec.de web is using a master_plant_number (and to make
            # things worse, the App just can have one master_plant, while the web can have multiple...
            # once more: "Thanks for Nothing!")
            # SO to get out of this mess, we will store the master_plant_id in our config entry and use this as our
            # general key - then when we access the web-portal, we will use assigned serial_number to the master_plant_id
            # and then query the web-portal anlagenNummer 0,1,2 ... till we find the one with the matching serial_number
            self.senec = SenecOnline(user=user, pwd=pwd, web_session=async_create_clientsession(hass),
                                     app_master_plant_number=app_master_plant_number,  # we will not set the master_plant number - we will always use "autodetect
                                     lang=hass.config.language.lower(),
                                     options=opt,
                                     integ_version=self._integration_version)
            self._warning_counter = 0
            max_val = max(20, config_entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_SENECV2))
            SCAN_INTERVAL = timedelta(seconds=max_val)

        # lala.cgi Version...
        else:
            # host can be changed in the options...
            self._host = config_entry.data[CONF_HOST]
            if CONF_USE_HTTPS in config_entry.data:
                self._use_https = config_entry.data[CONF_USE_HTTPS]
            else:
                self._use_https = False

            opt = {
                IGNORE_SYSTEM_STATE_KEY: config_entry.data.get(CONF_IGNORE_SYSTEM_STATE, False),
                QUERY_PV1_KEY: False,
                QUERY_PM1OBJ1_KEY: False,
                QUERY_PM1OBJ2_KEY: False,
                QUERY_BMS_KEY: False,
                QUERY_BMS_CELLS_KEY: False,
                QUERY_WALLBOX_KEY: False,
                QUERY_FANDATA_KEY: False,
                QUERY_SOCKETS_KEY: False
            }

            # check if any of the wallbox-sensors is enabled... and only THEN
            # we will include the 'WALLBOX' in our POST to the lala.cgi
            if hass is not None and config_entry.entry_id is not None:
                registry = entity_registry.async_get(hass)
                if registry is not None:
                    all_entities = entity_registry.async_entries_for_config_entry(registry, config_entry.entry_id)
                    _LOGGER.debug(f"all entities for config_entry {config_entry.entry_id} [{config_entry.title}] fetched - total number is: {len(all_entities)}")
                    for a_entity in all_entities:
                        if a_entity.disabled_by is None:
                            _LOGGER.debug(f"Entity '{a_entity.entity_id}' is enabled for {config_entry.title}")
                            # check if the entity is a sensor, binary_sensor, switch, number or select
                            a_entity_platform = a_entity.entity_id.split(".")[0]
                            if a_entity_platform in PLATFORM_MAPPING:
                                for a_entity_desc in PLATFORM_MAPPING[a_entity_platform]:
                                    if a_entity.entity_id.endswith(a_entity_desc.key):
                                        if hasattr(a_entity_desc, "senec_lala_section"):
                                            a_lala_section  = a_entity_desc.senec_lala_section
                                            if a_lala_section in SECTION_MAPPING:
                                                query_option_key, a_log_msg = SECTION_MAPPING[a_lala_section]
                                                if not opt[query_option_key]:
                                                    opt[query_option_key] = True
                                                    _LOGGER.info(a_log_msg)

                                        _LOGGER.debug(f"Found a EntityDescription for '{a_entity.entity_id}' key: {a_entity_desc.key}")
                                        break

            self.senec = SenecLocal(host=self._host, use_https=self._use_https, lala_session=async_create_clientsession(hass, verify_ssl=False),
                                    lang=hass.config.language.lower(), options=opt,
                                    integ_version=self._integration_version)

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

    async def _async_is2408_or_later(self) -> bool:
        return await self.senec._is_2408_or_higher_async()

    async def _async_update_data(self) -> dict:
        _LOGGER.debug(f"_async_update_data called")
        try:
            await self.senec.update()
            data = self.senec.dict_data();
            _LOGGER.debug(f"read: {util.mask_map(data)}")
            return data
        except UpdateFailed as exception:
            _LOGGER.warning(f"UpdateFailed: {exception}")
            raise UpdateFailed() from exception
        except BaseException as fatal:
            _LOGGER.warning(f"Exception (fatal): {type(fatal)} {fatal}")
            raise UpdateFailed() from fatal

    async def _async_switch_to_state(self, switch_key, state):
        try:
            await self.senec.switch(switch_key, state)
            return self.senec.dict_data()
        except UpdateFailed as exception:
            _LOGGER.warning(f"UpdateFailed: {exception}")
            raise UpdateFailed() from exception
        except BaseException as fatal:
            _LOGGER.warning(f"Exception (fatal): {type(fatal)} {fatal}")
            raise UpdateFailed() from fatal

    async def _async_switch_array_to_state(self, switch_array_key, array_pos, state):
        try:
            await self.senec.switch_array(switch_array_key, array_pos, state)
            return self.senec.dict_data()
        except UpdateFailed as exception:
            _LOGGER.warning(f"UpdateFailed: {exception}")
            raise UpdateFailed() from exception
        except BaseException as fatal:
            _LOGGER.warning(f"Exception (fatal): {type(fatal)} {fatal}")
            raise UpdateFailed() from fatal

    async def _async_set_string_value(self, set_str_key, value: str):
        try:
            await self.senec.set_string_value(set_str_key, value)
            return self.senec.dict_data()
        except UpdateFailed as exception:
            _LOGGER.warning(f"UpdateFailed: {exception}")
            raise UpdateFailed() from exception
        except BaseException as fatal:
            _LOGGER.warning(f"Exception (fatal): {type(fatal)} {fatal}")
            raise UpdateFailed() from fatal

    async def _async_trigger_button(self, trigger_key:str, payload: str):
        try:
            await self.senec._trigger_button(trigger_key, payload)
            return self.senec.dict_data()
        except UpdateFailed as exception:
            _LOGGER.warning(f"UpdateFailed: {exception}")
            raise UpdateFailed() from exception
        except BaseException as fatal:
            _LOGGER.warning(f"Exception (fatal): {type(fatal)} {fatal}")
            raise UpdateFailed() from fatal


async def async_unload_entry(hass: HomeAssistant, config_entry: ConfigEntry):
    """Unload Senec config entry."""
    _LOGGER.debug(f"async_unload_entry() called for entry: {config_entry.entry_id}")
    unload_ok = await hass.config_entries.async_unload_platforms(config_entry, PLATFORMS)

    if unload_ok:
        if DOMAIN in hass.data and config_entry.entry_id in hass.data[DOMAIN]:
            hass.data[DOMAIN].pop(config_entry.entry_id)

        if CONF_TYPE in config_entry.data and config_entry.data[CONF_TYPE] == CONF_SYSTYPE_WEB:
            hass.services.async_remove(DOMAIN, SERVICE_SET_PEAKSHAVING)  # Remove Service on unload

    return unload_ok


async def entry_update_listener(hass: HomeAssistant, config_entry: ConfigEntry) -> None:
    _LOGGER.debug(f"entry_update_listener() called for entry: {config_entry.entry_id}")
    await hass.config_entries.async_reload(config_entry.entry_id)


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
            dtype = self.coordinator._config_entry.data.get(CONF_DEV_TYPE, "UNKNOWN_TYPE")

        dmodel = self.coordinator._device_model
        if dmodel is None:
            dmodel = self.coordinator._config_entry.data.get(CONF_DEV_MODEL, "UNKNOWN_MODEL")

        dserial = self.coordinator._device_serial
        if dserial is None:
            dserial = self.coordinator._config_entry.data.get(CONF_DEV_SERIAL, "UNKNOWN_SERIAL")

        dversion = self.coordinator._device_version
        if dversion is None:
            dversion = self.coordinator._config_entry.data.get(CONF_DEV_VERSION, "UNKNOWN_VERSION")

        device = self._name

        # "hw_version": self.coordinator._config_entry.data.get(CONF_DEV_NAME, "UNKNOWN_HW_VERSION"),
        return {
            "identifiers": {(DOMAIN, self.coordinator._host, device)},
            "name": f"{dtype}: {device}",
            "model": f"{dmodel} [Serial: {dserial}]",
            "sw_version": dversion,
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
