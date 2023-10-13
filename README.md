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
