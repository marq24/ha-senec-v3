"""Platform for Senec numbers."""
import logging

from homeassistant.components.number import NumberEntity, NumberEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_TYPE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import slugify
from . import SenecDataUpdateCoordinator, SenecEntity
from .const import (
    DOMAIN,
    MAIN_NUMBER_TYPES,
    WEB_NUMBER_SENSOR_TYPES,
    CONF_SYSTYPE_WEB,
    CONF_SYSTYPE_INVERTER
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry,
                            async_add_entities: AddEntitiesCallback):
    """Initialize sensor platform from config entry."""
    _LOGGER.debug("NUMBER async_setup_entry")
    coordinator = hass.data[DOMAIN][config_entry.entry_id]
    entities = []

    if CONF_TYPE in config_entry.data and config_entry.data[CONF_TYPE] == CONF_SYSTYPE_INVERTER:
        _LOGGER.info("No numbers for Inverters...")
    elif CONF_TYPE in config_entry.data and config_entry.data[CONF_TYPE] == CONF_SYSTYPE_WEB:
        for description in WEB_NUMBER_SENSOR_TYPES:
            entity = SenecNumber(coordinator, description)
            entities.append(entity)
    else:
        for description in MAIN_NUMBER_TYPES:
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

        self._internal_minmax_adjustment_needed = False
        if key.endswith("set_icmax"):
            self._internal_minmax_adjustment_needed = True
            self._internal_check_minmax_adjustment()

    def _internal_check_minmax_adjustment(self):
        # a_pos = int(key[8:9])-1
        try:
            min_max = getattr(self.coordinator.senec, self.entity_description.key + "_extrema")
            if min_max is not None:
                self._internal_minmax_adjustment_needed = False
                self.entity_description.native_min_value = round(float(min_max[0]), 1)
                self.entity_description.native_max_value = round(float(min_max[1]), 1)
        except Exception as err:
            _LOGGER.error(f"Could not fetch min/max values for '{self.entity_description.key}' - cause: {err}")

    @property
    def native_value(self) -> float:
        if self.entity_description.array_key is not None:
            data = getattr(self.coordinator.senec, self.entity_description.array_key)
            if data is not None and len(data) > self.entity_description.array_pos:
                value = data[self.entity_description.array_pos]
            else:
                value = 0
        else:
            value = getattr(self.coordinator.senec, self.entity_description.key)

        if self._internal_minmax_adjustment_needed:
            self._internal_check_minmax_adjustment()

        if value is not None:
            return float(value)

    async def async_set_native_value(self, value: float) -> None:
        """Update the current value."""
        api = self.coordinator.senec
        # this is quite an ugly hack - but it's xmas!
        if self.entity_description.key == 'spare_capacity':
            await api.set_spare_capacity(int(value))
        else:
            if self.entity_description.array_key is not None:
                await api.set_number_value_array(self.entity_description.array_key, self.entity_description.array_pos,
                                                 float(value))
            else:
                await api.set_number_value(self.entity_description.key, float(value))
        self.async_schedule_update_ha_state(force_refresh=True)
