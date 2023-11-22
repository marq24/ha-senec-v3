"""Platform for Senec sensors."""
import logging

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.typing import HomeAssistantType
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import slugify
from homeassistant.const import CONF_TYPE

from . import SenecDataUpdateCoordinator, SenecEntity
from .const import (
    DOMAIN,
    MAIN_SENSOR_TYPES,
    INVERTER_SENSOR_TYPES,
    WEB_SENSOR_TYPES,
    CONF_SUPPORT_BDC,
    CONF_SYSTYPE_INVERTER,
    CONF_SYSTYPE_WEB
)

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistantType, config_entry: ConfigEntry, async_add_entities):
    """Initialize sensor platform from config entry."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]
    entities = []
    if CONF_TYPE in config_entry.data and config_entry.data[CONF_TYPE] == CONF_SYSTYPE_INVERTER:
        for description in INVERTER_SENSOR_TYPES:
            addEntity = description.controls is None
            if not addEntity:
                if 'bdc_only' in description.controls:
                    if (config_entry.data[CONF_SUPPORT_BDC]):
                        addEntity = True
                else:
                    addEntity = True

            if addEntity:
                entity = SenecSensor(coordinator, description)
                entities.append(entity)

    elif CONF_TYPE in config_entry.data and config_entry.data[CONF_TYPE] == CONF_SYSTYPE_WEB:
        for description in WEB_SENSOR_TYPES:
            entity = SenecSensor(coordinator, description)
            entities.append(entity)

    else:
        for description in MAIN_SENSOR_TYPES:
            addEntity = description.controls is None
            if not addEntity:
                if 'require_stats_fields' in description.controls:
                    if coordinator._statistics_available:
                        addEntity = True
                else:
                    addEntity = True

            if addEntity:
                entity = SenecSensor(coordinator, description)
                entities.append(entity)

    async_add_entities(entities)

class SenecSensor(SenecEntity, SensorEntity, RestoreEntity):
    """Sensor for the single values (e.g. pv power, ac power)."""

    def __init__(
            self,
            coordinator: SenecDataUpdateCoordinator,
            description: SensorEntityDescription
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
        self.entity_id = f"sensor.{slugify(title)}_{key}"

        # we use the "key" also as our internal translation-key - and EXTREMELY important we have
        # to set the '_attr_has_entity_name' to trigger the calls to the localization framework!
        self._attr_translation_key = key
        self._attr_has_entity_name = True
        self._state: float | None = None

    @property
    def state(self):
        """Return the current state."""
        sensor = self.entity_description.key
        value = getattr(self.coordinator.senec, sensor)
        #_LOGGER.debug( str(sensor)+' '+ str(type(value)) +' '+str(value))
        if isinstance(value, bool):
            return value
        try:
            value = round(float(value), 2)
        except (ValueError, TypeError):
            return value
            
        # do not update if value is lower than current state
        # this is only an issue for _total sensors
        # since the API may return false values in this case
        needs_attention = "_total" in str(sensor)
        if not needs_attention:
            return value
        if ((self._state is not None) and (value < self._state)):
            return self._state
        self._state = value
        return self._state

    async def async_added_to_hass(self) -> None:
        """Call when entity about to be added to Home Assistant."""
        await super().async_added_to_hass()
        # get the last known state
        state = await self.async_get_last_state()
        # most of the values, are float,
        # we could also check here for only _total entities
        if state is not None and isinstance(state, float):
            self._state = float(state.state)
