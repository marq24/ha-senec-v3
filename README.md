# Home Assistant sensor for SENEC.Home V3 
This fork was created from [mchwalisz/home-assistant-senec](https://gitgub.com/mchwalisz/home-assistant-senec) mainly
because I wanted additional fields and some configuration options (like polling interval). Since I own a
__SENEC.Home V3 hybrid duo__ I can __only test my adjustments in such a configuration__.

__Use this fork on your own risk!__

## Modifications (compared to the original Fork)
- Added User accessible configuration option
- Added _update interval_ to the configuration (I use here locally _5_ seconds without any issues)
- Integrated variant of _pysenec_ python lib (almost every modification of this Home Assistant integration requires also
  an adjustment in the lib) - yes of course it would be possible to release also a lib derivative - but right now I am
  just a python beginner, and __I am lazy!__
- Added three additional sensors for each MPP1, MPP2, MPP3 (potential, current & power)
- Modified _battery_charge_power_ & _battery_discharge_power_ so that they will only return data >0 when the system
  state is matching the CHARGE & DISCHARGE (& variants) state
- Added German "translation"

## Installation

### Hacs

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)

- Install [Home Assistant Community Store (HACS)](https://hacs.xyz/)
- Add custom repository https://github.com/marq24/ha-senec-v3 to HACS
- Add integration repository (search for "Senec" in "Explore & Download Repositories")
    - Select latest version or `master`
- Restart Home Assistant to install all dependencies

### Manual

- Copy all files from `custom_components/senec/` to `custom_components/senec/` inside your config Home Assistant directory.
- Restart Home Assistant to install all dependencies

### Adding or enabling integration
#### My Home Assistant (2021.3+)
[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=senec)

#### Manual
Add custom integration using the web interface and follow instruction on screen.

- Go to `Configuration -> Integrations` and add "Senec" integration
- Provide name for the device and it's address (hostname or IP)
- Provide area where the battery is located

## Home Assistant Energy Dashboard

This integration supports Home Assistant's [Energy Management](https://www.home-assistant.io/docs/energy/)

Example setup:

![Energy Dashboard Setup](images/energy_dashboard.png)

Resulting energy distribution card:

![Energy Distribution](images/energy_distribution.png)
