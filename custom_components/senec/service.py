""" Services for SENEC Device"""

from datetime import datetime


class SenecService():

    def __init__(self, hass, config, coordinator):
        """ Initialize """
        self._hass = hass
        self._config = config
        self._coordinator = coordinator

    async def set_peakshaving(self, call):
        # Get date from service call
        mode = call.data.get("mode", None)
        capacity = call.data.get("capacity", None)
        end_time = call.data.get("end_time", None)

        if end_time is not None:
            selected_time = datetime.strptime(end_time, "%H:%M:%S").time()
            end_time = datetime.combine(datetime.today(),
                                        selected_time)  # User sets just a time, create a valid timestamp
            end_time = int(end_time.timestamp()) * 1000  # We have to send the timestamp in miliseconds to senec
        try:
            new_peak_shaving = {"mode": mode, "capacity": capacity, "end_time": end_time}
            await self._coordinator.senec.set_peak_shaving(new_peak_shaving)

            # Force update
            # registry = entity_registry.async_get(self._hass)
            # peakshaving_mode_key = f"sensor.{slugify(ConfigEntry.title)}_peakshaving_mode".lower()
            # entity = registry.async_get(peakshaving_mode_key)
            # entity.async_schedule_update_ha_state(force_refresh=True)

            return True
        except ValueError:
            return "unavailable"
