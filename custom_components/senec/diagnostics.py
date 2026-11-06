"""Diagnostics of the Waterkotte Heatpump integration (Settings -> Devices & services -> Download diagnostics)."""
from datetime import date, time
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from . import SenecDataUpdateCoordinator
from .const import DOMAIN, CONF_DEV_SERIAL, CONF_OPENAPI_TOKEN

# the credentials and the identification of the heat pump are not part of the diagnostics
TO_REDACT = {CONF_HOST, CONF_PASSWORD, CONF_USERNAME, CONF_OPENAPI_TOKEN, CONF_DEV_SERIAL,
             "Authorization", "serial", "email", "phoneNumber", "address", "systemId", "controlUnitNumber",
             "caseNumber", "street", "productId", "serialNumber"}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, config_entry: ConfigEntry) -> dict[str, Any]:
    """Return the diagnostics of a config entry."""
    coordinator: SenecDataUpdateCoordinator = hass.data[DOMAIN][config_entry.entry_id]
    return {
        "entry": async_redact_data(config_entry.as_dict(), TO_REDACT),
        "options": coordinator._opt,
        "update_interval": coordinator.update_interval.total_seconds() if coordinator.update_interval else None,
        "last_update_success": coordinator.last_update_success,
        "provider": async_redact_data({
            "coordinator": coordinator.data,
            "senec": coordinator.senec.dict_data(),
        }, TO_REDACT),
        "source": async_redact_data(list(coordinator.senec._source), TO_REDACT) if hasattr(coordinator.senec, "_source") else None,
    }