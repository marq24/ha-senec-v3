"""Platform for Senec numbers."""
import logging

from homeassistant.components.number import NumberEntity, NumberEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.typing import HomeAssistantType
from homeassistant.util import slugify
from homeassistant.const import CONF_TYPE

from . import SenecDataUpdateCoordinator, SenecEntity
from .const import (
    DOMAIN,
    MAIN_NUMBER_SENSOR_TYPES,
    WEB_NUMBER_SENSOR_TYPES,
    CONF_SYSTYPE_WEB,
    CONF_SYSTYPE_INVERTER
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistantType, config_entry: ConfigEntry, async_add_entities):
    """Initialize sensor platform from config entry."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]
    entities = []

    if CONF_TYPE in config_entry.data and config_entry.data[CONF_TYPE] == CONF_SYSTYPE_INVERTER:
        _LOGGER.info("No numbers for Inverters...")
    elif CONF_TYPE in config_entry.data and config_entry.data[CONF_TYPE] == CONF_SYSTYPE_WEB:
        for description in WEB_NUMBER_SENSOR_TYPES:
            entity = SenecNumber(coordinator, description)
            entities.append(entity)
    else:
        for description in MAIN_NUMBER_SENSOR_TYPES:
            entity = SenecNumber(coordinator, description)
            entities.append(entity)

    async_add_entities(entities)


class SenecNumber(SenecEntity, NumberEntity):

    def __init__(
            self,
            coordinator: SenecDataUpdateCoordinator,
            description: NumberEntityDescription,
    ):
        """Initialize"""
        super().__init__(coordinator=coordinator, description=description)
        if (hasattr(self.entity_description, 'entity_registry_enabled_default')):
            self._attr_entity_registry_enabled_default = self.entity_description.entity_registry_enabled_default
        else:
            self._attr_entity_registry_enabled_default = True
        title = self.coordinator._config_entry.title
        key = self.entity_description.key.lower()
        name = self.entity_description.name
        self.entity_id = f"number.{slugify(title)}_{key}"

        # we use the "key" also as our internal translation-key - and EXTREMELY important we have
        # to set the '_attr_has_entity_name' to trigger the calls to the localization framework!
        self._attr_translation_key = key
        self._attr_has_entity_name = True

    @property
    def state(self) -> int:
        if self.entity_description.array_key is not None:
            value = getattr(self.coordinator.senec, self.entity_description.array_key)[self.entity_description.array_pos]
        else:
            value = getattr(self.coordinator.senec, self.entity_description.key)

        return int(value)

    async def async_set_native_value(self, value: int) -> None:
        """Update the current value."""
        api = self.coordinator.senec
        # this is quite an ugly hack - but it's xmas!
        if self.entity_description.key == 'spare_capacity':
            await api.set_spare_capacity(int(value))
        else:
            if self.entity_description.array_key is not None:
                await api.set_number_value_array(self.entity_description.array_key, self.entity_description.array_pos, int(value))
            else:
                await api.set_number_value(self.entity_description.key, int(value))
        self.async_schedule_update_ha_state(force_refresh=True)
