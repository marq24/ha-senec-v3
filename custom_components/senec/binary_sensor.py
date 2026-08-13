"""Binary sensor platform for Waterkotte Heatpump."""
import logging
from dataclasses import replace
from typing import Literal

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_ON, STATE_OFF, CONF_TYPE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import slugify

from . import SenecDataUpdateCoordinator, SenecEntity, CONF_SYSTYPE_SENECCONNECT
from .const import (
    DOMAIN,
    MAIN_BIN_SENSOR_TYPES,
    WEB_BIN_SENSOR_TYPES,
    SENECCONNECT_BIN_SENSOR_WALLBOX_TYPES,
    CONF_SYSTYPE_INVERTER,
    CONF_SYSTYPE_WEB,
    CONF_SYSTYPE_SENECCONNECT,
    ExtBinarySensorEntityDescription,
    StaticFuncs
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry, async_add_entities: AddEntitiesCallback):
    _LOGGER.info("BINARY_SENSOR async_setup_entry")
    coordinator = hass.data[DOMAIN][config_entry.entry_id]
    entities = []
    if CONF_TYPE in config_entry.data and config_entry.data[CONF_TYPE] == CONF_SYSTYPE_INVERTER:
        _LOGGER.info("No binary_sensors for Inverters...")

    elif CONF_TYPE in config_entry.data and config_entry.data[CONF_TYPE] == CONF_SYSTYPE_WEB:
        for description in WEB_BIN_SENSOR_TYPES:
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

            entity = SenecBinarySensor(coordinator, description)
            entities.append(entity)

    elif CONF_TYPE in config_entry.data and config_entry.data[CONF_TYPE] == CONF_SYSTYPE_SENECCONNECT:
        for a_id in coordinator._senec_connect_systems.keys():
            a_system = coordinator._senec_connect_systems[a_id]
            a_serial = a_system.get("serial_number", "UNKNOWN").lower().replace("-", "")
            # for all systems there could be multiple wallboxes... [I guess also max 4 - but who knows]
            a_evse_list = a_system.get("evse", None)
            if a_evse_list is not None and len(a_evse_list) > 0:
                for evse_id in a_evse_list:
                    for description in SENECCONNECT_BIN_SENSOR_WALLBOX_TYPES:
                        entity = SenecBinarySensor(coordinator, replace(description, serial=a_serial, wallbox_id=evse_id, system_id=a_id))
                        entities.append(entity)

    else:
        for description in MAIN_BIN_SENSOR_TYPES:
            entity = SenecBinarySensor(coordinator, description)
            entities.append(entity)

    async_add_entities(entities)


class SenecBinarySensor(SenecEntity, BinarySensorEntity):
    def __init__(
            self,
            a_coordinator: SenecDataUpdateCoordinator,
            a_description: ExtBinarySensorEntityDescription
    ):
        """Initialize a singular value sensor."""
        super().__init__(coordinator=a_coordinator, description=a_description)
        if (hasattr(self.entity_description, 'entity_registry_enabled_default')):
            self._attr_entity_registry_enabled_default = self.entity_description.entity_registry_enabled_default
        else:
            self._attr_entity_registry_enabled_default = True

        title = self.coordinator._config_entry.title
        key = self.entity_description.key.lower()
        name = self.entity_description.name
        self._attr_icon = self.entity_description.icon
        self._attr_icon_off = self.entity_description.icon_off

        self.serial = self.entity_description.serial
        self.wallbox_id = self.entity_description.wallbox_id
        self.system_id = self.entity_description.system_id
        if self.serial is not None:
            if self.wallbox_id is not None:
                self.entity_id = f"binary_sensor.{slugify(title)}_{self.serial}_{self.wallbox_id}_{key}".lower()
            else:
                self.entity_id = f"binary_sensor.{slugify(title)}_{self.serial}_{key}".lower()
        else:
            self.entity_id = f"binary_sensor.{slugify(title)}_{key}".lower()

        # we use the "key" also as our internal translation-key - and EXTREMELY important we have
        self._attr_translation_key = key

    @property
    def is_on(self) -> bool | None:
        """Return true if the binary_sensor is on."""
        # return self.coordinator.data.get("title", "") == "foo"

        if self.entity_description.on_values is not None:
            on_vals = self.entity_description.on_values
        else:
            on_vals = [1]

        try:
            if self.system_id is not None:
                value = getattr(self.coordinator.senec, self.entity_description.key)(self.system_id, self.wallbox_id)
            elif self.entity_description.array_key is not None:
                data = getattr(self.coordinator.senec, self.entity_description.array_key)
                if data is not None and len(data) > self.entity_description.array_pos:
                    value = data[self.entity_description.array_pos] in on_vals
                else:
                    value = None
            else:
                value = getattr(self.coordinator.senec, self.entity_description.key)
                if isinstance(value, int):
                    value = value in on_vals

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

    @property
    def icon(self):
        """Return the icon of the sensor."""
        if self._attr_icon_off is not None and self.state == STATE_OFF:
            return self._attr_icon_off
        else:
            return self._attr_icon
