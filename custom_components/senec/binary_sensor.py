"""Binary sensor platform for Waterkotte Heatpump."""
import logging

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.typing import HomeAssistantType
from homeassistant.util import slugify
from homeassistant.const import STATE_ON, STATE_OFF, CONF_TYPE

from typing import Literal
from . import SenecDataUpdateCoordinator, SenecEntity
from .const import DOMAIN, MAIN_BIN_SENSOR_TYPES, CONF_SYSTYPE_INVERTER, CONF_SYSTYPE_WEB, ExtBinarySensorEntityDescription

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistantType, config_entry: ConfigEntry, async_add_entities):
    coordinator = hass.data[DOMAIN][config_entry.entry_id]
    if (CONF_TYPE in config_entry.data and config_entry.data[CONF_TYPE] == CONF_SYSTYPE_INVERTER):
        _LOGGER.info("No binary_sensors for Inverters...")
    if (CONF_TYPE in config_entry.data and config_entry.data[CONF_TYPE] == CONF_SYSTYPE_WEB):
        _LOGGER.info("No binary_sensors for WebPortal...")
    else:
        entities = []
        for description in MAIN_BIN_SENSOR_TYPES:
            entity = SenecBinarySensor(coordinator, description)
            entities.append(entity)
        async_add_entities(entities)


class SenecBinarySensor(SenecEntity, BinarySensorEntity):
    def __init__(
            self,
            coordinator: SenecDataUpdateCoordinator,
            description: ExtBinarySensorEntityDescription
    ):
        """Initialize a singular value sensor."""
        super().__init__(coordinator=coordinator, description=description)
        if (hasattr(self.entity_description, 'entity_registry_enabled_default')):
            self._attr_entity_registry_enabled_default = self.entity_description.entity_registry_enabled_default
        else:
            self._attr_entity_registry_enabled_default = True

        title = self.coordinator._config_entry.title
        key = self.entity_description.key
        name = self.entity_description.name
        self.entity_id = f"binary_sensor.{slugify(title)}_{key}"
        self._attr_name = f"{title} {name}"
        self._attr_icon = self.entity_description.icon
        self._attr_icon_off = self.entity_description.icon_off

    @property
    def is_on(self) -> bool | None:
        """Return true if the binary_sensor is on."""
        # return self.coordinator.data.get("title", "") == "foo"
        try:
            value = getattr(self.coordinator.senec, self.entity_description.key)
            if value is None or value == "":
                value = None
            else:
                self._attr_is_on = value
        except KeyError:
            value = None
        except TypeError:
            return None
        return value

    @property
    def state(self) -> Literal["on", "off"] | None:
        """Return the state."""
        if (is_on := self.is_on) is None:
            return None
        return STATE_ON if is_on else STATE_OFF

    @ property
    def icon(self):
        """Return the icon of the sensor."""
        if self.state == STATE_ON:
            return self._attr_icon
        else:
            return self._attr_icon_off
