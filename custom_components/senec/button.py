import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_TYPE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import slugify
from . import SenecEntity, SenecDataUpdateCoordinator
from .const import (
    DOMAIN,
    MAIN_BUTTON_TYPES,
    WEB_BUTTON_TYPES,
    ExtButtonEntityDescription,
    CONF_SYSTYPE_INVERTER,
    CONF_SYSTYPE_WEB)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry, add_entity_cb: AddEntitiesCallback):
    _LOGGER.info("BUTTON async_setup_entry")
    coordinator = hass.data[DOMAIN][config_entry.entry_id]
    entities = []
    if CONF_TYPE in config_entry.data and config_entry.data[CONF_TYPE] == CONF_SYSTYPE_INVERTER:
        _LOGGER.info("No buttons for Inverters...")
    elif CONF_TYPE in config_entry.data and config_entry.data[CONF_TYPE] == CONF_SYSTYPE_WEB:
        for description in WEB_BUTTON_TYPES:
            entity = SenecButton(coordinator, description)
            entities.append(entity)
    else:
        is_2408_or_higher: bool = await coordinator._async_is2408_or_later()

        for description in MAIN_BUTTON_TYPES:
            do_add = False
            if hasattr(description, 'require_2408') and description.require_2408:
                if is_2408_or_higher:
                    do_add = True
            else:
                do_add = True

            if do_add:
                entity = SenecButton(coordinator, description)
                entities.append(entity)

    add_entity_cb(entities)


class SenecButton(SenecEntity, ButtonEntity):
    def __init__(self, coordinator: SenecDataUpdateCoordinator, description: ExtButtonEntityDescription):
        super().__init__(coordinator=coordinator, description=description)
        if (hasattr(self.entity_description, 'entity_registry_enabled_default')):
            self._attr_entity_registry_enabled_default = self.entity_description.entity_registry_enabled_default
        else:
            self._attr_entity_registry_enabled_default = True

        title = self.coordinator._config_entry.title
        key = self.entity_description.key.lower()
        name = self.entity_description.name
        self._attr_icon = self.entity_description.icon
        self.entity_id = f"button.{slugify(title)}_{key}"

        # we use the "key" also as our internal translation-key - and EXTREMELY important we have
        # to set the '_attr_has_entity_name' to trigger the calls to the localization framework!
        self._attr_translation_key = key
        self._attr_has_entity_name = True

    async def async_press(self, **kwargs):
        try:
            await self.coordinator._async_trigger_button(trigger_key=self.entity_description.key, payload=self.entity_description.payload)
        except ValueError:
            return "unavailable"
