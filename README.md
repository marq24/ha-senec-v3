# Home Assistant Integration for SENEC.Home V2.x/V3/V4 Systems

This Home Assistant Integration is providing information from SENEC.Home V2.x, SENEC.Home V3 and SENEC.Home V4 Systems. In addition and where possible functions are provided to control the system.

## Disclaimer

Please be aware, that we are developing this integration to best of our knowledge and belief, but cant give a guarantee. Therefore, use this integration **at your own risk**.

[![hacs_badge][hacsbadge]][hacs] [![BuyMeCoffee][buymecoffeebadge]][buymecoffee] [![PayPal][paypalbadge]][paypal] [![hainstall][hainstallbadge]][hainstall]

---

###### Advertisement / Werbung

### Switch to Tibber!

Are you still customer of (IMHO totally overpriced) SENEC.Cloud as electricity provider? Be smart switch to Tibber - that's what I did in october 2023.

If you want to join Tibber (become a customer), you might want to use my personal invitation link. When you use this link, Tibber will we grant you and me a bonus of 50,-€ for each of us. This bonus then can be used in the Tibber store (not for your power bill) - e.g. to buy a Tibber Bridge. If you are already a Tibber customer and have not used an invitation link yet, you can also enter one afterward in the Tibber App (up to 14 days). [[see official Tibber support article](https://support.tibber.com/en/articles/4601431-tibber-referral-bonus#h_ae8df266c0)]

Please consider [using my personal Tibber invitation link to join Tibber today](https://invite.tibber.com/6o0kqvzf) or Enter the following code: 6o0kqvzf (six, oscar, zero, kilo, quebec, victor, zulu, foxtrot) afterward in the Tibber App - TIA!

---

## Setup / Installation

### Installation using HACS

- Install [Home Assistant Community Store (HACS)](https://hacs.xyz/)
- Add integration repository (search for "SENEC.Home" in "Explore & Download Repositories")
    - Select latest version or `master`
- Restart Home Assistant to install all dependencies

__If you only find__ the `Senec solar system sensor` integration (which will not work any longer!) - please add this repo as custom repository https://github.com/marq24/ha-senec-v3 to HACS

### Manual installation

- Copy all files from `custom_components/senec/` to `custom_components/senec/` inside your config Home Assistant directory.
- Restart Home Assistant to install all dependencies

## Adding or enabling the integration

### My Home Assistant (2021.3+)

Just click the following Button to start the configuration automatically:

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=senec)

### Manual

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

You can repeat this to add additional Integration entries (e.g. LAN + WebAPI)

<a id='inv-lnk'></a>

## Switching to this fork

If you used previously the source of this fork created by [@mchwalisz](https://github.com/mchwalisz), please look at "[Switching [to this] Fork](https://github.com/marq24/ha-senec-v3/issues/14)", before using this integration.

## Want to report an issue?

Please use the [GitHub Issues](https://github.com/marq24/ha-senec-v3/issues) for reporting any issues you encounter with this integration. Please be so kind before creating a new issues, check the closed ones, if your problem have been already reported (& solved). Furthermore, I would kindly ask you to check:

#### 1. Consider providing DEBUG Log output
There is a short [tutorial/guide 'How to provide DEBUG log' here](docs/HA_DEBUG.md) - please take the time to quickly go through it. [open link from external (HACS)](https://github.com/marq24/ha-senec-v3/blob/master/docs/HA_DEBUG.md)

#### 2. In case of implausible data 
It will happen, that the data that is displayed by this integration does not make much sense (to you) - Of course this could be always the case, that something in this integration has been messed up - but so far - in all reported issues the root cause of implausible data was/is, that the SENEC.Home device itself already provided this data. So we have the SHIT-__IN__ - SHIT-__OUT__ principle here.

So when you have implausible data - please open in the case of the local polling integration  `https://[YOUR-SENEC-IP-HERE]//vars.html` (the two `/` before the `vars.html` are important) and check, if the values are already implausible there. For the WebAPI integration, check the SENEC-App or use `https://mein-senec.de`.


## Functional Overview

### Supported Devices

The following devices are currently supported:

| Device                 | Description                                                                                                                                                                                                                                                                     |
|------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| SENEC.HOME&nbsp;V2.x   | You can use the features and sensors provided by your device via the local polling (via lala.cgi) and the Web API (via mein-senec.de)                                                                                                                                           | 
| SENEC.HOME&nbsp;V3     | You can use the features and sensors provided by your device via the local polling (via lala.cgi) and the Web API (via mein-senec.de)                                                                                                                                           | 
| SENEC.HOME&nbsp;V4     | Since the device does not provide local access via a build in webserver, you can just use the features and sensors provided via the Web API (via mein-senec.de).                                                                                                                | 
| SENEC.Inverter&nbsp;V3 | [When you have connected the internal inverter(s) with your LAN](#build-in-inverters), you will be able to access information via the Local API. Please see: "Connecting the internal (build in) SENEC Inverter Hardware to your LAN and use it in HA" for further information. | 

### Local Polling

The following features and sensors are provided by polling the build in webserver of your SENEC device: Since this is a long list, not everything is enabled by default.

To enable a disabled function or sensor navigate to Settings -> Devices and Services, select the integration and click "configuration" of the device. In the list you can see the status and have also the option to enable/disable them.

#### Features

The following features are provided by the local polling:

| Feature              | Description                                                                                                                                                                                                                                                                                                                                                                                   | enabled by default |
|----------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|--------------------|
| Load Battery         | With this switch you can load the battery manually                                                                                                                                                                                                                                                                                                                                            | yes                |
| Lithium Storage Mode | EXPERIMENTAL: Switch to enable 'storage mode' [state: LITHIUM SAFE MODE DONE'] [disabled by default]. The functionality of this switch is currently __not known__ - IMHO this will disable the functionality of the PV! __Please Note, that once enabled and then disable again the system will go into the 'INSULATION TEST' mode__ for a short while (before returning to normal operation) | no                 |
| Wallbox I-IV Control | Requires the additionally the WebAPI to be installed - [please see the separate section for details](#wb-control)                                                                                                                                                                                                                                                                             | no                 |

#### Sensors

The following Sensors are provided by the local polling:

<!-- You can find the [complete list with additional details in the SENSORS_DETAILS.md](docs/SENSORS_DETAILS.md) -->

| Sensor                                       | default entity name                                                                                   | enabled by default | remark                                                                                      |
|----------------------------------------------|-------------------------------------------------------------------------------------------------------|--------------------|---------------------------------------------------------------------------------------------|
| System State (translated to DE & IT)         | sensor.senec_system_state                                                                             | yes                |                                                                                             |
| Battery Temperature                          | sensor.senec_battery_temp                                                                             | yes                |                                                                                             |
| Case Temperature                             | sensor.senec_case_temp                                                                                | yes                |                                                                                             |
| Controller Temperature                       | sensor.senec_mcu_temp                                                                                 | yes                |                                                                                             |
| Solar Generated Power                        | sensor.senec_solar_generated_power                                                                    | yes                |                                                                                             |
| House Power                                  | sensor.senec_house_power                                                                              | yes                |                                                                                             |
| Battery State Power                          | sensor.senec_battery_state_power                                                                      | yes                |                                                                                             |
| Battery Charge Power                         | sensor.senec_battery_charge_power                                                                     | yes                |                                                                                             |
| Battery Discharge Power                      | sensor.senec_battery_discharge_power                                                                  | yes                |                                                                                             |
| Battery Charge Percent                       | sensor.senec_battery_charge_percent                                                                   | yes                |                                                                                             |
| Grid State Power                             | sensor.senec_grid_state_power                                                                         | yes                |                                                                                             |
| Grid Imported Power                          | sensor.senec_grid_imported_power                                                                      | yes                |                                                                                             |
| Grid Exported Power                          | sensor.senec_grid_exported_power                                                                      | yes                |                                                                                             |
| MPP1-MMP3 Voltage/Potential                  | sensor.senec_solar_mpp1_potential - sensor.senec_solar_mpp3_potential                                 | yes                |                                                                                             |
| MPP1-MMP3 Current                            | sensor.senec_solar_mpp1_current - sensor.senec_solar_mpp3_current                                     | yes                |                                                                                             |
| MPP1-MMP3 Power                              | sensor.senec_solar_mpp1_power - sensor.senec_solar_mpp3_power                                         | yes                |                                                                                             |
| Enfluri Net Frequency                        | sensor.senec_enfluri_net_freq                                                                         | yes                |                                                                                             |
| Enfluri Net Total Power                      | sensor.senec_enfluri_net_power_total                                                                  | yes                |                                                                                             |
| Enfluri Net Voltage/Potential Phase 1-3      | sensor.senec_enfluri_net_potential_p1 - sensor.senec_enfluri_net_potential_p3                         | yes                |                                                                                             |
| Enfluri Net Current Phase 1-3                | sensor.senec_enfluri_net_current_p1 - sensor.senec_enfluri_net_current_p3                             | yes                |                                                                                             |
| Enfluri Net Power Phase 1-3                  | sensor.senec_enfluri_net_power_p1 - sensor.senec_enfluri_net_power_p3                                 | yes                |                                                                                             |
| Enfluri Usage Frequency                      | sensor.senec_enfluri_usage_freq                                                                       | no                 |                                                                                             |
| Enfluri Usage Total Power                    | sensor.senec_enfluri_usage_power_total                                                                | no                 |                                                                                             |
| Enfluri Usage Voltage/Potential Phase 1-3    | sensor.senec_enfluri_usage_potential_p1 - sensor.senec_enfluri_usage_potential_p3                     | no                 |                                                                                             |
| Enfluri Usage Current Phase 1-3              | sensor.senec_enfluri_usage_current_p1 - sensor.senec_enfluri_usage_current_p3                         | no                 |                                                                                             |
| Enfluri Usage Power Phase 1-3                | sensor.senec_enfluri_usage_power_p1 - sensor.senec_enfluri_usage_power_p3                             | no                 |                                                                                             |
| Load Battery                                 | switch.senec_safe_charge                                                                              | yes                |                                                                                             |
| Lithium Storage Mode - PV OFF                | switch.senec_li_storage_mode                                                                          | no                 | current functionality is unknown yet                                                        |
| Battery Module A: Cell Temperature A1-A6     | sensor.senec_bms_cell_temp_a1 - sensor.senec_bms_cell_temp_a6                                         | no                 |                                                                                             |
| Battery Module B: Cell Temperature B1-B6     | sensor.senec_bms_cell_temp_b1 - sensor.senec_bms_cell_temp_b6                                         | no                 |                                                                                             |
| Battery Module C: Cell Temperature C1-C6     | sensor.senec_bms_cell_temp_c1 - sensor.senec_bms_cell_temp_c6                                         | no                 |                                                                                             |
| Battery Module D: Cell Temperature D1-D6     | sensor.senec_bms_cell_temp_d1 - sensor.senec_bms_cell_temp_d6                                         | no                 |                                                                                             |
| Battery Module A: Cell Voltage A1-A14        | sensor.senec_bms_cell_volt_a1 - sensor.senec_bms_cell_volt_a14                                        | no                 |                                                                                             |
| Battery Module B: Cell Voltage B1-B14        | sensor.senec_bms_cell_volt_b1 - sensor.senec_bms_cell_volt_a14                                        | no                 |                                                                                             |
| Battery Module C: Cell Voltage C1-C14        | sensor.senec_bms_cell_volt_c1 - sensor.senec_bms_cell_volt_a14                                        | no                 |                                                                                             |
| Battery Module D: Cell Voltage D1-D14        | sensor.senec_bms_cell_volt_d1 - sensor.senec_bms_cell_volt_d14                                        | no                 |                                                                                             |
| Battery Module A-D: Voltage                  | sensor.senec_bms_voltage_a - sensor.senec_bms_voltage_d                                               | no                 |                                                                                             |
| Battery Module A-D: Current                  | sensor.senec_bms_current_a - sensor.senec_bms_current_d                                               | no                 |                                                                                             |
| Battery Module A-D: State of Charge          | sensor.senec_bms_soc_a - sensor.senec_bms_soc_d                                                       | no                 |                                                                                             |
| Battery Module A-D: State of Health          | sensor.senec_bms_soh_a - sensor.senec_bms_soh_d                                                       | no                 |                                                                                             |
| Battery Module A-D: Cycles                   | sensor.senec_bms_cycles_a - sensor.senec_bms_cycles_d                                                 | no                 | values seams to be not plausible                                                            |
| Fan LV-Inverter                              | binary_sensor.senec_fan_inv_lv                                                                        | no                 | looks like that lala.cgi currently does not provide valid data                              |
| Fan HV-Inverter                              | binary_sensor.senec_fan_inv_hv                                                                        | no                 | looks like that lala.cgi currently does not provide valid data                              |
| House consumed                               | sensor.senec_house_total_consumption                                                                  | yes                | "temp" not available since SENEC has decided to remove statistics data from the lala.cgi    | 
| Solar generated                              | sensor.senec_solar_total_generated                                                                    | yes                | "temp" not available since SENEC has decided to remove statistics data from the lala.cgi    |
| Battery charged                              | sensor.senec_battery_total_charged                                                                    | yes                | "temp" not available since SENEC has decided to remove statistics data from the lala.cgi    |
| Battery discharged                           | sensor.senec_battery_total_discharged                                                                 | yes                | "temp" not available since SENEC has decided to remove statistics data from the lala.cgi    |
| Grid Imported                                | sensor.senec_grid_total_import                                                                        | yes                | "temp" not available since SENEC has decided to remove statistics data from the lala.cgi    |
| Grid Exported                                | sensor.senec_grid_total_export                                                                        | yes                | "temp" not available since SENEC has decided to remove statistics data from the lala.cgi    |
| Wallbox I-IV total charged                   | sensor.senec_wallbox_1_energy - sensor.senec_wallbox_4_energy                                         | no                 | "temp" not available since SENEC has decided to remove statistics data from the lala.cgi    |
| Wallbox (All) allow intercharge              | switch.wallbox_allow_intercharge                                                                      | no                 | requires additional WebAPI to be configured                                                 |
| Wallbox I-IV MODE (Locked/Fastest/Optimized) | select.senec_wallbox_1_mode - select.senec_wallbox_4_mode                                             | no                 | requires additional WebAPI to be configured                                                 |
| Wallbox I-IV State                           | sensor.senec_wallbox_1_state - select.senec_wallbox_1_state                                           | no                 |                                                                                             |
| Wallbox I-IV Power                           | sensor.senec_wallbox_1_power - sensor.senec_wallbox_4_power                                           | no                 |                                                                                             |
| Wallbox I-IV EV Connected                    | sensor.senec_wallbox_1_ev_connected - sensor.senec_wallbox_4_ev_connected                             | no                 |                                                                                             |
| Wallbox I-IV L1 charging Current             | sensor.senec_wallbox_1_l1_charging_current - sensor.senec_wallbox_4_l1_charging_current               | no                 |                                                                                             |
| Wallbox I-IV L2 charging Current             | sensor.senec_wallbox_1_l2_charging_current - sensor.senec_wallbox_4_l2_charging_current               | no                 |                                                                                             |
| Wallbox I-IV L3 charging Current             | sensor.senec_wallbox_1_l3_charging_current - sensor.senec_wallbox_4_l3_charging_current               | no                 |                                                                                             |
| Wallbox I-IV MIN charging Current            | sensor.senec_wallbox_1_min_charging_current - sensor.senec_wallbox_4_min_charging_current             | no                 |                                                                                             |
| Wallbox I-IV set ICMAX                       | number.senec_wallbox_1_set_icmax - number.senec_wallbox_4_set_icmax                                   | no                 | requires additional WebAPI to be configured - value can only be changed in mode 'optimized' |
| Wallbox I-IV Phase L1 used                   | binary_sensor.senec_wallbox_1_l1_used - binary_sensor.senec_wallbox_4_l1_used                         | no                 |                                                                                             |
| Wallbox I-IV Phase L2 used                   | binary_sensor.senec_wallbox_1_l2_used - binary_sensor.senec_wallbox_4_l2_used                         | no                 |                                                                                             |
| Wallbox I-IV Phase L3 used                   | binary_sensor.senec_wallbox_1_l3_used - binary_sensor.senec_wallbox_4_l3_used                         | no                 |                                                                                             |
| Wallbox I-IV Smart Charge active (by mode)   | binary_sensor.senec_wallbox_1_smart_charge_active - binary_sensor.senec_wallbox_4_smart_charge_active | no                 |                                                                                             |
| Wallbox I-IV is locked (by mode)             | binary_sensor.senec_wallbox_1_prohibit_usage - binary_sensor.senec_wallbox_4_prohibit_usage           | no                 |                                                                                             |
| Socket 1&2 already switched today            | binary_sensor.senec_sockets_1_already_switched & binary_sensor.senec_sockets_2_already_switched       | no                 |                                                                                             |
| Socket 1&2 power on                          | binary_sensor.senec_sockets_1_power_on & binary_sensor.senec_sockets_2_power_on                       | no                 |                                                                                             |
| Socket 1&2 permanent on                      | switch.senec_sockets_1_force_on & switch.senec_sockets_2_force_on                                     | no                 |                                                                                             |
| Socket 1&2 automatic enable                  | switch.senec_sockets_1_enable & switch.senec_sockets_2_enable                                         | no                 |                                                                                             |
| Socket 1&2 use timer                         | switch.senec_sockets_1_use_time & switch.senec_sockets_2_use_time                                     | no                 |                                                                                             |
| Socket 1&2 lower limit (W)                   | number.senec_sockets_1_lower_limit & number.senec_sockets_2_lower_limit                               | no                 |                                                                                             |
| Socket 1&2 upper limit (W)                   | number.senec_sockets_1_upper_limit & number.senec_sockets_2_upper_limit                               | no                 |                                                                                             |
| Socket 1&2 time limit                        | number.senec_sockets_1_time_limit & number.senec_sockets_2_time_limit                                 | no                 |                                                                                             |
| Socket 1&2 switch on hour                    | number.senec_sockets_1_switch_on_hour & number.senec_sockets_2_switch_on_hour                         | no                 |                                                                                             |
| Socket 1&2 switch on minute                  | number.senec_sockets_1_switch_on_minute & number.senec_sockets_2_switch_on_minute                     | no                 |                                                                                             |
| Socket 1&2 power on time (duration)          | number.senec_sockets_1_power_on_time & number.senec_sockets_2_power_on_time                           | no                 |                                                                                             |

### Web API

The following features and sensors are provided by the Web API Integration. Not all sensors are enabled by default. To enable a disabled function or sensor navigate to Settings -> Devices and Services, select the integration and click "configuration" of the device. In the list you can see the status and have also the option to enable/disable them.

#### Features

The following features are provided by the Web API:

| Feature                   | Description                                                                                                                                                                                                                                                                                                                           | enabled by default |
|---------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|--------------------|
| WEBAPI Spare Capacity     | Current spare capacity in percent with the option to update. Precondition: When you are using "SENEC Backup Power pro" and you are able to see and update the spare capacity at mein-senec.de, than you can read andupdate the spare capacity with this integration.                                                                  | no                 |
| Service: Set Peak Shaving | When using the Web API, you can use the Peak Shaving Service. This service gives you the abilty to switch the Mode (Deactivated, Automatic, Manual). In the manual mode you can define a battery capacity limit, so that the capacity can be used for charging later, as well as a end time - to realease the battery capacity limit. | yes                |

#### Sensors

The following Sensors are provided by the Web API:

| Sensor                             | Description                                                                                        | enabled by default |
|------------------------------------|----------------------------------------------------------------------------------------------------|--------------------|
| WEBAPI Battery Charge Percent      | Current charge level of Battery in percent                                                         | yes                |
| WEBAPI Battery Charge Power        | Current charge power of Battery                                                                    | yes                |
| WEBAPI Battery charged             | Total: Charged power in Battery - This information is needed for the energy dashboard              | yes                |
| WEBAPI Battery Discharge Power     | Current discharge power of Battery                                                                 | yes                |
| WEBAPI Battery discharged          | Total: Discharged power from Battery - This information is needed for the energy dashboard         | yes                |
| WEBAPI Grid Exported               | Total: Power exported to the grid - This information is needed for the energy dashboard            | yes                |
| WEBAPI Grid Exported Power         | Current power exporting to the grid                                                                | yes                |
| WEBAPI Grid Imported               | Total: Power imported from the grid - This information is needed for the energy dashboard          | yes                |
| WEBAPI Grid Imported Power         | Current power imported from the grid                                                               | yes                |
| WEBAPI House consumed              | Total: Amount of power consumed by the House - This information is needed for the energy dashboard | yes                |
| WEBAPI House Power                 | Current power used by the House                                                                    | yes                |
| WEBAPI Solar generated             | Total: Power generated by the Solar - This information is needed for the energy dashboard          | yes                |
| WEBAPI Solar Generated Power       | Current power generated by Solar                                                                   | yes                |
| WEBAPI Grid Exported Limit         | Grid Export Limit in Percent                                                                       | no                 |
| WEBAPI Peak Shaving Mode           | Shows the current Peak Shaving Mode (Deactivated, Automatic, Manual)                               | no                 |
| WEBAPI Peak Shaving Capacity Limit | When using the Manual Peak Shaving Mode this capacity limit will be used for your battery          | no                 |
| WEBAPI Peak Shaving End Time       | When using the Manual Peak Shaving Mode, this time releases the capacity limit for the battery     | no                 |

<a href="wb-control"/></a>

### Wallbox Control

Without this integration owners of a SENEC wallbox, __must__ use the SENEC mobile app in order to control the wallbox device. This 'remote-control-functionality' implies, that it takes a certain amount of time till a change in the mobile app will be synced with your local device. I was not aware of this 'delay'-situation (since I do not have a wallbox installed - and probably I will not get one from SENEC). At the end of December (2023) I was contacted by Sigurd L. and was asked, if it would be possible to support wallbox control with this SENEC.Home Integration.

The challenge for the integration is, that on the one hand it has to be ensured that the appropriate values in the local SENEC device will be set and make sure on the other hand that at the same time, that also the corresponding adjustments will be done in the SENEC Backend infrastructure (where the mobile app going to make the adjustments). And of course all that have to be done without any documentation and a really wired mix of parameter names - so please __use this functionality on your own risk!__.

When the Integration would adjust the wallbox setting in the local SENEC device __only__, then these changes will be reverted/overwritten after a short while with the data provided by the central SENEC backend. So this Home Assistant integration will set values in your local SENEC device as well as via the APP-API (web based) __simultaneously__ - so that the central SENEC backend and your local SENEC device are in sync.

Please Note: When you're going to adjust the Wallbox setting via the SENEC mobile app, your local SENEC device will still get synced with these adjustments after a short while (typically 5minutes). In such a case the values in the Home Assistant Integration will be also updated to your 'remote' adjustments.

#### Supported wallbox control features:

- Select the current Wallbox Mode: LOCKED / FASTEST / OPTIMIZED
- When Mode OPTIMIZED is active you can adjust the charging current (IC_MAX)
- When FASTEST is enabled you can switch 'allow intercharge' (use energy from your SENEC battery)

#### Setup requirements

When you want to control your wallbox via Home Assistant and this integration, you need to configure:

1. the __LAN__: `SENEC.Home V3 hybrid/SENEC.Home V3 hybrid duo` or `SENEC.Home V2.1 or older` __and__
2. also the __WebAPI__: `mein-senec.de Portal (usable with all SENEC.Home variants)`

__Only__ if both components are configured the Wallbox Control can work correctly!

---

# There is even more...

Here you will find additional information regarding setup and configuration.

<a href="build-in-inverters"/></a>

## Connecting the internal (build in) SENEC Inverter Hardware to your LAN and use it in HA

The __SENEC.Home V3 hybrid duo__ have build in two inverters - called LV and HV. This hardware has its own LAN connectors, but they have not been connected during the installation process (I guess by purpose).

### __DO THIS ON YOUR OWN RISK!__

Nevertheless, when you dismount the front and the right hand side panels you simply can plug in RJ45 LAN cables into both of the inverters LAN connectors and after a short while you should be able to access the web frontends of the inverters via your browser.

_Don't forget to assign fixed IP's to the additional inverter hardware. You can unplug the LAN cable for a short while in order to make sure that the inverters will make use of the fixed assigned IP's._

### Position of SENEC.Inverter V3 LV LAN connector

![img|160x90](images/inv_lv.png)
On the front of the device

### Position of SENEC.Inverter V3 HV LAN connector _(hybrid duo only!)_

![img|160x90](images/inv_hv.png)
On the right hand side of the device

### Adding Inverter(s) to your HA

Once you have connected the inverter(s) with your LAN you can add another integration entry to your SENEC Integration in Home Assistant:

1. go to '__Settings__' -> '__Devices & Services__'
2. select the '__SENEC.Home__' integration.
3. there you find the '__Add Entry__' button (at the bottom of the '__Integration entries__' list)
4. select `Internal inverter build into SENEC.Home V3 hybrid/hybrid duo` from the list
5. specify the IP (or hostname) of the inverter you want to add
6. __important:__ assign a name (e.g. _INV_LV_).

Repeat step 3, 4 & 5 of this procedure, if you have build in two inverters into your SENEC.Home.

## Home Assistant Energy Dashboard

This integration supports Home Assistant's [Energy Management](https://www.home-assistant.io/docs/energy/).
To use the Energy Dashboard please set up the Web API first.
In the description of the Web API you will see which sensors you can use for the Energy Dashboard.

Example setup:

![Energy Dashboard Setup](images/energy_dashboard.png)

Resulting energy distribution card:

![Energy Distribution](images/energy_distribution.png)

# Developer information

If you are interested in some details about this implementation and the current known fields you might like to take a look into the [current developer documentation section](docs/DEVELOPER_DOCUMENTATION.md).

# Credits / Kudos

| who| what                                                                                                                                                                                                                                                                                              |
|---|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
|[@marq24](https://github.com/marq24)| @marq24 created this fork, e.g. added several sensors and functions and is maintaining the integration.                                                                                                                                                                                           |
|[@mstuettgen](https://github.com/mstuettgen)| Provided the initial WEB-API implementation for SENEC.Home V4 web access.                                                                                                                                                                                                                         |
|[@io-debug](https://github.com/io-debug)| Provided the initial developer documentation and added functionality like the spare capacity management.                                                                                                                                                                                          |
|[@mchwalisz](https://github.com/mchwalisz)| This fork was created from [mchwalisz/home-assistant-senec](https://github.com/mchwalisz/home-assistant-senec)<br/>After some firmware updates in 2023 (by SENEC) this original integration simply does not work any longer - plus: we needed more detailed information and configuration options |

[hacs]: https://github.com/hacs/integration
[hacsbadge]: https://img.shields.io/badge/HACS-Default-blue.svg?style=for-the-badge&logo=homeassistantcommunitystore&logoColor=ccc

[buymecoffee]: https://www.buymeacoffee.com/marquardt24
[buymecoffeebadge]: https://img.shields.io/badge/buy%20me%20a-coffee-blue.svg?style=for-the-badge&logo=buymeacoffee&logoColor=ccc

[paypal]: https://paypal.me/marq24
[paypalbadge]: https://img.shields.io/badge/paypal-me-blue.svg?style=for-the-badge&logo=paypal&logoColor=ccc

[hainstall]: https://my.home-assistant.io/redirect/config_flow_start/?domain=senec
[hainstallbadge]: https://img.shields.io/badge/dynamic/json?style=for-the-badge&logo=home-assistant&logoColor=ccc&label=usage&suffix=%20installs&cacheSeconds=15600&url=https://analytics.home-assistant.io/custom_integrations.json&query=$.senec.total