"""The senec integration."""
import asyncio
import logging
from datetime import timedelta
from pathlib import Path
from typing import Final

from custom_components.senec.pysenec_ha import SenecLocal, InverterLocal, SenecOnline, util, ReConfigurationRequired
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
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_SCAN_INTERVAL, CONF_TYPE, CONF_NAME, CONF_USERNAME, CONF_PASSWORD
from homeassistant.core import HomeAssistant, Event
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import entity_registry, config_validation as config_val, device_registry as device_reg
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.entity import EntityDescription, Entity
from homeassistant.helpers.storage import STORAGE_DIR
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.loader import async_get_integration
from . import service as SenecService
from .const import (
    StaticFuncs,
    DOMAIN,
    MANUFACTURE,
    DEFAULT_HOST,
    DEFAULT_NAME,
    DEFAULT_SCAN_INTERVAL_SENECV2,

    SYSTYPE_NAME_SENEC,
    SYSTYPE_NAME_INVERTER,
    SYSTYPE_NAME_WEBAPI,

    CONF_TOTP_SECRET,
    CONF_TOTP_URL,
    CONF_USE_HTTPS,
    CONF_DEV_TYPE,
    CONF_DEV_MODEL,
    CONF_DEV_SERIAL,
    CONF_DEV_VERSION,
    CONF_SYSTYPE_SENEC,
    CONF_SYSTYPE_SENEC_V2,
    CONF_SYSTYPE_INVERTER,
    CONF_SYSTYPE_WEB,
    CONF_IGNORE_SYSTEM_STATE,
    CONF_INCLUDE_WALLBOX_IN_HOUSE_CONSUMPTION,
    CONF_TOTP_ALREADY_USED,
    CONF_MUST_START_POST_MIGRATION_PROCESS,

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
    CONFIG_VERSION,
    CONFIG_MINOR_VERSION,
    QUERY_TOTALS_KEY,
    QUERY_SYSTEM_DETAILS_KEY,
    QUERY_SGREADY_KEY,
    STARTUP_MESSAGE
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["binary_sensor", "button", "number", "select", "sensor", "switch"]
CONFIG_SCHEMA = config_val.removed(DOMAIN, raise_if_present=False)
DEVICE_REG_CLEANUP_RUNNING = False
SKIP_NEXT_RELOAD_OF_WEB = False

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

    # update from 2.0 [completed wallbox implementation - and fixed total statistics stuff]
    if config_entry.version == 2:
        if config_entry.minor_version == 0:
            _LOGGER.info(f"Migration: from v{config_entry.version}.{config_entry.minor_version} to v{CONFIG_VERSION}.{CONFIG_MINOR_VERSION}")
            if CONF_TYPE in config_entry.data and config_entry.data[CONF_TYPE] == CONF_SYSTYPE_WEB:
                _LOGGER.info("Migration: for WebAPI we must clean the cache file ONCE")
                # we need to remove the cache file so that the next time we will
                # access the webAPI, we will get a fresh copy of the data
                user = config_entry.data.get(CONF_USERNAME, None)
                pwd = config_entry.data.get(CONF_PASSWORD, None)
                if user is not None:
                    # we just need the SenecOnline object to DELETE the access_token file...
                    web_api = SenecOnline(user=user, pwd=pwd, totp=None, web_session=None,
                                          storage_path=Path(hass.config.config_dir).joinpath(STORAGE_DIR),
                                          integ_version=f"MIGRATION_v{config_entry.version}.{config_entry.minor_version}_to_v{CONFIG_VERSION}.{CONFIG_MINOR_VERSION}")

                    # this will remove the cache file...
                    await web_api._write_token_to_storage(token_dict=None)
                    _LOGGER.info(f"Migration: cache file cleared for WebAPI - migrated to version {CONFIG_VERSION}.{CONFIG_MINOR_VERSION}")

            hass.config_entries.async_update_entry(config_entry, version=CONFIG_VERSION, minor_version=CONFIG_MINOR_VERSION)

        # update from 2.1 to 2.2 [mark config entry to purge data]
        if config_entry.minor_version == 1:
            _LOGGER.info(f"Migration: from v{config_entry.version}.{config_entry.minor_version} to v{CONFIG_VERSION}.{CONFIG_MINOR_VERSION}")
            if CONF_TYPE in config_entry.data and config_entry.data[CONF_TYPE] == CONF_SYSTYPE_WEB:
                _LOGGER.info("Migration: for WebAPI we must mark for clearing ONCE")

                # we must purge the 'last_stored_value' - but we can do that only during the loading phase of the config_entry
                new_config_entry_data = {**config_entry.data, **{CONF_MUST_START_POST_MIGRATION_PROCESS: True}}
                hass.config_entries.async_update_entry(config_entry, data=new_config_entry_data, version=CONFIG_VERSION, minor_version=CONFIG_MINOR_VERSION)
                _LOGGER.info(f"Migration: cache file marked for clearing for WebAPI - migrated to version {CONFIG_VERSION}.{CONFIG_MINOR_VERSION}")
            else:
                # do nothing for other system-types (inverter or local, just update the version info...
                hass.config_entries.async_update_entry(config_entry, version=CONFIG_VERSION, minor_version=CONFIG_MINOR_VERSION)

    return True


async def async_setup(hass: HomeAssistant, config: dict):
    """Set up the senec component."""
    return True


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry):
    """Set up senec from a config entry."""
    the_integration = await async_get_integration(hass, DOMAIN)
    intg_version = the_integration.version if the_integration is not None else "UNKNOWN"
    if DOMAIN not in hass.data:
        _LOGGER.info(STARTUP_MESSAGE % intg_version)
        hass.data.setdefault(DOMAIN, {"manifest_version": intg_version})

    # purge possible devices-check
    asyncio.create_task(check_device_registry(hass, config_entry.entry_id))

    log_scan_interval = timedelta(seconds=config_entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_SENECV2))
    _LOGGER.info(f"Starting SENEC.Home Integration '{config_entry.data.get(CONF_NAME)}' with interval:{log_scan_interval} - ConfigEntry: {util.mask_map(dict(config_entry.as_dict()))}")

    # check if we have a valid manifest_version
    coordinator = SenecDataUpdateCoordinator(hass, config_entry, intg_version)

    if CONF_TYPE in config_entry.data and config_entry.data[CONF_TYPE] == CONF_SYSTYPE_WEB:
        # we must check, if there is a legacy-token file (that does not contain the _app_master_plant_number in the filename)
        #await coordinator.senec._rename_token_file_if_needed(user=config_entry.data[CONF_USERNAME])
        await coordinator.senec._purge_old_token_files()

        # we need to log in into the SenecApp and authenticate the user via the web-portal
        try:
            await coordinator.senec.authenticate_all()
            _LOGGER.info(f"authenticate_all() completed -> main data: {util.mask_map(coordinator.senec.get_debug_login_data())}")
        except ReConfigurationRequired:
            _LOGGER.warning("ReConfigurationRequired - we need to re-authenticate the user")
            # we will not do this here, but let the HomeAssistant handle this for us
            # by calling the async_start_reauth() method on the config_entry
            hass.add_job(config_entry.async_start_reauth, hass)

    await coordinator.async_refresh()
    if not coordinator.last_update_success:
        raise ConfigEntryNotReady

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

        # Search the (optional) sibling SenecOnline for this SenecLocal via serialnumber and connect them
        for a_other_coord in hass.data[DOMAIN].values():
          if isinstance(a_other_coord, SenecDataUpdateCoordinator) and isinstance(a_other_coord.senec, SenecOnline):
            # we must ensure, that the 'a_other_coord' have already passed it's initialization-phase...
            max_wait_count = 0
            while max_wait_count < 5 and a_other_coord._device_serial is None:
                await asyncio.sleep(5)
                max_wait_count += 1

            if coordinator._device_serial == a_other_coord._device_serial:
                _LOGGER.info(f"SIBLING: ONLINE Sibling found for this SenecLocal[{util.mask_string(coordinator._device_serial)}]: {a_other_coord.senec}")
                coordinator.senec.set_senec_online_instance(a_other_coord.senec)
                a_other_coord.senec.set_senec_local_instance(coordinator.senec)

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

        # we launch the check_for_migration_tasks worker...
        hass.async_create_task(coordinator.check_for_post_migration_tasks(hass))

        # Search the (optional) sibling SenecLocal for this SenecOnline via serialnumber and connect them
        for a_other_coord in hass.data[DOMAIN].values():
          if isinstance(a_other_coord, SenecDataUpdateCoordinator) and isinstance(a_other_coord.senec, SenecLocal):
            # we must ensure that the 'a_other_coord' have already passed it's initialization-phase...
            max_wait_count = 0
            while max_wait_count < 5 and a_other_coord._device_serial is None:
                await asyncio.sleep(5)
                max_wait_count += 1

            if coordinator._device_serial == a_other_coord._device_serial:
                _LOGGER.info(f"SIBLING: LOCAL Sibling found for this SenecOnline[{util.mask_string(coordinator._device_serial)}]: {a_other_coord.senec}")
                coordinator.senec.set_senec_local_instance(a_other_coord.senec)
                a_other_coord.senec.set_senec_online_instance(coordinator.senec)

        # Register Services
        senec_services = SenecService.SenecService(hass, config_entry, coordinator)
        hass.services.async_register(DOMAIN, SERVICE_SET_PEAKSHAVING, senec_services.set_peakshaving)

    await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)

    config_entry.async_on_unload(config_entry.add_update_listener(entry_update_listener))
    return True


@staticmethod
async def check_device_registry(hass: HomeAssistant, config_entry_id:str = None) -> None:
    global DEVICE_REG_CLEANUP_RUNNING
    if not DEVICE_REG_CLEANUP_RUNNING:
        DEVICE_REG_CLEANUP_RUNNING = True
        _LOGGER.debug(f"check device registry for outdated {DOMAIN} devices...")
        if hass is not None:
            a_device_reg = device_reg.async_get(hass)
            if a_device_reg is not None:
                key_list_to_be_deleted = []
                for a_device_entry in list(a_device_reg.devices.values()):
                    if hasattr(a_device_entry, "identifiers"):
                        ident_value = a_device_entry.identifiers
                        if f"{ident_value}".__contains__(DOMAIN):
                            #if a_device_entry.config_entries is not None and config_entry_id in a_device_entry.config_entries:
                            #_LOGGER.warning(f"{a_device_entry}")
                            # ok this is an old 'device' entry (that does not include the
                            # serial_number)... This will be deleted in
                            # any case...
                            if not hasattr(a_device_entry, "serial_number") or a_device_entry.serial_number is None:
                                key_list_to_be_deleted.append(a_device_entry.id)

                if len(key_list_to_be_deleted) > 0:
                    key_list_to_be_deleted = list(dict.fromkeys(key_list_to_be_deleted))
                    _LOGGER.info(f"NEED TO DELETE old {DOMAIN} DeviceEntries: {key_list_to_be_deleted}")
                    for a_device_entry_id in key_list_to_be_deleted:
                        a_device_reg.async_remove_device(device_id=a_device_entry_id)

        DEVICE_REG_CLEANUP_RUNNING = False

# Map platforms to their corresponding search lists
LOCAL_PLATFORM_MAPPING: Final = {
    "sensor": MAIN_SENSOR_TYPES,
    "binary_sensor": MAIN_BIN_SENSOR_TYPES,
    "switch": MAIN_SWITCH_TYPES,
    "number": MAIN_NUMBER_TYPES,
    "select": MAIN_SELECT_TYPES
}
LOCAL_SECTION_MAPPING: Final = {
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
        UPDATE_INTERVAL_IN_SECONDS = config_entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_SENECV2)
        self._config_entry_id = config_entry.entry_id
        self._integration_version = intg_version
        self._total_increasing_sensors = []

        """Initialize."""
        # Build-In INVERTER
        if CONF_TYPE in config_entry.data and config_entry.data[CONF_TYPE] == CONF_SYSTYPE_INVERTER:
            # host can be changed in the options...
            self._host = config_entry.data[CONF_HOST]
            self.senec = InverterLocal(host=self._host, inv_session=async_create_clientsession(hass), integ_version=self._integration_version)

        # WEB-API Version...
        elif CONF_TYPE in config_entry.data and config_entry.data[CONF_TYPE] == CONF_SYSTYPE_WEB:
            self._host = "mein-senec.de"
            config_entry_serial_number = config_entry.data.get(CONF_DEV_SERIAL, None)
            include_wallbox_in_house_consumption = config_entry.data.get(CONF_INCLUDE_WALLBOX_IN_HOUSE_CONSUMPTION, True)

            # user & pwd can be changed via the options...
            user = config_entry.data[CONF_USERNAME]
            pwd = config_entry.data[CONF_PASSWORD]

            totp = config_entry.data.get(CONF_TOTP_SECRET, None)
            is_totp_already_used = config_entry.data.get(CONF_TOTP_ALREADY_USED, False)

            must_purge_access_token = False
            if totp is not None and not is_totp_already_used:
                # looks like that the TOTP secret is present in the config, but this is the first
                # time that it was detected...
                new_data = {**config_entry.data, CONF_TOTP_ALREADY_USED: True}
                hass.config_entries.async_update_entry(config_entry, data=new_data)
                _LOGGER.info("TOTP secret configured for the first time - we must purge any existing auth-tokens")
                must_purge_access_token = True

            # defining the default query options for APP & WEB...
            opt = {
                # by default, we do not query the Wallbox data for WEB/API -> the SenecLOCAL will turn this on/off
                QUERY_WALLBOX_KEY: False,
                QUERY_SPARE_CAPACITY_KEY: False,
                QUERY_PEAK_SHAVING_KEY: False,
                QUERY_TOTALS_KEY: False,
                QUERY_SYSTEM_DETAILS_KEY: False,
                QUERY_SGREADY_KEY: False,
                CONF_INCLUDE_WALLBOX_IN_HOUSE_CONSUMPTION: include_wallbox_in_house_consumption
            }

            if hass is not None and config_entry.entry_id is not None and config_entry.title is not None:
                # we do not need to listen to changed to the entity - since the integration will be automatically
                # restarted when an Entity of the integration will be disabled/enabled via the GUI (cool!) - but for
                # now I keep this for debugging why during initial setup of the integration the control 'spare_capacity'
                # will not be added [only 13 Entities - after restart there are 14!]
                # event.async_track_entity_registry_updated_event(hass=hass, entity_ids=sce_id, action=self)

                # this is enough to check the current enabled/disabled status of the 'spare_capacity' control
                registry = entity_registry.async_get(hass)

                if registry is not None:
                    all_webapi_entities = entity_registry.async_entries_for_config_entry(registry, config_entry.entry_id)
                    _LOGGER.debug(f"all entities for config_entry {config_entry.entry_id} [{config_entry.title}] fetched - total number is: {len(all_webapi_entities)}")
                    for a_entity in all_webapi_entities:
                        if a_entity.disabled_by is None:
                            a_id = a_entity.entity_id
                            _LOGGER.debug(f"Entity '{a_id}' is enabled for {config_entry.title}")

                            if a_id.startswith("sensor."):
                                if not opt[QUERY_SYSTEM_DETAILS_KEY]:
                                    if a_id.endswith("_system_state") or a_id.endswith("_case_temp"):
                                        _LOGGER.info("***** QUERY_SYSTEM_DETAILS! ********")
                                        opt[QUERY_SYSTEM_DETAILS_KEY] = True

                                # total statistic values [in the web-portal, each total statistic value
                                # would require a separate request]
                                if not opt[QUERY_TOTALS_KEY]:
                                    #if a_id.endswith("_total"):
                                    if any(a_id.endswith(suffix) for suffix in (
                                            "_consumption_total", "_powergenerated_total",
                                            "_accuimport_total", "_accuexport_total",
                                            "_gridimport_total", "gridexport_total",
                                            "_wallbox_consumption_total")):
                                        _LOGGER.info("***** QUERY_TOTALS! ********")
                                        opt[QUERY_TOTALS_KEY] = True

                                # Peak Shaving
                                if not opt[QUERY_PEAK_SHAVING_KEY]:
                                    if any(a_id.endswith(suffix) for suffix in (
                                            "_gridexport_limit", "_peakshaving_mode",
                                            "_peakshaving_capacitylimit", "_peakshaving_enddate")):
                                        _LOGGER.info("***** QUERY_PEAK_SHAVING! ********")
                                        opt[QUERY_PEAK_SHAVING_KEY] = True

                            elif a_id.startswith("number."):
                                # Spare Capacity
                                if not opt[QUERY_SPARE_CAPACITY_KEY]:
                                    if a_id.endswith("_spare_capacity"):
                                        _LOGGER.info("***** QUERY_SPARE_CAPACITY! ********")
                                        opt[QUERY_SPARE_CAPACITY_KEY] = True

                            # brute force for our wallbox stuff
                            if not opt[QUERY_WALLBOX_KEY]:
                                if "_wallbox_" in a_id:
                                    _LOGGER.info("***** QUERY_WALLBOX-DATA ********")
                                    opt[QUERY_WALLBOX_KEY] = True

                            # brute force for our sgready stuff
                            if not opt[QUERY_SGREADY_KEY]:
                                if "sgready" in a_id:
                                    _LOGGER.info("***** QUERY_SGREADY_DATA! ********")
                                    opt[QUERY_SGREADY_KEY] = True

                            # when we have ALL, we can break the loop
                            if (opt[QUERY_PEAK_SHAVING_KEY] and
                                opt[QUERY_SPARE_CAPACITY_KEY] and
                                opt[QUERY_TOTALS_KEY] and
                                opt[QUERY_SYSTEM_DETAILS_KEY] and
                                opt[QUERY_WALLBOX_KEY] and
                                opt[QUERY_SGREADY_KEY]
                            ):
                                _LOGGER.debug(f"All required options are set: {opt} - can cancel the checking loop")
                                break

                    # we need to check, if there are any Wallbox entities...
                    # opt[QUERY_WALLBOX_KEY] = True

            # we will not set the master_plant number any longer - we will always use "autodetect" option, since the
            # SenecApp use a master_plant_id while the MeinSenec.de web is using a master_plant_number (and to make
            # things worse, the App just can have one master_plant, while the web can have multiple...
            # once more: "Thanks for Nothing!")
            # SO to get out of this mess, we will store the serial_number in our config entry and use this as our
            # general key - then when we access the web-portal, we will use assigned serial_number to the master_plant_id
            # and then query the web-portal anlagenNummer 0,1,2 ... till we find the one with the matching serial_number
            try:
                self.senec = SenecOnline(user=user, pwd=pwd, totp=totp, web_session=async_create_clientsession(hass),
                                         config_entry_serial_number=config_entry_serial_number,
                                         lang=hass.config.language.lower(),
                                         options=opt,
                                         storage_path=Path(hass.config.config_dir).joinpath(STORAGE_DIR),
                                         integ_version=self._integration_version)
            except ReConfigurationRequired as exc:
                _LOGGER.warning(f"SenecOnline could not be created: {type(exc).__name__} - {exc}")
                hass.add_job(config_entry.async_start_reauth, hass)

            if must_purge_access_token:
                _LOGGER.info("init(): must_purge_access_token...")
                hass.async_create_task(self.senec._write_token_to_storage(token_dict=None))

            self._warning_counter = 0
            UPDATE_INTERVAL_IN_SECONDS = max(20, UPDATE_INTERVAL_IN_SECONDS)

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
            use_defaults = True
            if hass is not None and config_entry.entry_id is not None and config_entry.title is not None:
                registry = entity_registry.async_get(hass)
                if registry is not None:
                    all_local_entities = entity_registry.async_entries_for_config_entry(registry, config_entry.entry_id)
                    if len(all_local_entities) > 0:
                        use_defaults = False
                        _LOGGER.debug(f"all entities for config_entry {config_entry.entry_id} [{config_entry.title}] fetched - total number is: {len(all_local_entities)}")
                        for a_entity in all_local_entities:
                            if a_entity.disabled_by is None:
                                a_id = a_entity.entity_id
                                _LOGGER.debug(f"Entity '{a_id}' is enabled for {config_entry.title}")
                                # check if the entity is a sensor, binary_sensor, switch, number or select
                                a_entity_platform = a_id.split(".")[0]
                                if a_entity_platform in LOCAL_PLATFORM_MAPPING:
                                    for a_entity_desc in LOCAL_PLATFORM_MAPPING[a_entity_platform]:
                                        if a_id.endswith(a_entity_desc.key):
                                            if hasattr(a_entity_desc, "senec_lala_section"):
                                                a_lala_section  = a_entity_desc.senec_lala_section
                                                if a_lala_section in LOCAL_SECTION_MAPPING:
                                                    query_option_key, a_log_msg = LOCAL_SECTION_MAPPING[a_lala_section]
                                                    if not opt[query_option_key]:
                                                        opt[query_option_key] = True
                                                        _LOGGER.info(a_log_msg)

                                            _LOGGER.debug(f"Found a EntityDescription for '{a_id}' key: {a_entity_desc.key}")
                                            break

            if use_defaults:
                # if there are no entities yet... we slightly adjust our defaults!
                _LOGGER.info(f"NO entities for config_entry fetched! Using default options")
                opt[QUERY_PV1_KEY] = True
                opt[QUERY_PM1OBJ1_KEY] = True
                opt[QUERY_BMS_KEY] = True

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
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=timedelta(seconds=UPDATE_INTERVAL_IN_SECONDS))

    # Callable[[Event], Any]
    def __call__(self, evt: Event) -> bool:
        # just as testing the 'event.async_track_entity_registry_updated_event'
        _LOGGER.warning(str(evt))
        return True

    async def check_for_post_migration_tasks(self, hass: HomeAssistant):
        _LOGGER.debug(f"check_for_post_migration_tasks() called")
        if CONF_MUST_START_POST_MIGRATION_PROCESS in self._config_entry.data:
            data_reload_required = False
            _LOGGER.info(f"check_for_post_migration_tasks(): 'CONF_MUST_START_POST_MIGRATION_PROCESS' is present WE will perform the actual task in 45sec")
            await asyncio.sleep(45)
            _LOGGER.info(f"check_for_post_migration_tasks(): starting 'post_migration_process' now!")
            if self._config_entry.data[CONF_MUST_START_POST_MIGRATION_PROCESS] is True:
                if self._config_entry.data.get(CONF_TYPE, None) == CONF_SYSTYPE_WEB:
                    _LOGGER.info("check_for_post_migration_tasks(): we must: 1) reset the access_token 2) reset all our 'total_increasing_values' sensors")
                    await self._async_trigger_button(trigger_key="delete_cache", payload="true")
                    self.reset_total_increasing_values()
                    data_reload_required = True

            # when the 'CONF_MUST_START_POST_MIGRATION_PROCESS' value is in the config_entry.data, then we must
            # remove it...
            new_data = {**self._config_entry.data}
            new_data.pop(CONF_MUST_START_POST_MIGRATION_PROCESS)
            global SKIP_NEXT_RELOAD_OF_WEB
            SKIP_NEXT_RELOAD_OF_WEB = True
            hass.config_entries.async_update_entry(self._config_entry, data=new_data)

            if data_reload_required:
                await asyncio.sleep(5)
                await self.async_refresh()


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
            _LOGGER.warning(f"Exception (fatal): {type(fatal).__name__} {fatal}")
            raise UpdateFailed() from fatal

    async def _async_switch_to_state(self, switch_key, state):
        try:
            await self.senec.switch(switch_key, state)
            return self.senec.dict_data()
        except UpdateFailed as exception:
            _LOGGER.warning(f"UpdateFailed: {exception}")
            raise UpdateFailed() from exception
        except BaseException as fatal:
            _LOGGER.warning(f"Exception (fatal): {type(fatal).__name__} {fatal}")
            raise UpdateFailed() from fatal

    async def _async_switch_array_to_state(self, switch_array_key, array_pos, state):
        try:
            await self.senec.switch_array(switch_array_key, array_pos, state)
            return self.senec.dict_data()
        except UpdateFailed as exception:
            _LOGGER.warning(f"UpdateFailed: {exception}")
            raise UpdateFailed() from exception
        except BaseException as fatal:
            _LOGGER.warning(f"Exception (fatal): {type(fatal).__name__} {fatal}")
            raise UpdateFailed() from fatal

    async def _async_set_string_value(self, set_str_key, value: str):
        try:
            await self.senec.set_string_value(set_str_key, value)
            return self.senec.dict_data()
        except UpdateFailed as exception:
            _LOGGER.warning(f"UpdateFailed: {exception}")
            raise UpdateFailed() from exception
        except BaseException as fatal:
            _LOGGER.warning(f"Exception (fatal): {type(fatal).__name__} {fatal}")
            raise UpdateFailed() from fatal

    async def _async_trigger_button(self, trigger_key:str, payload: str):
        try:
            await self.senec._trigger_button(trigger_key, payload)
            return self.senec.dict_data()
        except UpdateFailed as exception:
            _LOGGER.warning(f"UpdateFailed: {exception}")
            raise UpdateFailed() from exception
        except BaseException as fatal:
            _LOGGER.warning(f"Exception (fatal): {type(fatal).__name__} {fatal}")
            raise UpdateFailed() from fatal

    def add_total_increasing_sensor(self, sensor):
        self._total_increasing_sensors.append(sensor)
        _LOGGER.debug(f"Added total increasing sensor: {sensor.entity_description.key} to coordinator")

    def reset_total_increasing_values(self):
        for sensor in self._total_increasing_sensors:
            if hasattr(sensor, "_previous_float_value") and sensor._previous_float_value is not None:
                _LOGGER.debug(f"Resetting total increasing value for sensor: {sensor.entity_description.key}")
                sensor._previous_float_value = None
            else:
                _LOGGER.debug(f"No previous float value to reset for sensor: {sensor.entity_description.key}")


async def async_unload_entry(hass: HomeAssistant, config_entry: ConfigEntry):
    """Unload Senec config entry."""
    _LOGGER.debug(f"async_unload_entry() called for entry: {config_entry.entry_id}")
    unload_ok = await hass.config_entries.async_unload_platforms(config_entry, PLATFORMS)

    if unload_ok:
        if DOMAIN in hass.data and config_entry.entry_id in hass.data[DOMAIN]:
            try:
                the_unload_coordinator = hass.data[DOMAIN][config_entry.entry_id]

                # we must find all other (still present) coordinator's where this
                # SenecLocal (or SenecOnline) is referred as 'self._bridge_to_senec_...'
                is_local = isinstance(the_unload_coordinator.senec, SenecLocal)
                is_online  = isinstance(the_unload_coordinator.senec, SenecOnline)
                if is_local or is_online:
                    for a_other_coord in hass.data[DOMAIN].values():
                        if isinstance(a_other_coord, SenecDataUpdateCoordinator):
                            if is_local and isinstance(a_other_coord.senec, SenecOnline):
                                if the_unload_coordinator._device_serial == a_other_coord._device_serial:
                                    a_other_coord.senec.set_senec_local_instance(None)

                            elif is_online and isinstance(a_other_coord.senec, SenecLocal):
                                if the_unload_coordinator._device_serial == a_other_coord._device_serial:
                                    a_other_coord.senec.set_senec_online_instance(None)

            except BaseException as exception:
                _LOGGER.warning(f"async_unload_entry() Exception (fatal): {exception}")

            hass.data[DOMAIN].pop(config_entry.entry_id)

        if CONF_TYPE in config_entry.data and config_entry.data[CONF_TYPE] == CONF_SYSTYPE_WEB:
            hass.services.async_remove(DOMAIN, SERVICE_SET_PEAKSHAVING)  # Remove Service on unload

    return unload_ok


async def entry_update_listener(hass: HomeAssistant, config_entry: ConfigEntry) -> None:
    global SKIP_NEXT_RELOAD_OF_WEB
    _LOGGER.debug(f"entry_update_listener() called for entry: {config_entry.entry_id}")
    if config_entry.data.get(CONF_TYPE, None) != CONF_SYSTYPE_WEB or SKIP_NEXT_RELOAD_OF_WEB is False:
        await hass.config_entries.async_reload(config_entry.entry_id)
    else:
        _LOGGER.info(f"entry_update_listener() was called but the RELOAD will be skipped cause the updated was caused by an integrtaion-internal process - all is fine!")
        SKIP_NEXT_RELOAD_OF_WEB = False

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

        a_wallbox_obj = None
        if self.entity_description is not None and self.entity_description.key.lower().startswith("wallbox"):
            possible_idx_str = self.entity_description.key.lower().split('_')[1]
            try:
                idx = int(possible_idx_str) - 1
                a_wallbox_obj = StaticFuncs.app_get_wallbox_obj(self.coordinator.data, idx)
            except ValueError:
                _LOGGER.debug(f"No valid wallbox index found in key: {self.entity_description.key} - {possible_idx_str}")

        if a_wallbox_obj is not None:
            #         "id": "1",
            #         "productFamily": None,
            #         "controllerId": "Sxxxxxxxxxxxxxxxxxxxxxxxxxx",
            #         "name": "Wallbox 1",
            #         "prohibitUsage": False,
            #         "isInterchargeAvailable": True,
            #         "isSolarChargingAvailable": True,
            #         "type": "V123",
            return {
                "identifiers": {(DOMAIN, self.coordinator._host, device, a_wallbox_obj.get("id"))},
                "name": f"{a_wallbox_obj.get("name")} @ {dtype}: {device}",
                "model": f"{a_wallbox_obj.get("name")} @ {dmodel}",
                "sw_version": dversion,
                "manufacturer": MANUFACTURE,
                "serial_number": {a_wallbox_obj.get("controllerId")}
            }
        else:
            # "hw_version": self.coordinator._config_entry.data.get(CONF_DEV_NAME, "UNKNOWN_HW_VERSION"),
            return {
                "identifiers": {(DOMAIN, self.coordinator._host, device)},
                "name": f"{dtype}: {device}",
                "model": f"{dmodel}",
                "sw_version": dversion,
                "manufacturer": MANUFACTURE,
                "serial_number": dserial
            }

    @property
    def available(self):
        """Return True if entity is available."""
        return self.coordinator.last_update_success

    @property
    def unique_id(self):
        """Return a unique ID to use for this entity."""
        return f"{self._name}_{self.entity_description.key}".lower()

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
