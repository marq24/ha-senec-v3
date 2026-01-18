from typing import Final

SENEC_SECTION_BAT1 = "BAT1"
SENEC_SECTION_BAT1OBJ1 = "BAT1OBJ1"
SENEC_SECTION_BMS = "BMS"
SENEC_SECTION_BMS_CELLS = "internal-only-BMS-CELLS"
SENEC_SECTION_BMS_PARA = "BMS_PARA"
SENEC_SECTION_CASC = "CASC"
SENEC_SECTION_DEBUG = "DEBUG"
SENEC_SECTION_DISPLAY = "DISPLAY"
SENEC_SECTION_ENERGY = "ENERGY"
SENEC_SECTION_FACTORY = "FACTORY"
SENEC_SECTION_FEATURES = "FEATURES"
SENEC_SECTION_FILE = "FILE"
SENEC_SECTION_GRIDCONFIG = "GRIDCONFIG"
SENEC_SECTION_LOG = "LOG"
SENEC_SECTION_PM1 = "PM1"
SENEC_SECTION_PM1OBJ1 = "PM1OBJ1"
SENEC_SECTION_PM1OBJ2 = "PM1OBJ2"
SENEC_SECTION_PV1 = "PV1"
SENEC_SECTION_PWR_UNIT = "PWR_UNIT"
SENEC_SECTION_RTC = "RTC"
SENEC_SECTION_SELFTEST_RESULTS = "SELFTEST_RESULTS"
SENEC_SECTION_SOCKETS = "SOCKETS"
SENEC_SECTION_STATISTIC = "STATISTIC"
SENEC_SECTION_STECA = "STECA"
SENEC_SECTION_SYS_UPDATE = "SYS_UPDATE"
SENEC_SECTION_TEMPMEASURE = "TEMPMEASURE"
SENEC_SECTION_TEST = "TEST"
SENEC_SECTION_UPDATE = "UPDATE"
SENEC_SECTION_WALLBOX = "WALLBOX"
SENEC_SECTION_WIZARD = "WIZARD"
SENEC_SECTION_CURRENT_IMBALANCE_CONTROL = "CURRENT_IMBALANCE_CONTROL"
SENEC_SECTION_BMZ_CURRENT_LIMITS = "BMZ_CURRENT_LIMITS"
SENEC_SECTION_CELL_DEVIATION_ROC = "CELL_DEVIATION_ROC"
SENEC_SECTION_SENEC_IO_INPUT = "SENEC_IO_INPUT"
SENEC_SECTION_SENEC_IO_OUTPUT = "SENEC_IO_OUTPUT"
SENEC_SECTION_IPU = "IPU"
SENEC_SECTION_FAN_TEST = "FAN_TEST"
SENEC_SECTION_FAN_SPEED = "FAN_SPEED"

SENEC_ENERGY_FIELDS = {
    "STAT_STATE": "",
    "GUI_GRID_POW": "",
    "GUI_HOUSE_POW": "",
    "GUI_INVERTER_POWER": "",
    "GUI_BAT_DATA_FUEL_CHARGE": "",
    "GUI_BAT_DATA_POWER": "",
    "GUI_BAT_DATA_VOLTAGE": "",
    "GUI_BAT_DATA_CURRENT": "",
    "SAFE_CHARGE_RUNNING": "",
    "LI_STORAGE_MODE_RUNNING": ""
}

SENEC_ENERGY_FIELDS_2408_MIN = {
    "STAT_STATE": "",
    "STAT_HOURS_OF_OPERATION": "",
    "GUI_GRID_POW": "",
    "GUI_HOUSE_POW": "",
    "GUI_INVERTER_POWER": "",
    "GUI_BAT_DATA_FUEL_CHARGE": "",
    "GUI_BAT_DATA_POWER": "",
    "GUI_BAT_DATA_VOLTAGE": "",
    "GUI_BAT_DATA_CURRENT": "",
    "SAFE_CHARGE_RUNNING": "",
    "LI_STORAGE_MODE_RUNNING": ""
}

SENEC_ENERGY_FIELDS_2408 = {
    "CAPTESTMODULE": "",
    "GRID_POWER_OFFSET": "",
    "GUI_BAT_DATA_COLLECTED": "",
    "GUI_BAT_DATA_CURRENT": "",
    "GUI_BAT_DATA_FUEL_CHARGE": "",
    "GUI_BAT_DATA_MAX_CELL_VOLTAGE": "",
    "GUI_BAT_DATA_MIN_CELL_VOLTAGE": "",
    "GUI_BAT_DATA_POWER": "",
    "GUI_BAT_DATA_VOLTAGE": "",
    "GUI_BOOSTING_INFO": "",
    "GUI_CAP_TEST_DIS_COUNT": "",
    "GUI_CAP_TEST_START": "",
    "GUI_CAP_TEST_STATE": "",
    "GUI_CAP_TEST_STOP": "",
    "GUI_CHARGING_INFO": "",
    "GUI_FACTORY_TEST_FAN": "",
    "GUI_GRID_POW": "",
    "GUI_HOUSE_POW": "",
    "GUI_INIT_CHARGE_START": "",
    "GUI_INIT_CHARGE_STOP": "",
    "GUI_INVERTER_POWER": "",
    "GUI_TEST_CHARGE_STAT": "",
    "GUI_TEST_DISCHARGE_STAT": "",
    "INIT_CHARGE_ACK": "",
    "INIT_CHARGE_DIFF_VOLTAGE": "",
    "INIT_CHARGE_MAX_CURRENT": "",
    "INIT_CHARGE_MAX_VOLTAGE": "",
    "INIT_CHARGE_MIN_VOLTAGE": "",
    "INIT_CHARGE_RERUN": "",
    "INIT_CHARGE_RUNNING": "",
    "INIT_CHARGE_STATE": "",
    "INIT_CHARGE_TIMER": "",
    "INIT_DISCHARGE_MAX_CURRENT": "",
    "LI_STORAGE_MODE_RUNNING": "",
    "LI_STORAGE_MODE_START": "",
    "LI_STORAGE_MODE_STOP": "",
    "SAFE_CHARGE_FORCE": "",
    "SAFE_CHARGE_PROHIBIT": "",
    "SAFE_CHARGE_RUNNING": "",
    "STAT_HOURS_OF_OPERATION": "",
    "STAT_LIMITED_NET_SKEW": "",
    "STAT_STATE": "",
    "TEST_CHARGE_ENABLE": "",
    "TEST_CYCLE": "",
    "ZERO_EXPORT": ""
}

BATT_TYPE_NAME = {
    0: "Studer Xtender",
    1: "SenecBatt",
    2: "Senec Inverter V2",
    3: "SENEC.Inverter V2.1",
    4: "SENEC.Inverter V3 LV"
}

SYSTEM_TYPE_NAME = {
    0: "Senec Home 8.0 / Blei",
    1: "Senec Business 30.0 / Blei",
    2: "Solarinvert Storage 10.0 / Blei",
    3: "Senec Home 4.0 / Blei",
    4: "Senec Home 5.0/7.5/10.0 / Lithium",
    5: "Senec Home 15.0 / Lithium",
    6: "Senec Business 25.0 / Lithium",
    7: "Senec Home 6.0 Pb",
    8: "Senec Home 10.0 Pb",
    9: "Senec Home V2 5.0/7.5/10.0",
    10: "Senec Business V2 30.0 / Blei",
    11: "Senec Home V2 10.0 / Blei",
    12: "OEM LG",
    13: "Senec Business V2_2ph / Lithium",
    14: "Senec Business V2 3ph / Lithium",
    15: "Senec Home V2.1 1ph / Lithium",
    16: "ADS Tec",
    17: "SENEC.Home V3 hybrid",
    18: "SENEC.Home V3 hybrid duo",
    19: "SENEC.Home V3 hybrid",
    20: "SENEC.Home V3 hybrid LFP",
    21: "SENEC.Home V3 hybrid duo LFP"
}

SYSTEM_STATE_NAME = {
    "en": {
        0: "INITIALSTATE",
        1: "ERROR INVERTER COMMUNICATION",
        2: "ERROR ELECTRICY METER",
        3: "RIPPLE CONTROL RECEIVER",
        4: "INITIAL CHARGE",
        5: "MAINTENANCE CHARGE",
        6: "MAINTENANCE READY",
        7: "MAINTENANCE REQUIRED",
        8: "MAN. SAFETY CHARGE",
        9: "SAFETY CHARGE READY",
        10: "FULL CHARGE",
        11: "EQUALIZATION: CHARGE",
        12: "DESULFATATION: CHARGE",
        13: "BATTERY FULL",
        14: "CHARGE",
        15: "BATTERY EMPTY",
        16: "DISCHARGE",
        17: "PV + DISCHARGE",
        18: "GRID + DISCHARGE",
        19: "PASSIVE",
        20: "OFF",
        21: "OWN CONSUMPTION",
        22: "RESTART",
        23: "MAN. EQUALIZATION: CHARGE",
        24: "MAN. DESULFATATION: CHARGE",
        25: "SAFETY CHARGE",
        26: "BATTERY PROTECTION MODE",
        27: "EG ERROR",
        28: "EG CHARGE",
        29: "EG DISCHARGE",
        30: "EG PASSIVE",
        31: "EG PROHIBIT CHARGE",
        32: "EG PROHIBIT DISCHARGE",
        33: "EMERGENCY CHARGE",
        34: "SOFTWARE UPDATE",
        35: "NSP ERROR",
        36: "NSP ERROR: GRID",
        37: "NSP ERROR: HARDWRE",
        38: "NO SERVER CONNECTION",
        39: "BMS ERROR",
        40: "MAINTENANCE: FILTER",
        41: "BMS SHUTDOWN",
        42: "WAITING EXCESS",
        43: "CAPACITY TEST: CHARGE",
        44: "CAPACITY TEST: DISCHARGE",
        45: "MAN. DESULFATATION: WAIT",
        46: "MAN. DESULFATATION: READY",
        47: "MAN. DESULFATATION: ERROR",
        48: "EQUALIZATION: WAIT",
        49: "EMERGENCY CHARGE: ERROR",
        50: "MAN. EQUALIZATION: WAIT",
        51: "MAN. EQUALIZATION: ERROR",
        52: "MAN: EQUALIZATION: READY",
        53: "AUTO. DESULFATATION: WAIT",
        54: "ABSORPTION PHASE",
        55: "DC-SWITCH OFF",
        56: "PEAK-SHAVING: WAIT",
        57: "ERROR BATTERY INVERTER",
        58: "NPU-ERROR",
        59: "BMS OFFLINE",
        60: "MAINTENANCE CHARGE ERROR",
        61: "MAN. SAFETY CHARGE ERROR",
        62: "SAFETY CHARGE ERROR",
        63: "NO CONNECTION TO MASTER",
        64: "LITHIUM SAFE MODE ACTIVE",
        65: "LITHIUM SAFE MODE DONE",
        66: "BATTERY VOLTAGE ERROR",
        67: "BMS DC SWITCHED OFF",
        68: "GRID INITIALIZATION",
        69: "GRID STABILIZATION",
        70: "REMOTE SHUTDOWN",
        71: "OFFPEAK-CHARGE",
        72: "ERROR HALFBRIDGE",
        73: "BMS: ERROR OPERATING TEMPERATURE",
        74: "FACTORY SETTINGS NOT FOUND",
        75: "BACKUP POWER MODE - ACTIVE",
        76: "BACKUP POWER MODE - BATTERY EMPTY",
        77: "BACKUP POWER MODE ERROR",
        78: "INITIALISING",
        79: "INSTALLATION MODE",
        80: "GRID OFFLINE",
        81: "BMS UPDATE NEEDED",
        82: "BMS CONFIGURATION NEEDED",
        83: "INSULATION TEST",
        84: "SELFTEST",
        85: "EXTERNAL CONTROL",
        86: "ERROR: TEMPERATURESENSOR",
        87: "GRID OPERATOR: CHARGE PROHIBITED",
        88: "GRID OPERATOR: DISCHARGE PROHIBITED",
        89: "SPARE CAPACITY",
        90: "SELFTEST ERROR",
        91: "EARTH FAULT",
        92: "PV-MODE",
        93: "REMOTE DISCONNECTION",
        94: "ERROR DRM0",
        95: "BATTERY DIAGNOSIS",
        96: "BALANCING",
        97: "SAFETY DISCHARGE",
        98: "BMS ERROR - MODULE IMBALANCE",
        99: "WAKE UP CHARGING",
        100: "SOX-CALIBRATION"
    },
    "de": {
        0: "INITIALZUSTAND",
        1: "KEINE KOMMUNIKATION LADEGERAET",
        2: "FEHLER LEISTUNGSMESSGERAET",
        3: "RUNDSTEUEREMPFAENGER",
        4: "ERSTLADUNG",
        5: "WARTUNGSLADUNG",
        6: "WARTUNGSLADUNG FERTIG",
        7: "WARTUNG NOTWENDIG",
        8: "MAN. SICHERHEITSLADUNG",
        9: "SICHERHEITSLADUNG FERTIG",
        10: "VOLLLADUNG",
        11: "AUSGLEICHSLADUNG: LADEN",
        12: "SULFATLADUNG: LADEN",
        13: "AKKU VOLL",
        14: "LADEN",
        15: "AKKU LEER",
        16: "ENTLADEN",
        17: "PV + ENTLADEN",
        18: "NETZ + ENTLADEN",
        19: "PASSIV",
        20: "AUSGESCHALTET",
        21: "EIGENVERBRAUCH",
        22: "NEUSTART",
        23: "MAN. AUSGLEICHSLADUNG: LADEN",
        24: "MAN. SULFATLADUNG: LADEN",
        25: "SICHERHEITSLADUNG",
        26: "AKKU-SCHUTZBETRIEB",
        27: "EG FEHLER",
        28: "EG LADEN",
        29: "EG ENTLADEN",
        30: "EG PASSIV",
        31: "EG LADEN VERBOTEN",
        32: "EG ENTLADEN VERBOTEN",
        33: "NOTLADUNG",
        34: "SOFTWAREAKTUALISIERUNG",
        35: "FEHLER: NA-SCHUTZ",
        36: "FEHLER: NA-SCHUTZ NETZ",
        37: "FEHLER: NA-SCHUTZ HARDWARE",
        38: "KEINE SERVERVERBINDUNG",
        39: "BMS FEHLER",
        40: "WARTUNG: FILTER",
        41: "ABSCHALTUNG LITHIUM",
        42: "WARTE AUF ÜBERSCHUSS",
        43: "KAPAZITÄTSTEST: LADEN",
        44: "KAPAZITÄTSTEST: ENTLADEN",
        45: "MAN. SULFATLADUNG: WARTEN",
        46: "MAN. SULFATLADUNG: FERTIG",
        47: "MAN. SULFATLADUNG: FEHLER",
        48: "AUSGLEICHSLADUNG: WARTEN",
        49: "NOTLADUNG: FEHLER",
        50: "MAN: AUSGLEICHSLADUNG: WARTEN",
        51: "MAN: AUSGLEICHSLADUNG: FEHLER",
        52: "MAN: AUSGLEICHSLADUNG: FERTIG",
        53: "AUTO: SULFATLADUNG: WARTEN",
        54: "LADESCHLUSSPHASE",
        55: "BATTERIETRENNSCHALTER AUS",
        56: "PEAK-SHAVING: WARTEN",
        57: "FEHLER LADEGERAET",
        58: "NPU-FEHLER",
        59: "BMS OFFLINE",
        60: "WARTUNGSLADUNG FEHLER",
        61: "MAN. SICHERHEITSLADUNG FEHLER",
        62: "SICHERHEITSLADUNG FEHLER",
        63: "KEINE MASTERVERBINDUNG",
        64: "LITHIUM SICHERHEITSMODUS AKTIV",
        65: "LITHIUM SICHERHEITSMODUS BEENDET",
        66: "FEHLER BATTERIESPANNUNG",
        67: "BMS DC AUSGESCHALTET",
        68: "NETZINITIALISIERUNG",
        69: "NETZSTABILISIERUNG",
        70: "FERNABSCHALTUNG",
        71: "OFFPEAK-LADEN",
        72: "FEHLER HALBBRÜCKE",
        73: "BMS: FEHLER BETRIEBSTEMPERATUR",
        74: "FACTORY SETTINGS NICHT GEFUNDEN",
        75: "NETZERSATZBETRIEB",
        76: "NETZERSATZBETRIEB AKKU LEER",
        77: "NETZERSATZBETRIEB FEHLER",
        78: "INITIALISIERUNG",
        79: "INSTALLATIONSMODUS",
        80: "NETZAUSFALL",
        81: "BMS UPDATE ERFORDERLICH",
        82: "BMS KONFIGURATION ERFORDERLICH",
        83: "ISOLATIONSTEST",
        84: "SELBSTTEST",
        85: "EXTERNE STEUERUNG",
        86: "TEMPERATUR SENSOR FEHLER",
        87: "NETZBETREIBER: LADEN GESPERRT",
        88: "NETZBETREIBER: ENTLADEN GESPERRT",
        89: "RESERVEKAPAZITÄT",
        90: "SELBSTTEST FEHLER",
        91: "ISOLATIONSFEHLER",
        92: "PV-MODUS",
        93: "FERNABSCHALTUNG NETZBETREIBER",
        94: "FEHLER DRM0",
        95: "BATTERIEDIAGNOSE",
        96: "BALANCING",
        97: "SICHERHEITSENTLADUNG",
        98: "BMS FEHLER - MODULUNGLEICHGEWICHT",
        99: "AUFWACHLADUNG",
        100: "SOX-KALIBRIERUNG"
    },
    "it": {
        0: "STATO INIZIALE",
        1: "ERRORE COMMUNICAZIONE INVERTER",
        2: "ERRORE WATTMETRO",
        3: "RICEVITORE RIPPLE CONTROL",
        4: "PRIMA CARICA",
        5: "CARICA DI MANTENIMENTO",
        6: "CARICA DI MANTENIMENTO COMPLETATA",
        7: "MANUTENZIONE: NECESSARIA",
        8: "CARICA DI SICUREZZA MANUALE",
        9: "CARICA DI SICUREZZA COMPLETA",
        10: "CARICA COMPLETA",
        11: "CARICA DI EQUALIZZAZIONE",
        12: "CARICA DI DESOLFATAZIONE",
        13: "ACCUMULATORE CARICO",
        14: "CARICA",
        15: "ACCUMULATORE SCARICO",
        16: "SCARICA",
        17: "FV + SCARICA",
        18: "RETE + SCARICA",
        19: "PASSIVO",
        20: "SPENTO",
        21: "AUTOCONSUMO",
        22: "RIAVVIO",
        23: "CARICA DI EQUALIZZAZIONE MANUALE",
        24: "CARICA DI DESOLFATAZIONE MANUALE",
        25: "CARICA DI SICUREZZA",
        26: "MODALITÀ PROTEZIONE ACCUMULATORE",
        27: "ERRORE EG",
        28: "EG: CARICA",
        29: "EG: SCARICA",
        30: "EG: PASSIVO",
        31: "CARICA EG PROIBITA",
        32: "SCARICAMENTO EG PROIBITO",
        33: "CARICA D'EMERGENZA",
        34: "AGGIORNAMENTO SOFTWARE",
        35: "ERRORE SPI",
        36: "ERRORE SPI: RETE ",
        37: "ERRORE SPI: HARDWARE ",
        38: "NESSUNA CONNESSIONE AL SERVER",
        39: "ERRORE BMS",
        40: "SOSTITUZIONE DEL FILTRO NECESSARIA",
        41: "CHIUSURA BMS",
        42: "IN ATTESA DI SURPLUS ENERGETICO",
        43: "TEST DI CAPACITÀ: CARICA",
        44: "TEST DI CAPACITÀ: SCARICA",
        45: "CARICA DI DESOLFATAZIONE MANUALE: ATTESA",
        46: "CARICA DI DESOLFATAZIONE MANUALE: COMPLETA",
        47: "CARICA DI DESOLFATAZIONE MANUALE: ERRORE",
        48: "EQUALIZZAZIONE: ATTESA",
        49: "CARICA D'EMERGENZA: ERRORE",
        50: "EQUALIZZAZIONE MANUALE: ATTESA",
        51: "EQUALIZZAZIONE MANUALE: ERRORE",
        52: "EQUALIZZAZIONE MANUALE: COMPLETA",
        53: "CARICA DI DESOLFATAZIONE: ATTESA",
        54: "FASE FINALE CARICA",
        55: "SEZIONATORE BATTERIA OFF",
        56: "PEAK SHAVING: ATTESA",
        57: "ERRORE DISPOSITIVO DI CARICA",
        58: "ERRORE NPU",
        59: "BMS DISCONESSO",
        60: "CARICA DI MANUTENZIONE ERRORE",
        61: "CARICA DI SICUREZZA MANUALE ERRORE",
        62: "CARICA DI SICUREZZA ERRORE",
        63: "NESSUNA CONNESSIONE MASTER",
        64: "MODALITA DI PROTEZIONE LITIO ATTIVA",
        65: "MODALITA DI PROTEZIONE LITIO COMPLETA",
        66: "ERORE DI TENSIONE BATTERIA",
        67: "BMS DC SPENTO",
        68: "INIZIALIZZAZIONE DELLA RETE",
        69: "STABILIZZAZIONE DELLA RETE",
        70: "ARRESTO REMOTO",
        71: "OFFPEAK-CARICA",
        72: "ERRORE MEZZO PONTE",
        73: "BMS: ERRORE TEMPERATURA DI FUNZIONAMENTO",
        74: "FACTORY SETTINGS NON TROVATO",
        75: "FUNZIONAMENTO ISOLATO",
        76: "FUNZIONAMENTO ISOLATO ACCUMULATORE SCARICO",
        77: "ERORE DI FUNZIONAMENTO ISOLATO",
        78: "INIZIALIZZAZIONE",
        79: "MODALITA INSTALLAZIONE",
        80: "RETE OFFLINE",
        81: "AGGIORNAMENTO BMS NECESSARIO",
        82: "CONFIGURAZIONE BMS NECESSARIA",
        83: "TEST DI ISOLAMENTO",
        84: "AUTOTEST",
        85: "CONTROLLO ESTERNO",
        86: "ERRORE SENSORE DI TEMPERATURA",
        87: "OPERATORE DI RETE: CARICA BLOCCATA",
        88: "OPERATORE DI RETE: SCARICA BLOCCATA",
        89: "CAPACITA INUTILIZZATA",
        90: "ERRORE DI AUTOTEST",
        91: "ERRORE DI ISOLAMENTO DC",
        92: "FV-MODE",
        93: "SCOLLEGAMENTO A DISTANZA",
        94: "ERRORE DRM0",
        95: "BATTERY DIAGNOSIS",
        96: "BALANCING",
        97: "SCARICO DI SICUREZZA",
        98: "ERRORE BMS - SQUILIBRIO DEL MODULOTRANSLATE",
        99: "CARICA DI RISVEGLIO",
        100: "SOX-CALIBRAZIONE"
    }
}

WALLBOX_STATE_NAME = {
    "en": {
        0: "Invalid",
        161: "Waiting for EV",
        162: "Waiting for EV, but locked",
        177: "EV is asking for charging",
        178: "EV has the permission to charge",
        193: "EV is asking for charging, but locked",
        194: "EV is charged",
        195: "C2 w. reduced current (error F16, F17)",
        196: "C2 w. reduced current (imbalance F15)",
        224: "Charging point disabled by enable input EN1 / key lock or for update",
        225: "production test",
        226: "EVCC can be programmed",
        227: "Bus idle",
        241: "Unintended closed contact (Welding)",
        242: "Internal error",
        243: "DC residual current detected",
        244: "Upstream communication timeout",
        245: "Lock of socket failed",
        246: "CS out of range",
        247: "State D requested by EV",
        248: "CP out of range",
        249: "Overcurrent detected",
        250: "Temperature outside limits",
        251: "Unintended opened contact",
        252: "Reserved State",
        253: "Reserved State",
    },
    "de": {
        0: "Ungültig",
        161: "Warte auf E-Fahrzeug",
        162: "Warte auf E-Fahrzeug, aber Ladepunkt gesperrt",
        177: "E-Fahrzeug fragt Ladung an",
        178: "E-Fahrzeug kann geladen werden",
        193: "E-Fahrzeug fragt Ladung an, aber Ladepunkt gesperrt",
        194: "E-Fahrzeug lädt momentan",
        195: "E-Fahrzeug lädt mit verringertem Strom (Fehler F16, F17)",
        196: "E-Fahrzeug lädt mit verringertem Strom (Schieflast F15)",
        224: "Wallbox deaktiviert durch EN1/Schlüsselschalter oder für Konfigurationsupdate",
        225: "Test Production",
        226: "Steuereinheit kann programmiert werden",
        227: "Warte auf Kommunikation mit SENEC-Speicher",
        241: "Unerwartet geschlossener Kontakt (verschweißt)",
        242: "Interner Fehler",
        243: "DC Fehlerstrom erkannt",
        244: "Fehler Kommunikation",
        245: "Sperren der Ladebuchse fehlgeschlagen",
        246: "Kabelfehler",
        247: "E-Fahrzeug meldet Übertemperatur",
        248: "Kommunikationsfehler zum E-Fahrzeug",
        249: "Überstrom erkannt",
        250: "Temperaturgrenzwert überschritten",
        251: "Unerwartet geöffneter Kontakt",
        252: "Reserved State",
        253: "Reserved State"
    },
    "it": {
        0: "Stato non valido",
        161: "Non collegato",
        162: "Non collegato (locked)",
        177: "Connesso",
        178: "Pronto",
        193: "Carica (locked)",
        194: "Carica",
        195: "Carica a potenza ridotta (temperatura elevata)",
        196: "Carica a potenza ridotta (limitazione dello squilibrio di carico)",
        224: "Disabilitato (contatto di abilitazione)",
        225: "production test",
        226: "EVCC can be programmed",
        227: "Bus idle",
        241: "Errore di contatto",
        242: "Errore interno",
        243: "Corrente di guasto rilevata",
        244: "Errore di comunicazione Wallbox",
        245: "Errore di blocco",
        246: "Errore cavo",
        247: "Sovratemperatura del veicolo",
        248: "Veicolo di errore di comunicazione",
        249: "Errore di alimentazione",
        250: "Temperatura troppo alta",
        251: "Errore di contatto",
        252: "Reserved State",
        253: "Reserved State",
    }
}

APP_API_WB_MODE_LOCKED: Final       = "LOCKED"
APP_API_WB_MODE_2025_SOLAR: Final   = "SOLAR"
APP_API_WB_MODE_2025_FAST: Final    = "FAST"

LOCAL_WB_MODE_LOCKED: Final  = "locked"
LOCAL_WB_MODE_SSGCM_3: Final = "optimized_3"
LOCAL_WB_MODE_SSGCM_4: Final = "optimized_4"
LOCAL_WB_MODE_FAST: Final    = "fast"
LOCAL_WB_MODE_FASTEST: Final = "fastest"
LOCAL_WB_MODE_UNKNOWN: Final = "unknown"

WALLBOX_CHARGING_MODES : Final = {
    0: LOCAL_WB_MODE_LOCKED,
    1: LOCAL_WB_MODE_SSGCM_3,
    2: LOCAL_WB_MODE_SSGCM_4,
    3: LOCAL_WB_MODE_FAST,
    4: LOCAL_WB_MODE_FASTEST
}

NO_LIMIT: Final         = "no_limit"
EVERY_MINUTE: Final     = "one_minute"
EVERY_5_MINUTES: Final  = "five_minutes"
EVERY_10_MINUTES: Final = "ten_minutes"
EVERY_15_MINUTES: Final = "fifteen_minutes"
EVERY_20_MINUTES: Final = "twenty_minutes"
EVERY_30_MINUTES: Final = "thirty_minutes"
EVERY_60_MINUTES: Final = "sixty_minutes"
EVERY_2_HOURS: Final    = "two_hours"
EVERY_4_HOURS: Final    = "four_hours"

UPDATE_INTERVALS: Final = {
    NO_LIMIT: 0,
    EVERY_MINUTE: 55,       # 1 minute
    EVERY_5_MINUTES: 295,   # 5 minutes
    EVERY_10_MINUTES: 595,  # 10 minutes
    EVERY_15_MINUTES: 895,  # 15 minutes
    EVERY_20_MINUTES: 1195, # 20 minutes
    EVERY_30_MINUTES: 1795, # 30 minutes
    EVERY_60_MINUTES: 3595, # 60 minutes
    EVERY_2_HOURS: 7195,    # 2 hours
    EVERY_4_HOURS: 14395    # 4 hours
}
UPDATE_INTERVAL_OPTIONS: Final = [NO_LIMIT, EVERY_MINUTE, EVERY_5_MINUTES, EVERY_10_MINUTES, EVERY_15_MINUTES, EVERY_20_MINUTES, EVERY_30_MINUTES, EVERY_60_MINUTES, EVERY_2_HOURS, EVERY_4_HOURS]

SGREADY_CONFKEY_ENABLED: Final = "enabled"
SGREADY_CONFKEY_MODE_DELAY: Final = "modeChangeDelayInMinutes"
SGREADY_CONFKEY_PON_PROPOSAL: Final = "powerOnProposalThresholdInWatt"
SGREADY_CONFKEY_PON_COMMAND: Final = "powerOnCommandThresholdInWatt"
SGREADY_CONFKEY_SDOWN_LEVEL: Final = "shutdownLevelInWatt"
SGREADY_CONF_KEYS: Final = [SGREADY_CONFKEY_ENABLED, SGREADY_CONFKEY_MODE_DELAY, SGREADY_CONFKEY_PON_PROPOSAL, SGREADY_CONFKEY_PON_COMMAND, SGREADY_CONFKEY_SDOWN_LEVEL]

SGREADY_MODES = {
    "de": {
        1: "Sperre",
        2: "Normalbetrieb",
        3: "Anlaufempfehlung",
        4: "Anlaufbefehl"
    },
    "en": {
        1: "Locked",
        2: "Regular operation",
        3: "Start suggested",
        4: "Start requested"
    }
}