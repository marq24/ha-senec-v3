"""Platform for Senec numbers."""
import asyncio
import logging
from dataclasses import replace

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
    WEB_NUMBER_TYPES,
    CONF_SYSTYPE_WEB,
    CONF_SYSTYPE_INVERTER
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry,
                            async_add_entities: AddEntitiesCallback):
    """Initialize sensor platform from config entry."""
    _LOGGER.info("NUMBER async_setup_entry")
    coordinator = hass.data[DOMAIN][config_entry.entry_id]
    entities = []

    if CONF_TYPE in config_entry.data and config_entry.data[CONF_TYPE] == CONF_SYSTYPE_INVERTER:
        _LOGGER.info("No numbers for Inverters...")

    elif CONF_TYPE in config_entry.data and config_entry.data[CONF_TYPE] == CONF_SYSTYPE_WEB:
        for description in WEB_NUMBER_TYPES:
            # we want to adjust the MIN value for the ic_max selectors...
            if description.key.endswith("set_icmax"):
                try:
                    a_state_key = description.key.replace("_set_icmax", "_state")
                    attr_func_name = f"{a_state_key}_attr"
                    if hasattr(coordinator.senec, attr_func_name):
                        a_dict = getattr(coordinator.senec, attr_func_name)
                        if a_dict is not None:
                            the_min_current = a_dict.get("json", {}).get("chargingCurrents", {}).get("minPossibleCharging", -1)
                            if the_min_current > 0:
                                description = replace(
                                    description,
                                    native_min_value = the_min_current,
                                    native_max_value = 16.02
                                )
                except Exception as err:
                    _LOGGER.error(f"WEB: Could not fetch min/max values for '{description.key}' - cause: {err}")

            entity = SenecNumber(coordinator, description, False)
            entities.append(entity)
    else:
        for description in MAIN_NUMBER_TYPES:
            entity = SenecNumber(coordinator, description, True)
            entities.append(entity)

    async_add_entities(entities)


class SenecNumber(SenecEntity, NumberEntity):
    def __init__(
            self,
            coordinator: SenecDataUpdateCoordinator,
            description: NumberEntityDescription,
            adjust_min_max: bool = False
    ):
        """Initialize"""
        super().__init__(coordinator=coordinator, description=description)
        self._adjust_min_max = adjust_min_max

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

    async def async_added_to_hass(self) -> None:
        """Handle entity which will be added."""
        await super().async_added_to_hass()

        # we want to adjust the MIN value for the ic_max selectors...
        if self._adjust_min_max and self.entity_description.key.endswith("set_icmax"):
            try:
                # waiting for WEBapi Integration to become available...
                counter = 1
                while counter < 6 and self.coordinator.senec._bridge_to_senec_online is None:
                    _LOGGER.debug(f"LOCAL: Waiting {(counter * 5)} sec for WEBapi Integration to become available - counter: {counter}")
                    await asyncio.sleep(counter * 5)
                    counter += 1

                _LOGGER.debug(f"LOCAL: Try to adjust min/max values for '{self.entity_description.key}'")
                min_max = getattr(self.coordinator.senec, self.entity_description.key + "_extrema")
                if min_max is not None:
                    self.entity_description = replace(
                        self.entity_description,
                        native_min_value=round(float(min_max[0]), 1),
                        native_max_value=round(float(min_max[1]), 1)
                    )
            except Exception as err:
                _LOGGER.error(f"LOCAL: Could not fetch min/max values for '{self.entity_description.key}' - cause: {err}")

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

        if value is not None:
            return float(value)

        return None

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
