# Home Assistant Integration for SENEC.Home V2.x/V3/V4 Systems
This Home Assistant Integration is providing information from SENEC.Home V2.x, SENEC.Home V3 and SENEC.Home V4 Systems.
In addition and where possible functions are provided to control the system. 

Please be aware, that we are developing this integration to best of our knowledge and belief, but cant give a guarantee.
Therefore use this integration at your own risk.


## Setup / Installation

### Installation using HACS
[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)

- Install [Home Assistant Community Store (HACS)](https://hacs.xyz/)
- Add custom repository https://github.com/marq24/ha-senec-v3 to HACS
- Add integration repository (search for "SENEC.Home" in "Explore & Download Repositories")
    - Select latest version or `master`
- Restart Home Assistant to install all dependencies


### Manual installation
- Copy all files from `custom_components/senec/` to `custom_components/senec/` inside your config Home Assistant
  directory.
- Restart Home Assistant to install all dependencies


## Adding or enabling the integration

#### My Home Assistant (2021.3+)
Just click the following Button to start the configuration automatically:

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=senec)


#### Manual
Use the following steps for a manual configuration by adding the custom integration using the web interface and follow instruction on screen:

- Go to `Configuration -> Integrations` and add "SENEC.Home" integration
- Select the Integration Type (basically LAN ot WebApi)
- LAN: (`SENEC.Home V3 hybrid/SENEC.Home V3 hybrid duo` or `SENEC.Home V2.1 or older`
  or `Internal inverter build into SENEC.Home V3 hybrid/hybrid duo`)
    - Provide display name for the device, and it's address (hostname or IP)
    - Provide the update intervall
    - Provide area where the battery is located
- WebAPI (`WEB.API: mein-senec.de Portal (usable with all SENEC.Home variants)`
  or `SENEC.Home V4/SENEC.Home V4 hybrid`):
    - Provide display name for the device
    - Provide your mein-senec.de login credentials

You can repreat this to add additional Integration entries (e.g. LAN + WebAPI)

<a id='inv-lnk'></a>


### Switching to this fork
If you used the original integration by [@mchwalisz](https://github.com/mchwalisz), please look at "[Switching [to this] Fork](https://github.com/marq24/ha-senec-v3/issues/14)", before using this integration.


## Supported Devices, Features and Sensors

### Devices
The following devices are currently supported:

|Device|Description|
|---|---|
|SENEC.HOME V2.x|You can use the features and sensors provided by your device via the local API (via lala.cgi) and the Web API (via mein-senec.de)| 
|SENEC.HOME V3|You can use the features and sensors provided by your device via the local API (via lala.cgi) and the Web API (via mein-senec.de)| 
|SENEC.HOME V4|Since the device does not provice a local access, you can just use the features and sensors provided via the Web API (via mein-senec.de).| 
|SENEC.Inverter V3|If you have an internal inverter that is connected to your LAN, you will be able to access information via the Local API. Please see: "Connecting the internal (build in) Senec Inverter Hardware to your LAN and use it in HA" for further information.| 


### Local API
The following Features and Sensors are provided by the local API: Since this is a long list, not everything is enabled by default.
To enable a disabled function or sensor navigate to Settings -> Devices and Services, select the integration and click "configuration" of the device. In the list you can see the status and enable/disable themen.


#### Features
The following features are provided by the local API:
|Feature|Description|Enabled by Default|
|---|---|---|
|Load Battery|With this switch you can load the battery manually|yes|
|Lithium Storage Mode| EXPERIMENTAL: Switch to enable 'storage mode' [state: LITHIUM SAFE MODE DONE'] [disabled by default]. The functionality of this switch is currently __not known__ - IMHO this will disable the functionality of the PV! __Please Note, that once enabled and then disable again the system will go into the 'INSULATION TEST' mode__ for a short while (before returning to normal operation)|no|


#### Sensors
The following Sensors are provided by the local API:
|Sensor|Description|Enabled by Default|
|---|---|---|
|System State|sensor.senec_system_state|yes|
|Battery Temperature|sensor.senec_battery_temp|yes|
|Case Temperature|sensor.senec_case_temp|yes|
|Controller Temperature|sensor.senec_mcu_temp|yes|
|Solar Generated Power|sensor.senec_solar_generated_power|yes|
|House Power|sensor.senec_house_power|yes|
|Battery State Power|sensor.senec_battery_state_power|yes|
|Battery Charge Power|sensor.senec_battery_charge_power|yes|
|Battery Discharge Power|sensor.senec_battery_discharge_power|yes|
|Battery Charge Percent|sensor.senec_battery_charge_percent|yes|
|Grid State Power|sensor.senec_grid_state_power|yes|
|Grid Imported Power|sensor.senec_grid_imported_power|yes|
|Grid Exported Power|sensor.senec_grid_exported_power|yes|
|MPP1 Potential|sensor.senec_solar_mpp1_potential|yes|
|MPP1 Current|sensor.senec_solar_mpp1_current|yes|
|MPP1 Power|sensor.senec_solar_mpp1_power|yes|
|MPP2 Potential|sensor.senec_solar_mpp2_potential|yes|
|MPP2 Current|sensor.senec_solar_mpp2_current|yes|
|MPP2 Power|sensor.senec_solar_mpp2_power|yes|
|MPP3 Potential|sensor.senec_solar_mpp3_potential|yes|
|MPP3 Current|sensor.senec_solar_mpp3_current|yes|
|MPP3 Power|sensor.senec_solar_mpp3_power|yes|
|Enfluri Net Frequency|sensor.senec_enfluri_net_freq|yes|
|Enfluri Net Total Power|sensor.senec_enfluri_net_power_total|yes|
|Enfluri Net Potential Phase 1|sensor.senec_enfluri_net_potential_p1|yes|
|Enfluri Net Potential Phase 2|sensor.senec_enfluri_net_potential_p2|yes|
|Enfluri Net Potential Phase 3|sensor.senec_enfluri_net_potential_p3|yes|
|Enfluri Net Current Phase 1|sensor.senec_enfluri_net_current_p1|yes|
|Enfluri Net Current Phase 2|sensor.senec_enfluri_net_current_p2|yes|
|Enfluri Net Current Phase 3|sensor.senec_enfluri_net_current_p3|yes|
|Enfluri Net Power Phase 1|sensor.senec_enfluri_net_power_p1|yes|
|Enfluri Net Power Phase 2|sensor.senec_enfluri_net_power_p2|yes|
|Enfluri Net Power Phase 3|sensor.senec_enfluri_net_power_p3|yes|
|Enfluri Usage Frequency|sensor.senec_enfluri_usage_freq|no|
|Enfluri Usage Total Power|sensor.senec_enfluri_usage_power_total|no|
|Enfluri Usage Potential Phase 1|sensor.senec_enfluri_usage_potential_p1|no|
|Enfluri Usage Potential Phase 2|sensor.senec_enfluri_usage_potential_p2|no|
|Enfluri Usage Potential Phase 3|sensor.senec_enfluri_usage_potential_p3|no|
|Enfluri Usage Current Phase 1|sensor.senec_enfluri_usage_current_p1|no|
|Enfluri Usage Current Phase 2|sensor.senec_enfluri_usage_current_p2|no|
|Enfluri Usage Current Phase 3|sensor.senec_enfluri_usage_current_p3|no|
|Enfluri Usage Power Phase 1|sensor.senec_enfluri_usage_power_p1|no|
|Enfluri Usage Power Phase 2|sensor.senec_enfluri_usage_power_p2|no|
|Enfluri Usage Power Phase 3|sensor.senec_enfluri_usage_power_p3|no|
|Module A: Cell Temperature A1|sensor.senec_bms_cell_temp_a1|yes|
|Module A: Cell Temperature A2|sensor.senec_bms_cell_temp_a2|yes|
|Module A: Cell Temperature A3|sensor.senec_bms_cell_temp_a3|yes|
|Module A: Cell Temperature A4|sensor.senec_bms_cell_temp_a4|yes|
|Module A: Cell Temperature A5|sensor.senec_bms_cell_temp_a5|yes|
|Module A: Cell Temperature A6|sensor.senec_bms_cell_temp_a6|yes|
|Module B: Cell Temperature B1|sensor.senec_bms_cell_temp_b1|yes|
|Module B: Cell Temperature B2|sensor.senec_bms_cell_temp_b2|yes|
|Module B: Cell Temperature B3|sensor.senec_bms_cell_temp_b3|yes|
|Module B: Cell Temperature B4|sensor.senec_bms_cell_temp_b4|yes|
|Module B: Cell Temperature B5|sensor.senec_bms_cell_temp_b5|yes|
|Module B: Cell Temperature B6|sensor.senec_bms_cell_temp_b6|yes|
|Module C: Cell Temperature C1|sensor.senec_bms_cell_temp_c1|yes|
|Module C: Cell Temperature C2|sensor.senec_bms_cell_temp_c2|yes|
|Module C: Cell Temperature C3|sensor.senec_bms_cell_temp_c3|yes|
|Module C: Cell Temperature C4|sensor.senec_bms_cell_temp_c4|yes|
|Module C: Cell Temperature C5|sensor.senec_bms_cell_temp_c5|yes|
|Module C: Cell Temperature C6|sensor.senec_bms_cell_temp_c6|yes|
|Module D: Cell Temperature D1|sensor.senec_bms_cell_temp_d1|no|
|Module D: Cell Temperature D2|sensor.senec_bms_cell_temp_d2|no|
|Module D: Cell Temperature D3|sensor.senec_bms_cell_temp_d3|no|
|Module D: Cell Temperature D4|sensor.senec_bms_cell_temp_d4|no|
|Module D: Cell Temperature D5|sensor.senec_bms_cell_temp_d5|no|
|Module D: Cell Temperature D6|sensor.senec_bms_cell_temp_d6|no|
|Module A: Cell Voltage A1|sensor.senec_bms_cell_volt_a1|no|
|Module A: Cell Voltage A2|sensor.senec_bms_cell_volt_a2|no|
|Module A: Cell Voltage A3|sensor.senec_bms_cell_volt_a3|no|
|Module A: Cell Voltage A4|sensor.senec_bms_cell_volt_a4|no|
|Module A: Cell Voltage A5|sensor.senec_bms_cell_volt_a5|no|
|Module A: Cell Voltage A6|sensor.senec_bms_cell_volt_a6|no|
|Module A: Cell Voltage A7|sensor.senec_bms_cell_volt_a7|no|
|Module A: Cell Voltage A8|sensor.senec_bms_cell_volt_a8|no|
|Module A: Cell Voltage A9|sensor.senec_bms_cell_volt_a9|no|
|Module A: Cell Voltage A10|sensor.senec_bms_cell_volt_a10|no|
|Module A: Cell Voltage A11|sensor.senec_bms_cell_volt_a11|no|
|Module A: Cell Voltage A12|sensor.senec_bms_cell_volt_a12|no|
|Module A: Cell Voltage A13|sensor.senec_bms_cell_volt_a13|no|
|Module A: Cell Voltage A14|sensor.senec_bms_cell_volt_a14|no|
|Module B: Cell Voltage B1|sensor.senec_bms_cell_volt_b1|no|
|Module B: Cell Voltage B2|sensor.senec_bms_cell_volt_b2|no|
|Module B: Cell Voltage B3|sensor.senec_bms_cell_volt_b3|no|
|Module B: Cell Voltage B4|sensor.senec_bms_cell_volt_b4|no|
|Module B: Cell Voltage B5|sensor.senec_bms_cell_volt_b5|no|
|Module B: Cell Voltage B6|sensor.senec_bms_cell_volt_b6|no|
|Module B: Cell Voltage B7|sensor.senec_bms_cell_volt_b7|no|
|Module B: Cell Voltage B8|sensor.senec_bms_cell_volt_b8|no|
|Module B: Cell Voltage B9|sensor.senec_bms_cell_volt_b9|no|
|Module B: Cell Voltage B10|sensor.senec_bms_cell_volt_b10|no|
|Module B: Cell Voltage B11|sensor.senec_bms_cell_volt_b11|no|
|Module B: Cell Voltage B12|sensor.senec_bms_cell_volt_b12|no|
|Module B: Cell Voltage B13|sensor.senec_bms_cell_volt_b13|no|
|Module B: Cell Voltage B14|sensor.senec_bms_cell_volt_b14|no|
|Module C: Cell Voltage C1|sensor.senec_bms_cell_volt_c1|no|
|Module C: Cell Voltage C2|sensor.senec_bms_cell_volt_c2|no|
|Module C: Cell Voltage C3|sensor.senec_bms_cell_volt_c3|no|
|Module C: Cell Voltage C4|sensor.senec_bms_cell_volt_c4|no|
|Module C: Cell Voltage C5|sensor.senec_bms_cell_volt_c5|no|
|Module C: Cell Voltage C6|sensor.senec_bms_cell_volt_c6|no|
|Module C: Cell Voltage C7|sensor.senec_bms_cell_volt_c7|no|
|Module C: Cell Voltage C8|sensor.senec_bms_cell_volt_c8|no|
|Module C: Cell Voltage C9|sensor.senec_bms_cell_volt_c9|no|
|Module C: Cell Voltage C10|sensor.senec_bms_cell_volt_c10|no|
|Module C: Cell Voltage C11|sensor.senec_bms_cell_volt_c11|no|
|Module C: Cell Voltage C12|sensor.senec_bms_cell_volt_c12|no|
|Module C: Cell Voltage C13|sensor.senec_bms_cell_volt_c13|no|
|Module C: Cell Voltage C14|sensor.senec_bms_cell_volt_c14|no|
|Module D: Cell Voltage D1|sensor.senec_bms_cell_volt_d1|no|
|Module D: Cell Voltage D2|sensor.senec_bms_cell_volt_d2|no|
|Module D: Cell Voltage D3|sensor.senec_bms_cell_volt_d3|no|
|Module D: Cell Voltage D4|sensor.senec_bms_cell_volt_d4|no|
|Module D: Cell Voltage D5|sensor.senec_bms_cell_volt_d5|no|
|Module D: Cell Voltage D6|sensor.senec_bms_cell_volt_d6|no|
|Module D: Cell Voltage D7|sensor.senec_bms_cell_volt_d7|no|
|Module D: Cell Voltage D8|sensor.senec_bms_cell_volt_d8|no|
|Module D: Cell Voltage D9|sensor.senec_bms_cell_volt_d9|no|
|Module D: Cell Voltage D10|sensor.senec_bms_cell_volt_d10|no|
|Module D: Cell Voltage D11|sensor.senec_bms_cell_volt_d11|no|
|Module D: Cell Voltage D12|sensor.senec_bms_cell_volt_d12|no|
|Module D: Cell Voltage D13|sensor.senec_bms_cell_volt_d13|no|
|Module D: Cell Voltage D14|sensor.senec_bms_cell_volt_d14|no|
|Module A: Voltage|sensor.senec_bms_voltage_a|yes|
|Module B: Voltage|sensor.senec_bms_voltage_b|yes|
|Module C: Voltage|sensor.senec_bms_voltage_c|yes|
|Module D: Voltage|sensor.senec_bms_voltage_d|yes|
|Module A: Current|sensor.senec_bms_current_a|yes|
|Module B: Current|sensor.senec_bms_current_b|yes|
|Module C: Current|sensor.senec_bms_current_c|yes|
|Module D: Current|sensor.senec_bms_current_d|yes|
|Module A: State of charge|sensor.senec_bms_soc_a|yes|
|Module B: State of charge|sensor.senec_bms_soc_b|yes|
|Module C: State of charge|sensor.senec_bms_soc_c|yes|
|Module D: State of charge|sensor.senec_bms_soc_d|yes|
|Module A: State of Health|sensor.senec_bms_soh_a|yes|
|Module B: State of Health|sensor.senec_bms_soh_b|yes|
|Module C: State of Health|sensor.senec_bms_soh_c|yes|
|Module D: State of Health|sensor.senec_bms_soh_d|yes|
|Module A: Cycles|sensor.senec_bms_cycles_a|yes|
|Module B: Cycles|sensor.senec_bms_cycles_b|yes|
|Module C: Cycles|sensor.senec_bms_cycles_c|yes|
|Module D: Cycles|sensor.senec_bms_cycles_d|yes|
|Wallbox Power|sensor.senec_wallbox_power|no|
|Wallbox EV Connected|sensor.senec_wallbox_ev_connected|no|
|Fan LV-Inverter|binary_sensor.senec_fan_inv_lv|yes|
|Fan HV-Inverter|binary_sensor.senec_fan_inv_hv|no

### Web API
The following Features and Sensors are provided by the Web API. Not all are enabled by default.
To enable a disabled function or sensor navigate to Settings -> Devices and Services, select the integration and click "configuration" of the device. In the list you can see the status and enable/disable themen.


#### Features
The following features are provided by the Web API:
|Feature|Description|Enabled by Default|
|---|---|---|
|WEBAPI Spare Capacity|Current spare capacity in percent with the option to update. Precondition: When you are using "SENEC Backup Power pro" and you are able to see and update the spare capacity at mein-senec.de, than you can read and update the spare capacity with this integration.|no|


#### Sensors
The following Sensors are provided by the Web API:
|Sensor|Description|Enabled by Default|
|---|---|---|
|WEBAPI Battery Charge Percent|Current charge level of Battery in percent|yes|
|WEBAPI Battery Charge Power|Curent charge power of Battery|yes|
|WEBAPI Battery charged|Total: Charged power in Battery - This information is needed for the energy dashboard|yes|
|WEBAPI Battery Discharge Power|Current discharge power of Battery|yes|
|WEBAPI Battery discharged|Total: Discharged power from Battery - This information is needed for the energy dashboard|yes|
|WEBAPI Grid Exported|Total: Power exported to the grid - This information is needed for the energy dashboard|yes|
|WEBAPI Grid Exported Power|Current power exporting to the grid|yes|
|WEBAPI Grid Imported|Total: Power imported from the grid - This information is needed for the energy dashboard|yes|
|WEBAPI Grid Imported Power|Current power imported from the grid|yes|
|WEBAPI House consumed|Total: Amout of power consumed by the House - This information is needed for the energy dashboard|yes|
|WEBAPI House Power|Current power used by the House|yes|
|WEBAPI Solar generated|Total: Power generated by the Solar - This information is needed for the energy dashboard|yes|
|WEBAPI Solar Generated Power|Current power generated by Solar|yes|

# User guide for setup and installation
Here you will find additional information regarding setup and configuration.


## Connecting the internal (build in) Senec Inverter Hardware to your LAN and use it in HA
The __SENEC.Home V3 hybrid duo__ have build in two inverters - called LV and HV. This hardware has its own LAN
connectors, but they have not been connected during the installation process (I guess by purpose).


### __DO THIS ON YOUR OWN RISK!__
Nevertheless, when you dismount the front and the right hand side panels you simply can plug in RJ45 LAN cables into
both of the inverters LAN connectors and after a short while you should be able to access the web frontends of the
inverters via your browser.

_Don't forget to assign fixed IP's to the additional inverter hardware. You can unplug the LAN cable for a short while
in order to make sure that the inverters will make use of the fixed assigned IP's._


### Position of SENEC.Inverter V3 LV LAN connector
![img|160x90](images/inv_lv.png)
On the front of the device


### Position of SENEC.Inverter V3 HV LAN connector _(hybrid duo only!)_
![img|160x90](images/inv_hv.png)
On the right hand side of the device


### Adding Inverter(s) to your HA
Once you have connected the inverter(s) with your LAN you can add another integration entry to your Senec Integration in
Home Assistant:

1. go to '__Settings__' -> '__Devices & Services__'
2. select the '__SENEC.Home__' integration.
3. there you find the '__Add Entry__' button (at the bottom of the '__Integration entries__' list)
4. specify the IP (or hostname) of the inverter you want to add
5. __important:__ assign a name (e.g. _INV_LV_).

Repeat step 3, 4 & 5 of this procedure, if you have build in two inverters into your Senec.HOME.


## Home Assistant Energy Dashboard
This integration supports Home Assistant's [Energy Management](https://www.home-assistant.io/docs/energy/).
To use the Energy Dashboard please set up the Web API first.
In the description of the Web API you will see which sensors you can use for the Energy Dashboard.

Example setup:

![Energy Dashboard Setup](images/energy_dashboard.png)

Resulting energy distribution card:

![Energy Distribution](images/energy_distribution.png)


# Credentials
|Who|Description|
|---|---|
|[@mchwalisz](https://github.com/mchwalisz)| This fork was created from [mchwalisz/home-assistant-senec](https://gitgub.com/mchwalisz/home-assistant-senec) since we needed more detailed information and configuration options|
|[@marq24](https://github.com/marq24)|@marq24 created this fork, e.g. added several sensors and functions and is maintaining the integration.|
|[@mstuettgen](https://github.com/mstuettgen)|Provided the initial WEB-API for SENEC.Home V4 web access.|
|[@io-debug](https://github.com/io-debug)|E.g. provided the initial developer documentation and added functionality like the spare capacity management.|

# Developer information
If you are interested in some details about this implementation and the current known fields you might like to take a
look into the [current developer documentation section](./DEVELOPER_DOCUMENTATION.md).
