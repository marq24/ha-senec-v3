"""Platform for Senec sensors."""
import logging

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.typing import HomeAssistantType
from homeassistant.util import slugify

from . import SenecDataUpdateCoordinator, SenecEntity
from .const import DOMAIN, MAIN_SENSOR_TYPES, INVERTER_SENSOR_TYPES, CONF_SUPPORT_BDC
from homeassistant.const import CONF_TYPE

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistantType, config_entry: ConfigEntry, async_add_entities):
    """Initialize sensor platform from config entry."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]
    entities = []
    if (CONF_TYPE in config_entry.data and config_entry.data[CONF_TYPE] == 'inverter'):
        for description in INVERTER_SENSOR_TYPES:
            addEntity = description.options is None
            if(not addEntity):
                if('bdc_only' in description.options):
                    if(config_entry.data[CONF_SUPPORT_BDC]):
                        addEntity = True
                else:
                    addEntity = True

            if (addEntity):
                enabledByDefault  = description.options is None or 'disabled_by_default' not in description.options
                entity = SenecSensor(coordinator, description, enabledByDefault)
                entities.append(entity)
    else:
        for description in MAIN_SENSOR_TYPES:
            enabledByDefault  = description.options is None or 'disabled_by_default' not in description.options
            entity = SenecSensor(coordinator, description, enabledByDefault)
            entities.append(entity)

    async_add_entities(entities)


class SenecSensor(SenecEntity, SensorEntity):
    """Sensor for the single values (e.g. pv power, ac power)."""

    def __init__(
            self,
            coordinator: SenecDataUpdateCoordinator,
            description: SensorEntityDescription,
            enabled: bool,
    ):
        """Initialize a singular value sensor."""
        super().__init__(coordinator=coordinator, description=description)

        title = self.coordinator._entry.title
        key = self.entity_description.key
        name = self.entity_description.name
        self.entity_id = f"sensor.{slugify(title)}_{key}"
        self._attr_name = f"{title} {name}"
        self._coordinator = coordinator
        self._enabled_by_default = enabled

    @property
    def entity_registry_enabled_default(self):
        """Return the entity_registry_enabled_default of the sensor."""
        return self._enabled_by_default

    async def async_update(self):
        """Schedule a custom update via the common entity update service."""
        await self._coordinator.async_request_refresh()

    @property
    def should_poll(self) -> bool:
        """Entities do not individually poll."""
        return False
