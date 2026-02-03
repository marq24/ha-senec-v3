"""Platform for Senec Selects."""
import asyncio
import logging
from dataclasses import replace

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_TYPE
from homeassistant.core import HomeAssistant
from homeassistant.core import State
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import slugify
from . import SenecDataUpdateCoordinator, SenecEntity
from .const import DOMAIN, MAIN_SELECT_TYPES, WEB_SELECT_TYPES, CONF_SYSTYPE_INVERTER, CONF_SYSTYPE_WEB, \
    ExtSelectEntityDescription, StaticFuncs
from .pysenec_ha import LOCAL_WB_MODE_LEGACY_UNKNOWN, LOCAL_WB_MODE_2026_UNKNOWN
from .pysenec_ha.constants import WALLBOX_CHARGING_MODES_LEGACY_P4, WALLBOX_CHARGING_MODES_2026_P4

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry,
                            async_add_entities: AddEntitiesCallback):
    """Initialize select platform from config entry."""
    _LOGGER.info("SELECT async_setup_entry")
    coordinator = hass.data[DOMAIN][config_entry.entry_id]
    entities = []
    if CONF_TYPE in config_entry.data and config_entry.data[CONF_TYPE] == CONF_SYSTYPE_INVERTER:
        _LOGGER.info("No selects for Inverters...")
    elif CONF_TYPE in config_entry.data and config_entry.data[CONF_TYPE] == CONF_SYSTYPE_WEB:
        for description in WEB_SELECT_TYPES:
            # when we have wallbox data, we want to enable the entity by default...
            if description.key.startswith("wallbox"):
                possible_idx_str = description.key.lower().split('_')[1]
                try:
                    idx = int(possible_idx_str) - 1
                    a_wallbox_obj = StaticFuncs.app_get_wallbox_obj(coordinator.data, idx)
                    if a_wallbox_obj is not None:
                        description = replace(description, entity_registry_enabled_default=True)
                except ValueError:
                    _LOGGER.debug(f"No valid wallbox index found in key: {description.key} - {possible_idx_str}")

            # we need to check, if for the wallbox modes, we have a V4 or a V2/V3 system - since
            # the V4 have more options!
            if description.key in ["wallbox_1_mode", "wallbox_1_mode_legacy", "wallbox_2_mode", "wallbox_2_mode_legacy",
                                   "wallbox_3_mode", "wallbox_3_mode_legacy", "wallbox_4_mode", "wallbox_4_mode_legacy"]:
                try:
                    is_legacy = description.key.endswith("_mode_legacy")
                    if is_legacy:
                        a_state_key = description.key.replace("_mode_legacy", "_state")
                    else:
                        a_state_key = description.key.replace("_mode", "_state")

                    attr_func_name = f"{a_state_key}_attr"
                    if hasattr(coordinator.senec, attr_func_name):
                        a_dict = getattr(coordinator.senec, attr_func_name)
                        if a_dict is not None:
                            the_wallbox_type = a_dict.get("json", {}).get("type", None)
                            if the_wallbox_type is not None and the_wallbox_type.upper() in ["V4", "P4"]:
                                description = replace(
                                    description,
                                    options = list(WALLBOX_CHARGING_MODES_LEGACY_P4.values()) if is_legacy else list(WALLBOX_CHARGING_MODES_2026_P4.values())
                                )
                except Exception as err:
                    _LOGGER.error(f"WEB: Could not fetch wallbox-type for '{description.key}' - cause: {err}")

            entity = SenecSelect(coordinator, description)
            entities.append(entity)
    else:
        for description in MAIN_SELECT_TYPES:
            entity = SenecSelect(coordinator, description)
            entities.append(entity)
    async_add_entities(entities)


class SenecSelect(SenecEntity, SelectEntity, RestoreEntity):
    def __init__(
            self,
            coordinator: SenecDataUpdateCoordinator,
            description: ExtSelectEntityDescription
    ):
        """Initialize a singular value sensor."""
        super().__init__(coordinator=coordinator, description=description)
        if (hasattr(self.entity_description, 'entity_registry_enabled_default')):
            self._attr_entity_registry_enabled_default = self.entity_description.entity_registry_enabled_default
        else:
            self._attr_entity_registry_enabled_default = True

        title = self.coordinator._config_entry.title
        key = self.entity_description.key.lower()
        name = self.entity_description.name
        self.entity_id = f"select.{slugify(title)}_{key}".lower()

        # we use the "key" also as our internal translation-key - and EXTREMELY important we have
        # to set the '_attr_has_entity_name' to trigger the calls to the localization framework!
        self._attr_translation_key = key
        self._attr_has_entity_name = True

        self._previous_value: str | None = None

        has_control: bool = (description is not None and isinstance(description, ExtSelectEntityDescription) and
                             hasattr(description, "controls") and description.controls is not None)

        self._is_local_persistence: bool = has_control and "local_persistence" in description.controls
        self._restore_from_local_persistence: bool = has_control and "restore_from_local_persistence" in description.controls

    @property
    def current_option(self) -> str | None:
        try:
            if self.entity_description.array_key is not None:
                value = getattr(self.coordinator.senec, self.entity_description.array_key)[self.entity_description.array_pos]
            else:
                value = getattr(self.coordinator.senec, self.entity_description.key)

            # if value is not set or the unknown-wallbox value, then check, if we
            # have a previous value... and then use it - or reset it to None
            if value is None or str(value) == LOCAL_WB_MODE_LEGACY_UNKNOWN or str(value) == LOCAL_WB_MODE_2026_UNKNOWN:
                if self._previous_value is not None:
                    value = self._previous_value
                else:
                    value = None

            if value is None or value == "":
                value = 'unknown'

        except KeyError:
            value = "unknown"
        except TypeError:
            return None
        return value

    async def async_select_option(self, option: str) -> None:  # pylint: disable=unused-argument
        try:
            if self.entity_description.array_key is not None:
                # not implemented yet...
                await self.coordinator._async_set_array_string_value(self.entity_description.array_key,
                                                                     self.entity_description.array_pos,
                                                                     option)
            else:
                await self.coordinator._async_set_string_value(self.entity_description.key, option)

            self.async_schedule_update_ha_state(force_refresh=True)
            if hasattr(self.entity_description, 'update_after_switch_delay_in_sec') and self.entity_description.update_after_switch_delay_in_sec > 0:
                await asyncio.sleep(self.entity_description.update_after_switch_delay_in_sec)
                self.async_schedule_update_ha_state(force_refresh=True)

            self._previous_value = option;

        except ValueError:
            return "unavailable"

    async def async_added_to_hass(self) -> None:
        """Call when entity about to be added to Home Assistant."""
        await super().async_added_to_hass()

        if self._is_local_persistence:
            # get the last known value
            last_sensor_data = await self.async_get_last_state()
            if last_sensor_data is not None and isinstance(last_sensor_data, State) and last_sensor_data.state is not None:
                if str(last_sensor_data.state).lower() != "unknown":
                    _LOGGER.debug(f"restored prev value for key {self._attr_translation_key}: {last_sensor_data.state}")
                    self._previous_value = str(last_sensor_data.state)
                    if self._restore_from_local_persistence:
                        _LOGGER.debug(f"set restored value '{self._previous_value}' as current value")
                        await self.async_select_option(self._previous_value)
                else:
                    _LOGGER.debug(f"SKIPP restored prev value for key {self._attr_translation_key} cause value is :'{last_sensor_data.state}'")
