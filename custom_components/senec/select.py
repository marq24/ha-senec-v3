"""Platform for Senec Selects."""
import asyncio
import logging

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_TYPE
from homeassistant.core import HomeAssistant
from homeassistant.core import State
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import slugify
from . import SenecDataUpdateCoordinator, SenecEntity
from .const import DOMAIN, MAIN_SELECT_TYPES, CONF_SYSTYPE_INVERTER, CONF_SYSTYPE_WEB, ExtSelectEntityDescription
from .pysenec_ha import LOCAL_WB_MODE_UNKNOWN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry,
                            async_add_entities: AddEntitiesCallback):
    """Initialize sensor platform from config entry."""
    _LOGGER.debug("SELECT async_setup_entry")
    coordinator = hass.data[DOMAIN][config_entry.entry_id]
    entities = []
    if CONF_TYPE in config_entry.data and config_entry.data[CONF_TYPE] == CONF_SYSTYPE_INVERTER:
        _LOGGER.info("No selects for Inverters...")
    elif CONF_TYPE in config_entry.data and config_entry.data[CONF_TYPE] == CONF_SYSTYPE_WEB:
        _LOGGER.info("No selects for WebPortal...")
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
        self.entity_id = f"select.{slugify(title)}_{key}"

        # we use the "key" also as our internal translation-key - and EXTREMELY important we have
        # to set the '_attr_has_entity_name' to trigger the calls to the localization framework!
        self._attr_translation_key = key
        self._attr_has_entity_name = True

        self._previous_value: str | None = None
        self._is_local_persistence: bool = description is not None and isinstance(description,
                                                                                  ExtSelectEntityDescription) and hasattr(
            description,
            "controls") and description.controls is not None and "local_persistence" in description.controls

    @property
    def current_option(self) -> str | None:
        try:
            if self.entity_description.array_key is not None:
                value = getattr(self.coordinator.senec, self.entity_description.array_key)[
                    self.entity_description.array_pos]
            else:
                value = getattr(self.coordinator.senec, self.entity_description.key)

            if (value is None or str(value) == LOCAL_WB_MODE_UNKNOWN) and self._previous_value is not None:
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
            if hasattr(self.entity_description,
                       'update_after_switch_delay_in_sec') and self.entity_description.update_after_switch_delay_in_sec > 0:
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
            if last_sensor_data is not None and isinstance(last_sensor_data,
                                                           State) and last_sensor_data.state is not None:
                if str(last_sensor_data.state).lower() != "unknown":
                    _LOGGER.debug(f"restored prev value for key {self._attr_translation_key}: {last_sensor_data.state}")
                    self._previous_value = str(last_sensor_data.state)
                else:
                    _LOGGER.debug(
                        f"SKIPP restored prev value for key {self._attr_translation_key} cause value is :'{last_sensor_data.state}'")
