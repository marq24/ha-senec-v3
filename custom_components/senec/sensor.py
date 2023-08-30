"""Platform for Senec sensors."""
import logging

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.typing import HomeAssistantType
from homeassistant.util import slugify
from homeassistant.const import CONF_TYPE

from . import SenecDataUpdateCoordinator, SenecEntity
from .const import DOMAIN, MAIN_SENSOR_TYPES, INVERTER_SENSOR_TYPES, CONF_SUPPORT_BDC, CONF_SYSTYPE_INVERTER

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
    else:
        for description in MAIN_SENSOR_TYPES:
            entity = SenecSensor(coordinator, description)
            entities.append(entity)

    async_add_entities(entities)


class SenecSensor(SenecEntity, SensorEntity):
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

        title = self.coordinator._entry.title
        key = self.entity_description.key
        name = self.entity_description.name
        self.entity_id = f"sensor.{slugify(title)}_{key}"
        self._attr_name = f"{title} {name}"

    @property
    def state(self):
        """Return the current state."""
        sensor = self.entity_description.key
        value = getattr(self.coordinator.senec, sensor)
        if type(value) != type(False):
            try:
                rounded_value = round(float(value), 2)
                return rounded_value
            except (ValueError, TypeError):
                return value
        else:
            return value
