"""Constants for the Senec integration."""
from collections import namedtuple
from datetime import timedelta
from typing import Final

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    ENERGY_KILO_WATT_HOUR,
    PERCENTAGE,
    POWER_WATT,
    TEMP_CELSIUS,
    UnitOfElectricPotential,
    UnitOfElectricCurrent, UnitOfFrequency,
)

DOMAIN = "senec"
MANUFACTURE = "SENEC GmbH"
CONF_DEV_TYPE = "dtype"
CONF_SUPPORT_BDC = "has_bdc_support"
CONF_DEV_NAME = "dname"
CONF_DEV_SERIAL = "dserial"
CONF_DEV_VERSION = "version"

"""Default config for Senec."""
DEFAULT_HOST = "Senec"
DEFAULT_NAME = "senec"
DEFAULT_SCAN_INTERVAL = 30

"""Supported sensor types."""

MAIN_SENSOR_TYPES = [
    SensorEntityDescription(
        key="system_state",
        name="System State",
        icon="mdi:solar-power",
    ),
    SensorEntityDescription(
        key="battery_temp",
        name="Battery Temperature",
        native_unit_of_measurement=TEMP_CELSIUS,
        icon="mdi:thermometer",
    ),
    SensorEntityDescription(
        key="case_temp",
        name="Case Temperature",
        native_unit_of_measurement=TEMP_CELSIUS,
        icon="mdi:thermometer",
    ),
    SensorEntityDescription(
        key="mcu_temp",
        name="Controller Temperature",
        native_unit_of_measurement=TEMP_CELSIUS,
        icon="mdi:thermometer",
    ),
    SensorEntityDescription(
        key="solar_generated_power",
        name="Solar Generated Power",
        native_unit_of_measurement=POWER_WATT,
        icon="mdi:solar-power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="house_power",
        name="House Power",
        native_unit_of_measurement=POWER_WATT,
        icon="mdi:home-import-outline",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="battery_state_power",
        name="Battery State Power",
        native_unit_of_measurement=POWER_WATT,
        icon="mdi:home-battery",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="battery_charge_power",
        name="Battery Charge Power",
        native_unit_of_measurement=POWER_WATT,
        icon="mdi:home-battery",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="battery_discharge_power",
        name="Battery Discharge Power",
        native_unit_of_measurement=POWER_WATT,
        icon="mdi:home-battery-outline",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="battery_charge_percent",
        name="Battery Charge Percent",
        native_unit_of_measurement=PERCENTAGE,
        icon="mdi:home-battery",
        # device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="grid_state_power",
        name="Grid State Power",
        native_unit_of_measurement=POWER_WATT,
        icon="mdi:transmission-tower",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="grid_imported_power",
        name="Grid Imported Power",
        native_unit_of_measurement=POWER_WATT,
        icon="mdi:transmission-tower-import",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="grid_exported_power",
        name="Grid Exported Power",
        native_unit_of_measurement=POWER_WATT,
        icon="mdi:transmission-tower-export",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="house_total_consumption",
        name="House consumed",
        native_unit_of_measurement=ENERGY_KILO_WATT_HOUR,
        icon="mdi:home-import-outline",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    SensorEntityDescription(
        key="solar_total_generated",
        name="Solar generated",
        native_unit_of_measurement=ENERGY_KILO_WATT_HOUR,
        icon="mdi:solar-power",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    SensorEntityDescription(
        key="battery_total_charged",
        name="Battery charged",
        native_unit_of_measurement=ENERGY_KILO_WATT_HOUR,
        icon="mdi:home-battery",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    SensorEntityDescription(
        key="battery_total_discharged",
        name="Battery discharged",
        native_unit_of_measurement=ENERGY_KILO_WATT_HOUR,
        icon="mdi:home-battery-outline",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    SensorEntityDescription(
        key="grid_total_import",
        name="Grid Imported",
        native_unit_of_measurement=ENERGY_KILO_WATT_HOUR,
        icon="mdi:transmission-tower-import",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    SensorEntityDescription(
        key="grid_total_export",
        name="Grid Exported",
        native_unit_of_measurement=ENERGY_KILO_WATT_HOUR,
        icon="mdi:transmission-tower-export",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),

    SensorEntityDescription(
        key="solar_mpp1_potential",
        name="MPP1 Potential",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        icon="mdi:lightning-bolt",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="solar_mpp1_current",
        name="MPP1 Current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        icon="mdi:current-dc",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="solar_mpp1_power",
        name="MPP1 Power",
        native_unit_of_measurement=POWER_WATT,
        icon="mdi:meter-electric",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="solar_mpp2_potential",
        name="MPP2 Potential",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        icon="mdi:lightning-bolt",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="solar_mpp2_current",
        name="MPP2 Current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        icon="mdi:current-dc",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="solar_mpp2_power",
        name="MPP2 Power",
        native_unit_of_measurement=POWER_WATT,
        icon="mdi:meter-electric",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="solar_mpp3_potential",
        name="MPP3 Potential",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        icon="mdi:lightning-bolt",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="solar_mpp3_current",
        name="MPP3 Current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        icon="mdi:current-dc",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="solar_mpp3_power",
        name="MPP3 Power",
        native_unit_of_measurement=POWER_WATT,
        icon="mdi:meter-electric",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.MEASUREMENT,
    ),

    SensorEntityDescription(
        key="enfluri_net_freq",
        name="Enfluri Net Frequency",
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        icon="mdi:meter-electric",
        device_class=SensorDeviceClass.FREQUENCY,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="enfluri_net_power_total",
        name="Enfluri Net Total Power",
        native_unit_of_measurement=POWER_WATT,
        icon="mdi:meter-electric",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="enfluri_net_potential_p1",
        name="Enfluri Net Potential Phase 1",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        icon="mdi:lightning-bolt",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="enfluri_net_potential_p2",
        name="Enfluri Net Potential Phase 2",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        icon="mdi:lightning-bolt",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="enfluri_net_potential_p3",
        name="Enfluri Net Potential Phase 3",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        icon="mdi:lightning-bolt",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="enfluri_net_current_p1",
        name="Enfluri Net Current Phase 1",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        icon="mdi:current-dc",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="enfluri_net_current_p2",
        name="Enfluri Net Current Phase 2",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        icon="mdi:current-dc",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="enfluri_net_current_p3",
        name="Enfluri Net Current Phase 3",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        icon="mdi:current-dc",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="enfluri_net_power_p1",
        name="Enfluri Net Power Phase 1",
        native_unit_of_measurement=POWER_WATT,
        icon="mdi:meter-electric",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="enfluri_net_power_p2",
        name="Enfluri Net Power Phase 2",
        native_unit_of_measurement=POWER_WATT,
        icon="mdi:meter-electric",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="enfluri_net_power_p3",
        name="Enfluri Net Power Phase 3",
        native_unit_of_measurement=POWER_WATT,
        icon="mdi:meter-electric",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.MEASUREMENT,
    ),
]

INVERTER_SENSOR_TYPES = [
    SensorEntityDescription(
        key="ac_voltage",
        name="AC Voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        icon="mdi:lightning-bolt",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.MEASUREMENT,
    ),

    SensorEntityDescription(
        key="ac_current",
        name="AC current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        icon="mdi:current-ac",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.MEASUREMENT,
    ),

    SensorEntityDescription(
        key="ac_power",
        name="AC Power",
        native_unit_of_measurement=POWER_WATT,
        icon="mdi:solar-power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),

    SensorEntityDescription(
        key="ac_power_fast",
        name="AC Power (fast)",
        native_unit_of_measurement=POWER_WATT,
        icon="mdi:solar-power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),

    SensorEntityDescription(
        key="ac_frequency",
        name="AC Frequency",
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        icon="mdi:meter-electric",
        device_class=SensorDeviceClass.FREQUENCY,
        state_class=SensorStateClass.MEASUREMENT,
    ),


    SensorEntityDescription(
        options=("bdc_only"),
        key="bdc_bat_voltage",
        name="BDC Battery Voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        icon="mdi:lightning-bolt",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.MEASUREMENT,
    ),

    SensorEntityDescription(
        options=("bdc_only"),
        key="bdc_bat_current",
        name="BDC Battery Current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        icon="mdi:current-dc",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.MEASUREMENT,
    ),

    SensorEntityDescription(
        options=("bdc_only"),
        key="bdc_bat_power",
        name="BDC Battery Power",
        native_unit_of_measurement=POWER_WATT,
        icon="mdi:battery-charging-100",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),

    SensorEntityDescription(
        options=("bdc_only"),
        key="bdc_link_voltage",
        name="BDC Link Voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        icon="mdi:lightning-bolt",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.MEASUREMENT,
    ),

    SensorEntityDescription(
        options=("bdc_only"),
        key="bdc_link_current",
        name="BDC Link Current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        icon="mdi:current-dc",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.MEASUREMENT,
    ),

    SensorEntityDescription(
        options=("bdc_only"),
        key="bdc_link_power",
        name="BDC Link Power",
        native_unit_of_measurement=POWER_WATT,
        icon="mdi:power-plug-outline",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),

    SensorEntityDescription(
        key="dc_voltage1",
        name="DC Voltage 1",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        icon="mdi:lightning-bolt",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="dc_voltage2",
        name="DC Voltage 2",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        icon="mdi:lightning-bolt",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="dc_current1",
        name="DC current 1",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        icon="mdi:current-dc",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="dc_current2",
        name="DC current 2",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        icon="mdi:current-dc",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.MEASUREMENT,
    ),

    SensorEntityDescription(
        key="gridpower",
        name="Grid Power",
        native_unit_of_measurement=POWER_WATT,
        icon="mdi:transmission-tower",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="gridconsumedpower",
        name="Grid consumed Power",
        native_unit_of_measurement=POWER_WATT,
        icon="mdi:transmission-tower-import",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="gridinjectedpower",
        name="Grid injected Power",
        native_unit_of_measurement=POWER_WATT,
        icon="mdi:transmission-tower-export",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="ownconsumedpower",
        name="Own consumed Power",
        native_unit_of_measurement=POWER_WATT,
        icon="mdi:home-import-outline",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="_derating",
        name="Derating",
        native_unit_of_measurement=PERCENTAGE,
        icon="mdi:arrow-down-thin-circle-outline",
        state_class=SensorStateClass.MEASUREMENT,
    ),
]
