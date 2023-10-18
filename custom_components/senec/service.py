""" Services for SENEC Device"""
from custom_components.senec.pysenec_ha import MySenecWebPortal

class SenecService():
       
    def __init__(self, hass, config, coordinator):  
        """ Initialize """
        self._hass = hass
        self._config = config
        self._coordinator = coordinator

    async def set_peakshaving(self, call):
        try:
            return True
        except ValueError:
            return "unavailable"