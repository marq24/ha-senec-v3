"""Platform for Senec sensors."""
import logging
from time import time

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_TYPE
from homeassistant.core import HomeAssistant
from homeassistant.core import State
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import slugify
from . import SenecDataUpdateCoordinator, SenecEntity
from .const import (
    DOMAIN,
    MAIN_SENSOR_TYPES,
    INVERTER_SENSOR_TYPES,
    WEB_SENSOR_TYPES,
    CONF_SUPPORT_BDC,
    CONF_SYSTYPE_INVERTER,
    CONF_SYSTYPE_WEB,
    ExtSensorEntityDescription
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry,
                            async_add_entities: AddEntitiesCallback):
    """Initialize sensor platform from config entry."""
    _LOGGER.debug("SENSOR async_setup_entry")
    coordinator = hass.data[DOMAIN][config_entry.entry_id]
    entities = []
    if CONF_TYPE in config_entry.data and config_entry.data[CONF_TYPE] == CONF_SYSTYPE_INVERTER:
        for description in INVERTER_SENSOR_TYPES:
            add_entity = description.controls is None
            if not add_entity:
                if 'bdc_only' in description.controls:
                    if (config_entry.data[CONF_SUPPORT_BDC]):
                        add_entity = True
                else:
                    add_entity = True

            if add_entity:
                entity = SenecSensor(coordinator, description)
                entities.append(entity)

    elif CONF_TYPE in config_entry.data and config_entry.data[CONF_TYPE] == CONF_SYSTYPE_WEB:
        for description in WEB_SENSOR_TYPES:
            entity = SenecSensor(coordinator, description)
            entities.append(entity)

    else:
        for description in MAIN_SENSOR_TYPES:
            add_entity = description.controls is None
            if not add_entity:
                if 'require_stats_fields' in description.controls:
                    if coordinator._statistics_available:
                        add_entity = True
                else:
                    add_entity = True

            if add_entity:
                entity = SenecSensor(coordinator, description)
                entities.append(entity)

    async_add_entities(entities)


# class SenecSensor(SenecEntity, RestoreSensor, SensorEntity):
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
        self._previous_float_value: float | None = None
        self._is_total_increasing: bool = (description is not None and
                                           isinstance(description, ExtSensorEntityDescription) and
                                           hasattr(description, "controls") and
                                           description.controls is not None and
                                           "only_increasing" in description.controls)

        self._previous_plausible_value_ts = time()
        self._previous_plausible_value: int | float | None = None
        self._check_plausibility: bool = (description is not None and
                                          isinstance(description, ExtSensorEntityDescription) and
                                          hasattr(description, "controls") and
                                          description.controls is not None and
                                          "check_plausibility" in description.controls)

    @property
    def native_value(self):
        """Return the current state."""
        if self.entity_description.array_key is not None:
            data = getattr(self.coordinator.senec, self.entity_description.array_key)
            if data is not None and len(data) > self.entity_description.array_pos:
                value = data[self.entity_description.array_pos]
            else:
                value = None
        else:
            value = getattr(self.coordinator.senec, self.entity_description.key)

        # _LOGGER.debug( str(sensor)+' '+ str(type(value)) +' '+str(value))
        if isinstance(value, bool):
            return value
        else:
            if isinstance(value, int):
                return value
            else:
                # always try to parse sensor value as float
                try:
                    value = float(value)
                except (ValueError, TypeError):
                    return value

                # 1: SENEC API returns 1e-05 for some values, which is not a valid value
                # -----------------
                # _check_plausibility only implemented for web-api 'acculevel_now'
                # and if the value is not 'plausible', then the return value is a float! (and not an int)
                if self._check_plausibility:
                    # sometime fucking SENEC API return 1e-05, when the actual value
                    # should be way larger than 1e-05
                    if value == 1e-05:
                        # if there is a valid '_previous_plausible_value' stored...
                        if self._previous_plausible_value is not None and self._previous_plausible_value != 1e-05:
                            # we only use a previous value if it's not older than
                            # 2 times the configured update interval + 30 seconds...
                            if self._previous_plausible_value_ts + ((2 *  self.coordinator.update_interval()) + 30) < time():
                                _LOGGER.debug(f"Thanks for nothing Senec! - API provided '{value}' for key {self._attr_translation_key} - but last known value before was: {self._previous_plausible_value}")
                                return self._previous_plausible_value
                    else:
                        self._previous_plausible_value_ts = time()
                        self._previous_plausible_value = value

                    # if we haven't returned any value yet, we use the value that we
                    # have actually read from the API
                    return value

                # 2: SENEC API returns sometimes smaller values, even if the values should increase
                # -----------------
                # do not update if value is lower than the current state
                # this is only an issue for _total sensors
                # since the API may return false values in this case
                if not self._is_total_increasing:
                    return value
                elif (self._previous_float_value is not None) and (value < self._previous_float_value):
                    _LOGGER.debug(f"Thanks for nothing Senec! prev>new for key {self._attr_translation_key} - prev:{self._previous_float_value} new: {value}")
                    return self._previous_float_value
                else:
                    self._previous_float_value = value
                    return value

    async def async_added_to_hass(self) -> None:
        """Call when entity about to be added to Home Assistant."""
        await super().async_added_to_hass()
        if self._is_total_increasing:
            # get the last known value
            last_sensor_data = await self.async_get_last_state()
            if last_sensor_data is not None and isinstance(last_sensor_data,
                                                           State) and last_sensor_data.state is not None:
                try:
                    self._previous_float_value = float(last_sensor_data.state)
                    _LOGGER.debug(f"restored prev value for key {self._attr_translation_key}: {last_sensor_data.state}")
                except:
                    _LOGGER.debug(f"ignoring prev value for key {self._attr_translation_key}: cause value is: {last_sensor_data.state}")
                    self._previous_float_value = None
                    pass
