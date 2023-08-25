"""Platform for Senec Switches."""
import logging

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.typing import HomeAssistantType
from homeassistant.util import slugify
from homeassistant.const import STATE_ON, STATE_OFF, STATE_UNAVAILABLE, STATE_UNKNOWN

from typing import Literal
from . import SenecDataUpdateCoordinator, SenecEntity
from .const import DOMAIN, MAIN_SWITCH_TYPES

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistantType, config_entry: ConfigEntry, async_add_entities):
    """Initialize sensor platform from config entry."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]
    entities = []

    for description in MAIN_SWITCH_TYPES:
        #enabledByDefault  = description.options is None or 'disabled_by_default' not in description.options
        entity = SenecSwitch(coordinator, description, True)
        entities.append(entity)

    async_add_entities(entities)


class SenecSwitch(SenecEntity, SwitchEntity):
    def __init__(
            self,
            coordinator: SenecDataUpdateCoordinator,
            description: SwitchEntityDescription,
            enabled: bool,
    ):
        """Initialize a singular value sensor."""
        super().__init__(coordinator=coordinator, description=description)

        title = self.coordinator._entry.title
        key = self.entity_description.key
        name = self.entity_description.name
        self.entity_id = f"switch.{slugify(title)}_{key}"
        self._attr_name = f"{title} {name}"
        self._coordinator = coordinator
        self._enabled_by_default = enabled

    async def async_turn_on(self, **kwargs):  # pylint: disable=unused-argument
        """Turn on the switch."""
        try:
            await self._coordinator._async_switch_to_state(self.entity_description.key, True)
            return getattr(self.coordinator.senec, self.entity_description.key)
        except ValueError:
            return "unavailable"

    async def async_turn_off(self, **kwargs):  # pylint: disable=unused-argument
        """Turn off the switch."""
        try:
            # print(option)
            await self._coordinator._async_switch_to_state(self.entity_description.key, False)
            return getattr(self.coordinator.senec, self.entity_description.key)
        except ValueError:
            return "unavailable"

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

    def entity_registry_enabled_default(self):
        """Return the entity_registry_enabled_default of the sensor."""
        return self._enabled_by_default

    @property
    def state(self) -> Literal["on", "off"] | None:
        """Return the state."""
        if (is_on := self.is_on) is None:
            return None
        return STATE_ON if is_on else STATE_OFF
