# Development Documentation
This document should give an overview regarding the used APIs and the possible data that can be queried.

## Data that can be accessed in the local network from a Senec V3 device 
Basis for this documentation is the firmware version 0826.

The following information are provided by the device. Since no open acceccible API documentation exists, the following description is an assumption. 
- The following information can be accessed sending a post request with a JSON-Payload to https://[IP of the senec device]/lala.cgi
- As response a JSON String is returned
- Please note: Depending on the firmware version the Request has to be via http or https. (https starting with the firmware version 825)

### Logfile
The logfile of the device can be accessed via URL and shows a raw text file.
The URL has the following format: `https://[IP of the device]//log/[year]/[month]/[day].log` (and __YES__ there are two
`/` behind the ip-address since v0826)

Example: https://192.168.1.115//log/2023/10/05.log

### VarMon & Chart
It is possible to get a list of all variables and their values of the device, even if Senec claimed that this data is
only accessible by themselves (since 0826) - the access is still possible for every owner without any kind of hacks.

| version      | url                                     |
|--------------|-----------------------------------------|
| before v0825 | `https://[IP of the device]/vars.html`  |
| v0825        | `https://[IP of the device]/Vars.html`  |
| v0826        | `https://[IP of the device]//vars.html` |

Example: https://192.168.1.115//vars.html

### lala.cgi Request Example
To gather data we have to send a POST-Request to the Senec device ("lala.cgi"), that has a JSON-String as payload.
Here an request example with all objects that can be requested. Many of the objects have sub-objects:
```
POST https://[my-ip]/lala.cgi HTTP/1.1
content-type: application/json

{
"DEBUG":{},
"BAT1":{},
"BAT1OBJ1":{},
"BMS":{},
"BMS_PARA":{},
"CASC":{},
"DISPLAY":{},
"ENERGY":{},
"FACTORY":{},
"FEATURES":{},
"FILE":{},
"GRIDCONFIG":{},
"LOG":{},
"PM1":{},
"PM1OBJ1":{},
"PM1OBJ2":{},
"PV1":{},
"PWR_UNIT":{},
"RTC":{},
"SELFTEST_RESULTS":{},
"SOCKETS":{},
"STATISTIC":{},
"STECA":{},
"SYS_UPDATE":{},
"TEMPMEASURE":{},
"TEST":{},
"UPDATE":{},
"WALLBOX":{},
"WIZARD":{},
"CURRENT_IMBALANCE_CONTROL":{},
"BMZ_CURRENT_LIMITS":{},
"CELL_DEVIATION_ROC":{},
"SENEC_IO_INPUT":{},
"SENEC_IO_OUTPUT":{},
"IPU":{},
"FAN_TEST":{},
"FAN_SPEED":{}
}
```

### Response Example
The response returns a JSON-String for the requested object.
In this example the "ENERGY" was used.
The values are in hex format and have to be decoded in dec, int or float.
```
{
    "ENERGY": {
        "STAT_STATE": "u8_0D",
        "GUI_BAT_DATA_POWER": "fl_BF08E2C1",
        "GUI_INVERTER_POWER": "fl_4599AD17",
        "GUI_HOUSE_POW": "fl_442047C0",
        "GUI_GRID_POW": "fl_C585A866",
        "GUI_BAT_DATA_FUEL_CHARGE": "fl_428C0000",
        "GUI_CHARGING_INFO": "u8_00",
        "GUI_BOOSTING_INFO": "u8_00"
    }
}
```

### Category DEBUG
Information from the DEBUG-Object:

|Object|Example value|Description|
|------|-------------|-----------|
|CHARGE_TARGET||
|DC_TARGET||
|FEED_TARGET||
|PU_AVAIL||
|SECTIONS|Assumption: Could be a (not complete) list of objects that contain data.|

### Category "ENERGY"
Information from the ENERGY-Object:

|Object|Example value|Description|
|------|-------------|-----------|
|CAPTESTMODULE|[0.0, 0.0, 0.0, 0.0 ]||
|GUI_BAT_DATA_COLLECTED|1||
|GUI_BAT_DATA_CURRENT|-6.849999904632568||
|GUI_BAT_DATA_FUEL_CHARGE|82.82827758789062|Battery fuel charge in percent, as shown in the gui, wenn accessing the device via browser.|
|GUI_BAT_DATA_MAX_CELL_VOLTAGE|3929|||
|GUI_BAT_DATA_MIN_CELL_VOLTAGE|3923|||
|GUI_BAT_DATA_POWER|-376.57867431640625|Positive: Watt with which the battery is charged; Negative: Watts with which the battery is discharged|
|GUI_BAT_DATA_VOLTAGE|54.974998474121094||
|GUI_BOOSTING_INFO|1||
|GUI_CAP_TEST_STATE|0||
|GUI_CHARGING_INFO|0||
|GUI_GRID_POW|-6.079999923706055|A positive value corresponds to a mains reference, a negative value to a net feed-in. This is the same data shown in the gui, when accessing the device via browser. |
|GUI_HOUSE_POW|370.4986877441406||
|GUI_INIT_CHARGE_START|0||
|GUI_INIT_CHARGE_STOP|0||
|GUI_INVERTER_POWER|-0.0|Sum of currently generated PV electricity in watts|
|GUI_TEST_CHARGE_STAT|0||
|GUI_TEST_DISCHARGE_STAT|0||
|INIT_CHARGE_ACK|0||
|INIT_CHARGE_DIFF_VOLTAGE|0.0||
|INIT_CHARGE_MAX_CURRENT|0.0||
|INIT_CHARGE_MAX_VOLTAGE|0.0||
|INIT_CHARGE_MIN_VOLTAGE|0.0||
|INIT_CHARGE_RERUN|0||
|INIT_CHARGE_RUNNING|0||
|INIT_CHARGE_STATE|0||
|INIT_CHARGE_TIMER|0||
|INIT_DISCHARGE_MAX_CURRENT|0.0||
|LI_STORAGE_MODE_RUNNING|0||
|LI_STORAGE_MODE_START|0||
|LI_STORAGE_MODE_STOP|0||
|OFFPEAK_DURATION|0||
|OFFPEAK_POWER|0.0||
|OFFPEAK_RUNNING|0||
|OFFPEAK_TARGET|100||
|SAFE_CHARGE_FORCE|0||
|SAFE_CHARGE_PROHIBIT|0||
|SAFE_CHARGE_RUNNING|0||
|STAT_HOURS_OF_OPERATION|9993|Number of hours since the system was activated|
|STAT_LIMITED_NET_SKEW|0||
|STAT_STATE|16|Status of the system, see detailed definition in section "Translation of System State Name Enums to Text" |
|VPP_ACTIVATE_EXPORT_LIMIT|0||
|VPP_ACTIVATE_TARGET_POWER|0||
|VPP_DAILY_PARAMETER_RESET|1||
|VPP_ENDTIME_HOUR|0||
|VPP_ENDTIME_MINUTE|0||
|VPP_EXPORT_LIMIT|0||
|VPP_IGNORE_COUNTRY_TYPE|0||
|VPP_IS_ACTIVE|0||
|VPP_LAST_CHANGE_UTC|0||
|VPP_STARTTIME_HOUR|0||
|VPP_STARTTIME_MINUTE|0||
|VPP_TARGET_POWER|0.0||
|ZERO_EXPORT|0||

#### Translation of ENERGY STAT_STATE Name ENUMS to Text
Representations of STAT_STATE

|ENUM|Description|
|----|-----------|
|0|INITIALZUSTAND|
|1|KEINE KOMMUNIKATION LADEGERAET|
|2|FEHLER LEISTUNGSMESSGERAET|
|3|RUNDSTEUEREMPFAENGER|
|4|ERSTLADUNG|
|5|WARTUNGSLADUNG|
|6|WARTUNGSLADUNG FERTIG|
|7|WARTUNG NOTWENDIG|
|8|MAN. SICHERHEITSLADUNG|
|9|SICHERHEITSLADUNG FERTIG|
|10|VOLLLADUNG|
|11|AUSGLEICHSLADUNG: LADEN|
|12|SULFATLADUNG: LADEN|
|13|AKKU VOLL|
|14|LADEN|
|15|AKKU LEER|
|16|ENTLADEN|
|17|PV + ENTLADEN|
|18|NETZ + ENTLADEN|
|19|PASSIV|
|20|AUSGESCHALTET|
|21|EIGENVERBRAUCH|
|22|NEUSTART|
|23|MAN. AUSGLEICHSLADUNG: LADEN|
|24|MAN. SULFATLADUNG: LADEN|
|25|SICHERHEITSLADUNG|
|26|AKKU-SCHUTZBETRIEB|
|27|EG FEHLER|
|28|EG LADEN|
|29|EG ENTLADEN|
|30|EG PASSIV|
|31|EG LADEN VERBOTEN|
|32|EG ENTLADEN VERBOTEN|
|33|NOTLADUNG|
|34|SOFTWAREAKTUALISIERUNG|
|35|FEHLER: NA-SCHUTZ|
|36|FEHLER: NA-SCHUTZ NETZ|
|37|FEHLER: NA-SCHUTZ HARDWARE|
|38|KEINE SERVERVERBINDUNG|
|39|BMS FEHLER|
|40|WARTUNG: FILTER|
|41|ABSCHALTUNG LITHIUM|
|42|WARTE AUF ÜBERSCHUSS|
|43|KAPAZITÄTSTEST: LADEN|
|44|KAPAZITÄTSTEST: ENTLADEN|
|45|MAN. SULFATLADUNG: WARTEN|
|46|MAN. SULFATLADUNG: FERTIG|
|47|MAN. SULFATLADUNG: FEHLER|
|48|AUSGLEICHSLADUNG: WARTEN|
|49|NOTLADUNG: FEHLER|
|50|MAN: AUSGLEICHSLADUNG: WARTEN|
|51|MAN: AUSGLEICHSLADUNG: FEHLER|
|52|MAN: AUSGLEICHSLADUNG: FERTIG|
|53|AUTO: SULFATLADUNG: WARTEN|
|54|LADESCHLUSSPHASE|
|55|BATTERIETRENNSCHALTER AUS|
|56|PEAK-SHAVING: WARTEN|
|57|FEHLER LADEGERAET|
|58|NPU-FEHLER|
|59|BMS OFFLINE|
|60|WARTUNGSLADUNG FEHLER|
|61|MAN. SICHERHEITSLADUNG FEHLER|
|62|SICHERHEITSLADUNG FEHLER|
|63|KEINE MASTERVERBINDUNG|
|64|LITHIUM SICHERHEITSMODUS AKTIV|
|65|LITHIUM SICHERHEITSMODUS BEENDET|
|66|FEHLER BATTERIESPANNUNG|
|67|BMS DC AUSGESCHALTET|
|68|NETZINITIALISIERUNG|
|69|NETZSTABILISIERUNG|
|70|FERNABSCHALTUNG|
|71|OFFPEAK-LADEN|
|72|FEHLER HALBBRÜCKE|
|73|BMS: FEHLER BETRIEBSTEMPERATUR|
|74|FACTORY SETTINGS NICHT GEFUNDEN|
|75|NETZERSATZBETRIEB|
|76|NETZERSATZBETRIEB AKKU LEER|
|77|NETZERSATZBETRIEB FEHLER|
|78|INITIALISIERUNG|
|79|INSTALLATIONSMODUS|
|80|NETZAUSFALL|
|81|BMS UPDATE ERFORDERLICH|
|82|BMS KONFIGURATION ERFORDERLICH|
|83|ISOLATIONSTEST|
|84|SELBSTTEST|
|85|EXTERNE STEUERUNG|
|86|TEMPERATUR SENSOR FEHLER|
|87|NETZBETREIBER: LADEN GESPERRT|
|88|NETZBETREIBER: ENTLADEN GESPERRT|
|89|RESERVEKAPAZITÄT|
|90|SELBSTTEST FEHLER|
|91|ISOLATIONSFEHLER|
|92|PV-MODUS|
|93|FERNABSCHALTUNG NETZBETREIBER|
|94|FEHLER DRM0|
|95|BATTERIEDIAGNOSE|
|96|BALANCING|
|97|SICHERHEITSENTLADUNG|
|98|BMS FEHLER - MODULUNGLEICHGEWICHT|

### Category FEATURES
Features of Senec device, represented in the FEATURES-Object:
|Object|Example value|Description|
|------|-------------|-----------|
|CAR|1|installation of wallbox possible?|
|CLOUDREADY|1||
|ECOGRIDREADY|1||
|HEAT|1|Connection to heat module like asko heat possible?|
|ISLAND|1|module backup power installed?|
|ISLAND_PRO|1|module backup power pro installed?|
|PEAKSHAVING|1|peak shaving is possible|
|SGREADY|1|Smart grid ready|
|SHKW|0||
|SOCKETS|0||

### Category FILE
Returns an empty object

### Category LOG
Information represented bei the LOG-Object:
|Object|Example value|Description|
|------|-------------|-----------|
|LOG_IN_BUTT|0||
|LOG_IN_NOK_COUNT|0|Number of wrong login attempts|
|LOG_OUT_BUTT|0||
|PASSWORD|||||
|USERNAME|||||
|USER_LEVEL|0||


### Category DISPLAYSYS_UPDATE
Unknown, what the DISPLYSYS-Object represents:

   "DISPLAYSYS_UPDATE":{
      "OBJECT_NOT_FOUND":""
   },

### Category WIZARD
Information represented by the WIZARD-Object:
|Object|Example value|Description|
|------|-------------|-----------|
|APPLICATION_HASH|05feefa49abec4a123f6883386a48497562caa8|||
|APPLICATION_VERSION|1824|||
|BATT_IPU_MISMATCH|0||
|BOOT|1||
|CHARGE_PRIO|0||
|CONFIG_CHECKSUM|40231||
|CONFIG_LOADED|1||
|CONFIG_MODIFIED_BY_USER|0||
|CONFIG_WRITE|0||
|DEVICE_BATTERY_TYPE|4||
|DEVICE_INVERTER_TYPE|66|Model of the inverter.|
|DEVICE_INV_ENABLED|[1, 0, 0, 0, 0, 0]||
|DEVICE_INV_PHASES_ARR|[4, 4, 4, 4, 4, 4]||
|DEVICE_INV_SLAVE_ADRESS|[1, 4, 5, 6, 7, 8]||
|DEVICE_PM_GRID_ENABLED|1||
|DEVICE_PM_HOUSE_ENABLED|0||
|DEVICE_PM_TYPE|1||
|DEVICE_WB_TYPE|0||
|FEATURECODE_ENTERED|0||
|FIRMWARE_VERSION|954|Version of the firmware|
|GENERATION_METER_SN|0||
|GRID_CONNECTION_TYPE|2||
|GUI_LANG|0||
|HEATPUMP_METER_SN|0||
|HEAT_CONN_TYPE|2||
|INSULATION_RESISTANCE|1000||
|INTERFACE_VERSION|1964||
|LOGGER_SEVERITY|8||
|MAC_ADDRESS_BYTES|[10, 21, 246, 11, 222, 116]||
|MASTER_SLAVE_ADDRESSES|[0, 0, 0, 0, 0, 0]||
|MASTER_SLAVE_MODE|0||
|POWER_METER_SERIAL|0||
|PS_ENABLE|0||
|PS_HOUR|0||
|PS_MINUTE|0||
|PS_RESERVOIR|0||
|PV_CONFIG|[1, 1]||
|PWRCFG_PEAK_PV_POWER|9500.0|Max. PV power of system in watts|
|SENEC_METER_SN|0||
|SETUP_ABS_POWER|0||
|SETUP_HV_PHASE|0||
|SETUP_NUMBER_WALLBOXES|0||
|SETUP_PM_GRID_ADR|1||
|SETUP_PM_HOUSE_ADR|2||
|SETUP_POWER_RULE|100||
|SETUP_PV_INV_IP0|0||
|SETUP_PV_INV_IP1|0||
|SETUP_PV_INV_IP2|0||
|SETUP_PV_INV_IP3|0||
|SETUP_PV_INV_IP4|0||
|SETUP_PV_INV_IP5|0||
|SETUP_RCR_STEPS|[0, 30, 60, 100]||
|SETUP_USED_PHASE|1||
|SETUP_USE_ABS_POWER|0||
|SETUP_USE_DRM0|0||
|SETUP_USE_RCR|0||
|SETUP_WALLBOX_SERIAL0|||||
|SETUP_WALLBOX_SERIAL1|||||
|SETUP_WALLBOX_SERIAL2|||||
|SETUP_WALLBOX_SERIAL3|||||
|SG_READY_CURR_MODE|1||
|SG_READY_ENABLED|0||
|SG_READY_ENABLE_OVERWRITE|0||
|SG_READY_EN_MODE1|0||
|SG_READY_OVERWRITE_RELAY|[0, 0]||
|SG_READY_POWER_COMM|65535||
|SG_READY_POWER_PROP|65535||
|SG_READY_TIME|720||
|TEST_EG_METER|0||
|TEST_GENERATION_METER|0||
|TEST_HEATPUMP_METER|0||
|TEST_SENEC_METER|0||
|ZEROMODULE|0||

### Category BMS
Information represented by the BMS-Object:
|Object|Example value|Description|
|------|-------------|-----------|
|ALARM_STATUS|[0, 0, 0, 0]||
|BATTERY_STATUS|[0, 0, 0, 0]||
|BL|[12480, 12480, 12480, 0]||
|BMS_READY_FLAG|1||
|BMS_STATUS|1||
|BMS_STATUS_TIMESTAMP|1689953960||
|CELL_BALANCE_STATUS|[0, 0, 0, 0]||
|CELL_TEMPERATURES_MODULE_A|[30, 30, 31, 30, 31, 31]|Temperature of the battery cells of module A. For each cell a sensor is set up.|
|CELL_TEMPERATURES_MODULE_B|[30, 30, 31, 31, 31, 31]|Temperature of the battery cells of module B. For each cell a sensor is set up.|
|CELL_TEMPERATURES_MODULE_C|[31, 31, 32, 32, 32, 32]|Temperature of the battery cells of module C. For each cell a sensor is set up.|
|CELL_TEMPERATURES_MODULE_D|[0, 0, 0, 0, 0, 0]|Temperature of the battery cells of module D. For each cell a sensor is set up.|
|CELL_VOLTAGES_MODULE_A|[3926, 3926, 3926, 3926, 3926, 3926, 3925, 3923, 3926, 3926, 3926, 3927, 3926, 3927]||
|CELL_VOLTAGES_MODULE_B|[3928, 3926, 3926, 3926, 3926, 3927, 3926, 3923, 3927, 3926, 3927, 3927, 3927, 3928]||
|CELL_VOLTAGES_MODULE_C|[3929, 3929, 3928, 3928, 3928, 3929, 3928, 3926, 3928, 3928, 3928, 3928, 3928, 3929]||
|CELL_VOLTAGES_MODULE_D|[0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]||
|CHARGED_ENERGY|[60293836, 307496975, 267112777, 0]||
|CHARGE_CURRENT_LIMIT|[12.0, 12.0, 12.0, 0.0]||
|COMMERRCOUNT|0||
|CURRENT|[-2.2799999713897705, -2.2899999618530273, -2.2799999713897705, 0.0]||
|CYCLES|[27, 29, 14, 0]|Assumption: Number of charging cycles per module|
|DERATING|0||
|DISCHARGED_ENERGY|[290682267, 291850974, 30869157, 0]||
|DISCHARGE_CURRENT_LIMIT|[-24.0, -24.0, -24.0, 0.0]||
|ERROR|0||
|FAULTLINECOUNT|2||
|FW|[39637, 39637, 39637, 0]||
|HW_EXTENSION|[2, 2, 2, 0]||
|HW_MAINBOARD|[3002, 3002, 3002,0]||
|MANUFACTURER|2||
|MAX_CELL_VOLTAGE|[3927, 3928, 3929, 0]||
|MAX_TEMP|320||
|MIN_CELL_VOLTAGE|[3923, 3923, 3926, 0]||
|MIN_TEMP|300||
|MODULES_CONFIGURED|3|Number of configured modules|
|MODULE_COUNT|3|Number of battery modules|
|NOM_CHARGEPOWER_MODULE|625.0|Nominal charging power for each module|
|NOM_DISCHARGEPOWER_MODULE|1250.0|Nominal discharge power for each module|
|NR_INSTALLED|3|Number of installed batteries|
|PROTOCOL|0||
|RECOVERLOCKED|0||
|SERIAL|["", "", "", ""]||
|SN|[44043416, 44043417, 44043418, 0]||
|SOC|[83, 83, 83, 0]||
|SOH|[99, 99, 99, 0]||
|STATUS|[1, 1, 1, 0]||
|SYSTEM_SOC|830||
|TEMP_MAX|[31, 31, 32, 0]||
|TEMP_MIN|[30, 30, 31, 0]||
|TF_ERROR|0||
|VOLTAGE|[54.96200180053711, 54.970001220703125, 54.99399948120117, 0.0]||
|WIZARD_ABORT|1||
|WIZARD_CONFIRM|0||
|WIZARD_DCCONNECT|0||
|WIZARD_START|0||
|WIZARD_STATE|0||

#### Translation of the BMS_STATUS ENUMS
|ENUM|Description|
|---|---|
| 1 | Warning: cell overvoltage |
| 2 | Alarm: cell overvoltage |
| 3 | Error: cell overvoltage |
| 4 | Warning: cell undervoltage |
| 5 | Alarm: cell undervoltage |
| 6 | Error: cell undervoltage |
| 7 | Alarm: module overvoltage |
| 8 | Alarm: module undervoltage |
| 9 | Error: cell overtemperature |
| 10 | Error: cell undertemperature |
| 11 | Warning: cell overtemperature charging |
| 12 | Alarm: cell overtemperature charging |
| 13 | Warning: cell undertemperature charging |
| 14 | Alarm: cell undertemperature charging |
| 15 | Warning: cell overtemperature discharging |
| 16 | Alarm: cell overtemperature discharging |
| 17 | Warning: cell undertemperature discharging |
| 18 | Alarm: cell undertemperature discharging |
| 19 | Warning: charging current |
| 20 | Alarm: charging current |
| 21 | Warning: discharging current |
| 22 | Alarm: discharging current |
| 23 | Warning: cells imbalanced |
| 24 | Alarm: cells imbalanced |
| 25 | Warning: board temperature too high |
| 26 | Alarm: board temperature too high |
| 27 | Warning: checking temperature difference |
| 28 | Alarm: checking temperature difference |
| 29 | Warning: checking current difference |
| 30 | Alarm: checking current difference |
| 31 | Selftest SCP failed |

### Category BAT1
Information represented by the BAT1-Object:
|Object|Example value|Description|
|------|-------------|-----------|
|CEI_LIMIT|0||
|DRM0_ASSERT|0||
|ISLAND_ENABLE|1|Assumption: Is the emergency power available?|
|NSP2_FW|6||
|NSP_FW|10||
|RESET|0||
|SELFTEST_ACT|[0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]||
|SELFTEST_LIMIT|[0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]||
|SELFTEST_OFF|[0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]||
|SELFTEST_OVERALL_STATE|5||
|SELFTEST_STATE|[0, 0, 0, 0, 0, 0, 0, 0]||
|SELFTEST_STEP|["", "", "", "", "", "", "", ""]||
|SELFTEST_TIME|[0, 0, 0, 0, 0, 0, 0, 0]||
|SERIAL|"783234JD028547840519"||
|SPARE_CAPACITY|15|Set reserve capacity for emergency power supply|
|TRIG_ITALY_SELF|0||
|TYPE|4|Battery type|

#### Translation of the Selftest result ENUMs
|ENUM|Description|
|---|---|
|0|Undefined|
|1|Running|
|2|Success|
|3|Failed|
|4|Never Runned|
|5|Not Started|

#### Translation of the Selftest step ENUMs
|ENUM|Description|
|---|---|
| 0 | Upper Voltage Limit L1 |
| 1 | Lower Voltage Limit L1 |
| 2 | Upper Freq Limit L1 |
| 3 | Lower Freq Limit L1 |
| 4 | Upper 10 Min Avg Limit L1 |
| 5 | Ext Upper Freq Limit L1 |
| 6 | Ext Lower Freq Limit L1 |
| 7 | Lower Voltage Limit 2 L1 |

### Category BAT1OBJ1
Information represented by the BAT1OBJ1-Object:
|Object|Example value|Description|
|------|-------------|-----------|
|COMM|0||
|I_DC|-6.744999885559082||
|P|0||
|Q|0||
|S|0||
|SW_VERSION|51380244||
|SW_VERSION2|67305482||
|SW_VERSION3|84148230||
|TEMP1|42||
|TEMP2|49||
|TEMP3|0||
|TEMP4|0||
|TEMP5|0||
|U_DC|54.85300064086914||
  
  ### Category BAT1OBJ2
  Information represented by the BAT1OBJ2-Object:
   "BAT1OBJ2":{
      "OBJECT_NOT_FOUND":""
   },
  
  ### Category BAT1OBJ3
  Information represented by the BAT1OBJ3-Object:
   "BAT1OBJ3":{
      "OBJECT_NOT_FOUND":""
   },
### Category BAT1OBJ4
Information represented by the BAT1OBJ4-Object:
   "BAT1OBJ4":{
      "OBJECT_NOT_FOUND":""
   },

### Category PWR_UNIT
Information represented by the PWR_UNIT-Object:
|Object|Example value|Description|
|------|-------------|-----------|
|ADRESS|[0, 0, 0, 0, 0, 0]||
|CONNPWR|[0.0, 0.0, 0.0, 0.0, 0.0, 0.0]||
|CONNPWR_1|[0.0, 0.0, 0.0, 0.0, 0.0, 0.0]||
|CONNPWR_2|[ 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]||
|CONNPWR_3|[0.0, 0.0, 0.0, 0.0, 0.0, 0.0]||
|CURRENTTEMP_MAX|[0.0, 0.0, 0.0, 0.0, 0.0, 0.0]||
|CURRENTTEMP_MAX_HW|[ 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]||
|CURRENTTEMP_MIN|[0.0, 0.0, 0.0, 0.0, 0.0, 0.0]||
|CURRENTTEMP_MIN_HW|[0.0, 0.0, 0.0, 0.0, 0.0, 0.0]||
|ENFLURI|[0, 0, 0, 0, 0, 0]||
|FW_VER|[0, 0, 0, 0, 0, 0]||
|HW_REV|[0, 0, 0, 0, 0, 0]||
|POWER|[0.0, 0.0, 0.0, 0.0, 0.0, 0.0]||
|POWER_L1|[0.0, 0.0, 0.0, 0.0, 0.0, 0.0]||
|POWER_L2|[ 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]||
|POWER_L3|[0.0, 0.0, 0.0, 0.0, 0.0, 0.0]||
|PU_MISSING|0||
|REQ_POWER|[0.0, 0.0, 0.0, 0.0, 0.0, 0.0]||
|SERIAL|["", "", "", "", "", ""]||
|STATUS|[0, 1, 2, 3, 4, 5]||
|TEMPMAX|[0.0, 0.0, 0.0, 0.0, 0.0, 0.0]||
|TEMPMIN|[0.0, 0.0, 0.0, 0.0, 0.0, 0.0]||
|TEMPTARGET|[0.0, 0.0, 0.0, 0.0, 0.0, 0.0]||
|TEMP_COUNT|[0, 0, 0, 0, 0, 0]||
|TEMP_LIMIT_LOWER|0.0||
|TEMP_LIMIT_UPPER|100.0||
|TYPE|[0, 0, 0, 0, 0, 0]||
|WATERVOL|[0, 0, 0, 0, 0, 0]||

#### Translation of the PWR_UNIT TYPE ENUM
| ENUM | Description |
|---|---|
| 0 | N/A |
| 1 | Solarinvert SHKW |
| 2 | SENEC.Heat |

### Category PV1
Information represented by the PV1-Object:
|Object|Example value|Description|
|------|-------------|-----------|
|ERROR_STATE_INT|[0, 0]||
|INTERNAL_INV_ERROR_TEXT|["", ""]||
|INTERNAL_INV_ERR_STATE_VALID|[1, 0]||
|INTERNAL_INV_STATE|[2, 5]||
|INTERNAL_MD_AVAIL|[1, 0]||
|INTERNAL_MD_MANUFACTURER|["Senec", ""]|Manufacturer|
|INTERNAL_MD_MODEL|["V3 LV", ""]|Currently used model|
|INTERNAL_MD_SERIAL|["7a7553H304H544250424", ""]||
|INTERNAL_MD_VERSION|["HMI: 3.16.20 PU: 4.3.10 BDC: 5.4.6", ""]||
|INTERNAL_PV_AVAIL|1||
|INV_MODEL|["", "", "st_END_OF_ARRAY"]||
|INV_SERIAL|["", "","st_END_OF_ARRAY"]||
|INV_VERSIONS|["HMI: 3.16.20 PU: 4.3.10", "","st_END_OF_ARRAY"]||
|MPP_AVAIL|2|Number of available MPPs|
|MPP_CUR|[0.0, 0.0, 0.0]||
|MPP_POWER|[0.0, 0.0, 0.0]|Power for each MPP in watts. For each MPP a sensor is set up.|
|MPP_VOL|[60.202003479003906, 66.80500030517578, 0.0]|Voltage of each MPP|
|POWER_RATIO|100.0||
|POWER_RATIO_L1|100.0||
|POWER_RATIO_L2|100.0||
|POWER_RATIO_L3|100.0||
|PV_MISSING|0||
|P_TOTAL|0.0||
|STATE_INT|[272, 0]||
|TYPE|66||


### Category BMS_PARA
Information represented by the BMS_PARA-Object:
|Object|Example value|Description|
|------|-------------|-----------|
|FORCE_BMS_ERROR|0||
|FORCE_OP_MODE|0||
|FULL_CELL_VOLTAGE_MV|4069||
|MAX_BATTERY_TEMP_LIMIT_DEG|45||
|MAX_MODULE_CHARGE_CURRENT_LIMIT_A|12||
|MAX_MODULE_DISCHARGE_CURRENT_LIMIT_A|65512||
|OPERATIONAL_MODE|2||
|USE_ROA_PARAMETER|0||

### Category CASC
Information represented by the CASC-Object:
|Object|Example value|Description|
|------|-------------|-----------|
|BATPOWERSUM|-376.0310363769531||
|POWER|[0.0, 0.0, 0.0, 0.0, 0.0, 0.0]||
|PVGEN|[0.0, 0.0, 0.0, 0.0, 0.0, 0.0]||
|PVMASTER|0.0||
|SOC|[100.0, 100.0, 100.0, 100.0, 100.0, 100.0]||
|STATE|[0, 0, 0, 0, 0, 0]||
|TARGET|[0.0, 0.0, 0.0, 0.0, 0.0, 0.0]||
  
### Category DISPLAY
Returns an empty object

### Category FACTORY
Information represented by the FACTORY-Object:
|Object|Example value|Description|
|------|-------------|-----------|
|BAT_TYPE|4|Battery type|
|CELL_TYPE|5|Cell type|
|COUNTRY|0||
|DESIGN_CAPACITY|7500.0|Capacity of available batteries|
|DEVICE_ID|"2525866113258324220991834"||
|EPA_GRID_FILTER|0||
|FAC_SANITY|1||
|MAX_CHARGE_POWER_DC|1875.0|Sum of power the available batteries can be charged|
|MAX_DISCHARGE_POWER_DC|3750.0|Sum of power the available batteries can be discharged|
|PM_TYPE|1||
|SYS_TYPE|17||

#### Translation of the FACTORY BAT_TYPE ENUM
| ENUM | Description |
|---|---|
| 0 | Studer Xtender |
| 1 | SenecBatt |
| 2 | Senec.Inverter V2 |
| 3 | SENEC.Inverter V2.1 |
| 4 | SENEC.Inverter V3 LV |

### Category GRIDCONFIG
Information represented by the GRIDCONFIG-Object:
|Object|Example value|Description|
|------|-------------|-----------|
| PWRCFG_COS_POINT1 | 1 | |
| PWRCFG_COS_POINT3 | 0.95 | |
| PWRCFG_COS_POINT_2A | 1 | |
| PWRCFG_COS_POINT_2B | 50 | |
| PWRCFG_USE_MAX_PWR_SKEW | 1 | |
| VDECOSPHITIME | 10 | |
| VDEFIXEDFAC | 0.9 | |
| VDEOVERFREQDROOP | 5 | |
| VDEOVERFREQLIMIT | 50.2 | |
| VDEPT1RESPONSETIME | 0 | |
| VDERECOVERTIME | 10 | |
| VDETARGETTY | 1 | |
| VDEUNDERFREQDROOP | 2 | |
| VDE_FREQDROPPROT | 47.5 | |
| VDE_FREQDROPPROTDELAY | 0.1 | |
| VDE_FREQRISEPROT | 51.5 | |
| VDE_FREQRISEPROTDELAY | 0.1 | |
| VDE_UNDERFREQLIMIT | 49.8 | |
| VDE_VOLTDROPPROT | 45 | |
| VDE_VOLTDROPPROTAVG | 80 | |
| VDE_VOLTDROPPROTAVGDELAY | 3 | |
| VDE_VOLTDROPPROTDELAY | 0.3 | |
| VDE_VOLTRISEPROT | 125 | |
| VDE_VOLTRISEPROTAVG | 110 | |
| VDE_VOLTRISEPROTAVGDELAY | 0.1 | |
| VDE_VOLTRISEPROTDELAY | 0.1 | |

### Category PM1
Information represented by the PM1-Object:
|Object|Example value|Description|
|------|-------------|-----------|
| MB_SL2MA_CONN | 0 | |
| MB_SLAVES_COUNT | 0 ||
| PWR_METERS_MISSING | 0 ||
| TYPE | 1 ||

### Category PM1OBJ1
Information represented by the PM1OBJ1-Object - ENFLURI 1:
|Object|Example value|Description|
|------|-------------|-----------|
|ADR|1||
|ENABLED|1||
|FREQ|50.05999755859375|Frequency of the power grid|
|I_AC|[1.159999966621399, 0.35999998450279236, 1.0]|Current in amps for each phase. For each phase a single sensor is set up.|
|P_AC|[-234.3199920654297, 49.84000015258789, 174.45999145507812]|Current power (w) of each phase. For each phase a single sensor is set up.|
|P_TOTAL|-10.029999732971191||
|U_AC|[229.40000915527344, 230.3000030517578, 228.40000915527344]|Current voltage per phase. For each phase a single sensor is set up.|


### Category PM1OBJ2
Information represented by the PM1OBJ2-Object - ENFLURI 2:
|Object|Example value|Description|
|------|-------------|-----------|
|ADR|2||
|ENABLED|0||
|FREQ|0.0||
|I_AC|[0.0, 0.0, 0.0]||
|P_AC|[0.0, 0.0, 0.0]||
|P_TOTAL|0.0||
|U_AC|[0.0, 0.0, 0.0]||


### Category RTC
Information represented by the RTC-Object:
|Object|Example value|Description|
|------|-------------|-----------|
|TIMESTAMP_MS|1314036527||
|UTC_OFFSET|120||
|WEB_TIME|1691275183||

### Category SELFTEST_RESULTS
Information represented by the SELFTEST_RESULTS-Object:
|Object|Example value|Description|
|------|-------------|-----------|
|DC_COIL|Test passed||
|INIT_BATTERY_MODULES|Test passed||
|INSULATION|Test passed||
|INTERRUPT|No Interrupt||
|IPU|Test not initialized||

### Category SOCKETS
Information represented by the SOCKETS-Object:
|Object|Example value|Description|
|------|-------------|-----------|
|ALREADY_SWITCHED|[0, 0]||
|ENABLE|[0, 0]||
|FORCE_ON|[0, 0]||
|LOWER_LIMIT|[0, 0]||
|NUMBER_OF_SOCKETS|2||
|POWER_ON|[0, 0]||
|POWER_ON_TIME|[0, 0]||
|PRIORITY|[0, 0]||
|RESET_SWITCHED|0||
|SWITCH_ON_HOUR|[0, 0]||
|SWITCH_ON_MINUTE|[0, 0]||
|TIME_LIMIT|[0, 0]||
|TIME_REM|[0, 0]||
|UPPER_LIMIT|[0, 0]||
|USE_TIME|[0, 0]||

### Category "STATISTIC"

Returns an empty object.

### Category STECA
Information represented by the STECA-Object:
|Object|Example value|Description|
|------|-------------|-----------|
|AU2020_VERSION_MISMATCH|0||
|BAT|1||
|BDC_STATE|[262144, 0, 1073741824]||
|ERROR|0||
|ERRORTEXT|""||
|ISLAND|1||
|NUM_PV_CONFIG_POSSIBLE|10||
|PV|1||
|PVSS|4||
|PV_CONFIG_POSSIBLE|[1, 1, 1, 2, 16, 1, 1, 16, 16, 16]||
|PV_INPUTS|2|Number of MPPs provided|
|RELAYS|15||
|STARTUP|272|See tranlation of ENUMS below - 272=Run Grid|
|STARTUP_ADD|4294967295||

#### Translation of the ENUMS for the STARTUP Variable
|ENUM|Description|
|----|-----------|
| 0 | StabilizeMcuSupply |
| 16 | StartHighSidePwm |
| 32 | StartAuxSupply |
| 48 | StartMonitoring |
| 64 | ThermalManagement |
| 80 | StartProtection |
| 88 | CheckIslanding |
| 96 | DegaussRCD |
| 112 | GetAcOffset |
| 128 | SwitchOnRelaisSupply |
| 136 | CheckStrings |
| 140 | EstablishLink |
| 141 | BlackStart |
| 144 | TestAcRelais |
| 160 | TestDcRelais |
| 176 | SwitchOnDcRelais |
| 184 | CheckDcShortcircuitAndPolarity |
| 192 | GetDcOffset |
| 208 | TestRcd |
| 224 | IsolationCheck |
| 228 | SwitchOnENS |
| 232 | ReestablishLink |
| 236 | RecheckIslanding |
| 237 | EstablishIslandingLink |
| 238 | ConfirmIslanding |
| 240 | WaitEnsClearance |
| 256 | EstablishAcVoltage |
| 264 | RunIslanding |
| 272 | RunGrid |
| 280 | CheckShortFault |
| 288 | SafeState |
| 304 | Sleep |
| 312 | SleepAfterIslanding |
| 320 | ShutdownForSleep |
| 336 | SystemReset |
| 352 | WaitForReset |

### Category SYS_UPDATE
Information represented by the SYS_UPDATE-Object:
|Object|Example value|Description|
|------|-------------|-----------|
|FSM_STATE|1||
|MISC|[0, 0, 0, 0, 0, 0]||
|NPU_IMAGE_VERSION|2011||
|NPU_VER|9||
|UPDATE_AVAILABLE|0||
|USER_REBOOT_DEVICE|0||
|USER_REQ_UPDATE|0||


### Category TEMPMEASURE
Information represented by the TEMPMEASURE-Object:
|Object|Example value|Description|
|------|-------------|-----------|
|BATTERY_TEMP|32.0|Temperature of the batteries in °C|
|CASE_TEMP|39.308067321777344|Temperature of the case in °C|
|MCU_TEMP|49.744564056396484|Temperature of the MCU in °C|
|TEMP_DATA_COLLECTED|1||

### Category TEST
Returns an empty object.

### Category UPDATE
Returns an empty object.

### Category WALLBOX
Information represented by the WALLBOX-Object:
|Object|Example value|Description|
|------|-------------|-----------|
|ADDITIONAL_ERROR|[0, 0, 0, 0]||
|ALLOW_INTERCHARGE|0||
|APPARENT_CHARGING_POWER|[0.0, 0.0, 0.0, 0.0]||
|BUS_ADR|[1, 2, 3, 4]||
|CS_ENABLED|[0, 0, 0, 0]||
|DETECTION_MODE|0||
|EV_CONNECTED|[0, 0, 0, 0]||
|HW_TYPE|[0, 0, 0, 0]||
|L1_CHARGING_CURRENT|[0.0, 0.0, 0.0, 0.0]||
|L1_USED|[0, 0, 0, 0]||
|L2_CHARGING_CURRENT|[0.0, 0.0, 0.0, 0.0]||
|L2_USED|[0, 0, 0, 0]||
|L3_CHARGING_CURRENT|[0.0, 0.0, 0.0, 0.0]||
|L3_USED|[0, 0, 0, 0]||
|LOAD_IMBALANCE_DETECTED|[0, 0, 0, 0]||
|LOAD_IMBALANCE_ENABLED|[0, 0, 0, 0]||
|MAJOR_REV|[0, 0, 0, 0]||
|MAX_CHARGING_CURRENT_DEFAULT|[0.0, 0.0, 0.0, 0.0]||
|MAX_CHARGING_CURRENT_IC|[0.0, 0.0, 0.0, 0.0]||
|MAX_CHARGING_CURRENT_ICMAX|[0.0, 0.0, 0.0, 0.0]||
|MAX_CHARGING_CURRENT_RATED|[0.0, 0.0, 0.0, 0.0]||
|MAX_PHASE_CURRENT_BY_GRID|0.0||
|MAX_TOTAL_CURRENT_BY_GRID|0.0||
|METER_ENABLED|[0, 0, 0, 0]||
|METHOD_EN1|[0, 0, 0, 0]||
|MINOR_REV|[0, 0, 0, 0]||
|MIN_CHARGING_CURRENT|[ 0.0, 0.0, 0.0, 0.0]||
|PHASES_USED|[0, 0, 0, 0]||
|PROHIBIT_USAGE|[0, 0, 0, 0]||
|SAP_NUMBER|["", "", "", ""]||
|SERIAL_NUMBER|["", "", "", ""]||
|SERIAL_NUMBER_INTERNAL|["", "", "", ""]||
|SET_ICMAX|[0.0, 0.0, 0.0, 0.0]||
|SET_IDEFAULT|[0.0, 0.0, 0.0, 0.0]||
|SMART_CHARGE_ACTIVE|[0, 0, 0, 0]||
|SOCKET_ENABLED|[0, 0, 0, 0]||
|STATE|[0, 0, 0, 0]||
|UID|[0, 0, 0, 0]||
|UTMP|[0, 0, 0, 0]||

#### Translation of Wallbox STATE ENUM
| ENUM | Description |
|---|---|
| 0x00 | invalid state |
| 0xA1 | not connected |
| 0xA2 | not connected |
| 0xB1 | connected |
| 0xB2 | ready |
| 0xC2 | charging |
| 0xC3 | charging with reduced power (high temperature) |
| 0xC4 | charging with reduced power (unbalanced load limitation) |
| 0xE0 | deactivated (enabling contact) |
| 0xF1 | contact error |
| 0xF2 | internal error |
| 0xF3 | fault current detected |
| 0xF4 | EV charger communication error |
| 0xF5 | locking error |
| 0xF6 | cable error |
| 0xF7 | vehicle overtemperature |
| 0xF8 | vehicle communication error |
| 0xF9 | power supply error |
| 0xFA | temperature too high |
| 0xFB | contact error |

### Category CURRENT_IMBALANCE_CONTROL
Information represented by the Current_IMBALANCE_CONTROL-Object:
|Object|Example value|Description|
|------|-------------|-----------|
|THRESHOLD_mA|8000| Threadshold |

### Category BMZ_CURRENT_LIMITS
Information represented by the BMZ_CURRENT_LIMITS-Object:
|Object|Example value|Description|
|------|-------------|-----------|
|MIN_CURRENT_LIMIT_A|65512||
|MAX_CURRENT_LIMIT_A|12||


### Category CELL_DEVIATION_ROC
Information represented by the CELL_DEVIATION_ROC-Object:
|Object|Example value|Description|
|------|-------------|-----------|
|SKIP_WAITING|0||

### Category SENEC_IO_INPUT
Information represented by the SENEC_IO_INPUT-Object:
|Object|Example value|Description|
|------|-------------|-----------|
|STATUS_DC_SWITCH_IPU_V5|1||
|FAULTLINE_DELAYED|0||
|FAULTLINE|0||
|STATUS_AC_SWITCH_IPU_V3|0||
|ISOGUARD_STATUS|1||
|DRY_CONTACT_IN_IPU_V5|1||
|DC_HK_STATUS_IPU_V5|0||
|POWER_STATUS|1||
|HID3_IPU_V5|0||
|HID2_IPU_V5|1||
|HID1|1||
|HID0|0||
|RCD_RMS_IPU_V3|1||
|RCD_ERROR_IPU_V3|1||
|RCD_DC_IPU_V3|0||
|AC_ERROR_IPU_V3|1||

### Category SENEC_IO_OUTPUT
Information represented by the SENEC_IO_OUTPUT-Object:
|Object|Example value|Description|
|------|-------------|-----------|
|BAT_MODULE_ENABLE_SAMSUNG_IPU_V5|0|1 =Samsung Modules are used  |
|BAT_MODULE_ENABLE_BMZ|1|1 = BMZ Modules are used|
|KILLSWITCH|0||
|Relay_4|0||
|Relay_3|0||
|Relay_2|0||
|Relay_1|0||
|ISOGUARD_ENABLE|0||
|DC_SWITCH|1||
|AC_SWITCH_IPU_V3|0||
|DRY_CONTACT_OUT_IPU_V5|1||
|RCD_RESET_IPU_V3|0||
|RCD_TEST_IPU_V3|1||

### Category IPU
Information represented by the IPU-Object:
|Object|Example value|Description|
|------|-------------|-----------|
|VERSION|2||

### Category FAN_TEST
Information represented by the FAN_TEST-Object:
|Object|Example value|Description|
|------|-------------|-----------|
|INV_LV|0||
|INV_HV|0||

### Category FAN_SPEED
Information represented by the FAN_SPEED-Object:
|Object|Example value|Description|
|------|-------------|-----------|
|INV_LV|0||
|INV_HV|0||


### Category V_STECA
Information represented by the V_STECA-Object:
|Object|Example value|Description|
|------|-------------|-----------|
|percent#v|0.0||
|percent#vf|0.0|||
|percent#f|0|||
