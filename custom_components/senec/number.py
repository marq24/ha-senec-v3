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
    WEB_NUMBER_SENYOR_TYPES,
    CONF_SYSTYPE_WEB
)

_LOGGER = logging.getLogger(__name__)
_LANG = None


async def async_setup_entry(hass: HomeAssistantType, config_entry: ConfigEntry, async_add_entities):
    """Initialize sensor platform from config entry."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]
    global _LANG
    _LANG = coordinator._langDict

    entities = []
    # Take care that CONF_TYPE = CONF_SYSTEYPE_WEB, since the implementation works with the web API
    if CONF_TYPE in config_entry.data and config_entry.data[CONF_TYPE] == CONF_SYSTYPE_WEB:
        for description in WEB_NUMBER_SENYOR_TYPES:
            entity = SenecNumber(coordinator, description)
            entities.append(entity)
    async_add_entities(entities)


"""Implementation for the spare capacity of the senec device"""
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
        if key in _LANG:
            self._attr_name = _LANG[key]
        else:
            _LOGGER.info(str(key)+" Number not found in translation")
            self._attr_name = f"{title} {name}"

    @property
    def state(self) -> int:
        number = self.entity_description.key
        value = getattr(self.coordinator.senec, number)
        return int(value)

    async def async_set_native_value(self, value: int) -> None:
        """Update the current value."""
        updated_spare_capacity = int(value)
        api = self.coordinator.senec
        await api.set_spare_capacity(updated_spare_capacity)
        self.async_schedule_update_ha_state(force_refresh=True)
