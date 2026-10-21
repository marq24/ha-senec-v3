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
    CONF_SYSTYPE_INVERTER, StaticFuncs, CONF_SYSTYPE_SENECCONNECT, CONF_SYSTYPE_OPENAPI
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry,
                            async_add_entities: AddEntitiesCallback):
    """Initialize number platform from config entry."""
    _LOGGER.info("NUMBER async_setup_entry")
    coordinator = hass.data[DOMAIN][config_entry.entry_id]
    entities = []

    if CONF_TYPE in config_entry.data and config_entry.data[CONF_TYPE] in [CONF_SYSTYPE_INVERTER, CONF_SYSTYPE_OPENAPI]:
        _LOGGER.info("No numbers for Inverters or OpenAPI...")

    elif CONF_TYPE in config_entry.data and config_entry.data[CONF_TYPE] == CONF_SYSTYPE_WEB:
        for description in WEB_NUMBER_TYPES:

            # when we have wallbox data, we want to enable the entity by default...
            a_wallbox_obj = None
            if description.key.startswith("wallbox"):
                possible_idx_str = description.key.lower().split('_')[1]
                try:
                    idx = int(possible_idx_str) - 1
                    a_wallbox_obj = StaticFuncs.app_get_wallbox_obj(coordinator.data, idx)
                except ValueError:
                    _LOGGER.debug(f"No valid wallbox index found in key: {description.key} - {possible_idx_str}")

                if a_wallbox_obj is not None:
                    description = replace(description, entity_registry_enabled_default=True)

                    # we want to adjust the MIN value for the ic_max selectors...
                    if description.key.endswith("set_icmax"):
                        try:
                            the_min_current = a_wallbox_obj.get("chargingCurrents", {}).get("minPossibleCharging", -1)
                            if the_min_current > 0:
                                description = replace(
                                    description,
                                    native_min_value = the_min_current,
                                    native_max_value = 12
                                )
                        except Exception as err:
                            _LOGGER.warning(f"WEB: Could not fetch min/max values for '{description.key}' - cause: {err}")

            entity = SenecNumber(coordinator, description)
            entities.append(entity)

    elif CONF_TYPE in config_entry.data and config_entry.data[CONF_TYPE] == CONF_SYSTYPE_SENECCONNECT:
        _LOGGER.info("No numbers for SENEC.Connect...")

    else:
        for description in MAIN_NUMBER_TYPES:
            must_add_to_patch_max_value_later = False
            if description.array_key == "wallbox_set_icmax":
                if coordinator.senec._bridge_to_senec_online is None:
                    # we somehow must do this later...
                    must_add_to_patch_max_value_later = True
                else:
                    # we already have the SenecOnline running... so we can get from
                    # the SenecLocal implementation, the extremas of the wallbox...
                    min_max = getattr(coordinator.senec, f"{description.key}_extrema")
                    if min_max is not None:
                        _LOGGER.debug(f"NUMBER async_setup_entry(): LOCAL: Going to adjust min/max values for '{description.key}' with min: {min_max[0]} and max: {min_max[1]}")
                        description = replace(
                            description,
                            native_min_value=round(float(min_max[0]), 1),
                            native_max_value=round(float(min_max[1]), 1)
                        )
                    else:
                        _LOGGER.debug(f"NUMBER async_setup_entry(): LOCAL: No min/max values found for '{description.key}'")

            entity = SenecNumber(coordinator, description)
            entities.append(entity)

            # we must adjust min-max later (once we set _bridge_to_senec_online)...
            if must_add_to_patch_max_value_later:
                coordinator.senec._number_entities_to_patch_later.append({
                    "method": f"{description.key}_extrema",
                    "entity": entity}
                )

    async_add_entities(entities)


class SenecNumber(SenecEntity, NumberEntity):
    def __init__(
            self,
            coordinator: SenecDataUpdateCoordinator,
            description: NumberEntityDescription
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
        self.entity_id = f"number.{slugify(title)}_{key}".lower()

        # we use the "key" also as our internal translation-key - and EXTREMELY important we have
        self._attr_translation_key = key

    async def async_added_to_hass(self) -> None:
        """Handle entity which will be added."""
        await super().async_added_to_hass()

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

    @property
    def available(self):
        ret = super().available
        if hasattr(self.entity_description, "availability_check") and self.entity_description.availability_check is not None:
            ret = ret and self.entity_description.availability_check(self.coordinator.data)
        return ret