# Supported Sensors for Senec V2/v3 local polling


| Sensor                          | default entity name                     | enabled by default | additional remark                                              |
|---------------------------------|-----------------------------------------|--------------------|----------------------------------------------------------------|
| System State                    | sensor.senec_system_state               | yes                |                                                                |
| Battery Temperature             | sensor.senec_battery_temp               | yes                |                                                                |
| Case Temperature                | sensor.senec_case_temp                  | yes                |                                                                |
| Controller Temperature          | sensor.senec_mcu_temp                   | yes                |                                                                |
| Solar Generated Power           | sensor.senec_solar_generated_power      | yes                |                                                                |
| House Power                     | sensor.senec_house_power                | yes                |                                                                |
| Battery State Power             | sensor.senec_battery_state_power        | yes                |                                                                |
| Battery Charge Power            | sensor.senec_battery_charge_power       | yes                |                                                                |
| Battery Discharge Power         | sensor.senec_battery_discharge_power    | yes                |                                                                |
| Battery Charge Percent          | sensor.senec_battery_charge_percent     | yes                |                                                                |
| Grid State Power                | sensor.senec_grid_state_power           | yes                |                                                                |
| Grid Imported Power             | sensor.senec_grid_imported_power        | yes                |                                                                |
| Grid Exported Power             | sensor.senec_grid_exported_power        | yes                |                                                                |
| MPP1 Potential                  | sensor.senec_solar_mpp1_potential       | no                 |                                                                |
| MPP1 Current                    | sensor.senec_solar_mpp1_current         | no                 |                                                                |
| MPP1 Power                      | sensor.senec_solar_mpp1_power           | no                 |                                                                |
| MPP2 Potential                  | sensor.senec_solar_mpp2_potential       | no                 |                                                                |
| MPP2 Current                    | sensor.senec_solar_mpp2_current         | no                 |                                                                |
| MPP2 Power                      | sensor.senec_solar_mpp2_power           | no                 |                                                                |
| MPP3 Potential                  | sensor.senec_solar_mpp3_potential       | no                 |                                                                |
| MPP3 Current                    | sensor.senec_solar_mpp3_current         | no                 |                                                                |
| MPP3 Power                      | sensor.senec_solar_mpp3_power           | no                 |                                                                |
| Enfluri Net Frequency           | sensor.senec_enfluri_net_freq           | no                 |                                                                |
| Enfluri Net Total Power         | sensor.senec_enfluri_net_power_total    | no                 |                                                                |
| Enfluri Net Potential Phase 1   | sensor.senec_enfluri_net_potential_p1   | no                 |                                                                |
| Enfluri Net Potential Phase 2   | sensor.senec_enfluri_net_potential_p2   | no                 |                                                                |
| Enfluri Net Potential Phase 3   | sensor.senec_enfluri_net_potential_p3   | no                 |                                                                |
| Enfluri Net Current Phase 1     | sensor.senec_enfluri_net_current_p1     | no                 |                                                                |
| Enfluri Net Current Phase 2     | sensor.senec_enfluri_net_current_p2     | no                 |                                                                |
| Enfluri Net Current Phase 3     | sensor.senec_enfluri_net_current_p3     | no                 |                                                                |
| Enfluri Net Power Phase 1       | sensor.senec_enfluri_net_power_p1       | no                 |                                                                |
| Enfluri Net Power Phase 2       | sensor.senec_enfluri_net_power_p2       | no                 |                                                                |
| Enfluri Net Power Phase 3       | sensor.senec_enfluri_net_power_p3       | no                 |                                                                |
| Enfluri Usage Frequency         | sensor.senec_enfluri_usage_freq         | no                 |                                                                |
| Enfluri Usage Total Power       | sensor.senec_enfluri_usage_power_total  | no                 |                                                                |
| Enfluri Usage Potential Phase 1 | sensor.senec_enfluri_usage_potential_p1 | no                 |                                                                |
| Enfluri Usage Potential Phase 2 | sensor.senec_enfluri_usage_potential_p2 | no                 |                                                                |
| Enfluri Usage Potential Phase 3 | sensor.senec_enfluri_usage_potential_p3 | no                 |                                                                |
| Enfluri Usage Current Phase 1   | sensor.senec_enfluri_usage_current_p1   | no                 |                                                                |
| Enfluri Usage Current Phase 2   | sensor.senec_enfluri_usage_current_p2   | no                 |                                                                |
| Enfluri Usage Current Phase 3   | sensor.senec_enfluri_usage_current_p3   | no                 |                                                                |
| Enfluri Usage Power Phase 1     | sensor.senec_enfluri_usage_power_p1     | no                 |                                                                |
| Enfluri Usage Power Phase 2     | sensor.senec_enfluri_usage_power_p2     | no                 |                                                                |
| Enfluri Usage Power Phase 3     | sensor.senec_enfluri_usage_power_p3     | no                 |                                                                |
| Module A: Cell Temperature A1   | sensor.senec_bms_cell_temp_a1           | no                 |                                                                |
| Module A: Cell Temperature A2   | sensor.senec_bms_cell_temp_a2           | no                 |                                                                |
| Module A: Cell Temperature A3   | sensor.senec_bms_cell_temp_a3           | no                 |                                                                |
| Module A: Cell Temperature A4   | sensor.senec_bms_cell_temp_a4           | no                 |                                                                |
| Module A: Cell Temperature A5   | sensor.senec_bms_cell_temp_a5           | no                 |                                                                |
| Module A: Cell Temperature A6   | sensor.senec_bms_cell_temp_a6           | no                 |                                                                |
| Module B: Cell Temperature B1   | sensor.senec_bms_cell_temp_b1           | no                 |                                                                |
| Module B: Cell Temperature B2   | sensor.senec_bms_cell_temp_b2           | no                 |                                                                |
| Module B: Cell Temperature B3   | sensor.senec_bms_cell_temp_b3           | no                 |                                                                |
| Module B: Cell Temperature B4   | sensor.senec_bms_cell_temp_b4           | no                 |                                                                |
| Module B: Cell Temperature B5   | sensor.senec_bms_cell_temp_b5           | no                 |                                                                |
| Module B: Cell Temperature B6   | sensor.senec_bms_cell_temp_b6           | no                 |                                                                |
| Module C: Cell Temperature C1   | sensor.senec_bms_cell_temp_c1           | no                 |                                                                |
| Module C: Cell Temperature C2   | sensor.senec_bms_cell_temp_c2           | no                 |                                                                |
| Module C: Cell Temperature C3   | sensor.senec_bms_cell_temp_c3           | no                 |                                                                |
| Module C: Cell Temperature C4   | sensor.senec_bms_cell_temp_c4           | no                 |                                                                |
| Module C: Cell Temperature C5   | sensor.senec_bms_cell_temp_c5           | no                 |                                                                |
| Module C: Cell Temperature C6   | sensor.senec_bms_cell_temp_c6           | no                 |                                                                |
| Module D: Cell Temperature D1   | sensor.senec_bms_cell_temp_d1           | no                 |                                                                |
| Module D: Cell Temperature D2   | sensor.senec_bms_cell_temp_d2           | no                 |                                                                |
| Module D: Cell Temperature D3   | sensor.senec_bms_cell_temp_d3           | no                 |                                                                |
| Module D: Cell Temperature D4   | sensor.senec_bms_cell_temp_d4           | no                 |                                                                |
| Module D: Cell Temperature D5   | sensor.senec_bms_cell_temp_d5           | no                 |                                                                |
| Module D: Cell Temperature D6   | sensor.senec_bms_cell_temp_d6           | no                 |                                                                |
| Module A: Cell Voltage A1       | sensor.senec_bms_cell_volt_a1           | no                 |                                                                |
| Module A: Cell Voltage A2       | sensor.senec_bms_cell_volt_a2           | no                 |                                                                |
| Module A: Cell Voltage A3       | sensor.senec_bms_cell_volt_a3           | no                 |                                                                |
| Module A: Cell Voltage A4       | sensor.senec_bms_cell_volt_a4           | no                 |                                                                |
| Module A: Cell Voltage A5       | sensor.senec_bms_cell_volt_a5           | no                 |                                                                |
| Module A: Cell Voltage A6       | sensor.senec_bms_cell_volt_a6           | no                 |                                                                |
| Module A: Cell Voltage A7       | sensor.senec_bms_cell_volt_a7           | no                 |                                                                |
| Module A: Cell Voltage A8       | sensor.senec_bms_cell_volt_a8           | no                 |                                                                |
| Module A: Cell Voltage A9       | sensor.senec_bms_cell_volt_a9           | no                 |                                                                |
| Module A: Cell Voltage A10      | sensor.senec_bms_cell_volt_a10          | no                 |                                                                |
| Module A: Cell Voltage A11      | sensor.senec_bms_cell_volt_a11          | no                 |                                                                |
| Module A: Cell Voltage A12      | sensor.senec_bms_cell_volt_a12          | no                 |                                                                |
| Module A: Cell Voltage A13      | sensor.senec_bms_cell_volt_a13          | no                 |                                                                |
| Module A: Cell Voltage A14      | sensor.senec_bms_cell_volt_a14          | no                 |                                                                |
| Module B: Cell Voltage B1       | sensor.senec_bms_cell_volt_b1           | no                 |                                                                |
| Module B: Cell Voltage B2       | sensor.senec_bms_cell_volt_b2           | no                 |                                                                |
| Module B: Cell Voltage B3       | sensor.senec_bms_cell_volt_b3           | no                 |                                                                |
| Module B: Cell Voltage B4       | sensor.senec_bms_cell_volt_b4           | no                 |                                                                |
| Module B: Cell Voltage B5       | sensor.senec_bms_cell_volt_b5           | no                 |                                                                |
| Module B: Cell Voltage B6       | sensor.senec_bms_cell_volt_b6           | no                 |                                                                |
| Module B: Cell Voltage B7       | sensor.senec_bms_cell_volt_b7           | no                 |                                                                |
| Module B: Cell Voltage B8       | sensor.senec_bms_cell_volt_b8           | no                 |                                                                |
| Module B: Cell Voltage B9       | sensor.senec_bms_cell_volt_b9           | no                 |                                                                |
| Module B: Cell Voltage B10      | sensor.senec_bms_cell_volt_b10          | no                 |                                                                |
| Module B: Cell Voltage B11      | sensor.senec_bms_cell_volt_b11          | no                 |                                                                |
| Module B: Cell Voltage B12      | sensor.senec_bms_cell_volt_b12          | no                 |                                                                |
| Module B: Cell Voltage B13      | sensor.senec_bms_cell_volt_b13          | no                 |                                                                |
| Module B: Cell Voltage B14      | sensor.senec_bms_cell_volt_b14          | no                 |                                                                |
| Module C: Cell Voltage C1       | sensor.senec_bms_cell_volt_c1           | no                 |                                                                |
| Module C: Cell Voltage C2       | sensor.senec_bms_cell_volt_c2           | no                 |                                                                |
| Module C: Cell Voltage C3       | sensor.senec_bms_cell_volt_c3           | no                 |                                                                |
| Module C: Cell Voltage C4       | sensor.senec_bms_cell_volt_c4           | no                 |                                                                |
| Module C: Cell Voltage C5       | sensor.senec_bms_cell_volt_c5           | no                 |                                                                |
| Module C: Cell Voltage C6       | sensor.senec_bms_cell_volt_c6           | no                 |                                                                |
| Module C: Cell Voltage C7       | sensor.senec_bms_cell_volt_c7           | no                 |                                                                |
| Module C: Cell Voltage C8       | sensor.senec_bms_cell_volt_c8           | no                 |                                                                |
| Module C: Cell Voltage C9       | sensor.senec_bms_cell_volt_c9           | no                 |                                                                |
| Module C: Cell Voltage C10      | sensor.senec_bms_cell_volt_c10          | no                 |                                                                |
| Module C: Cell Voltage C11      | sensor.senec_bms_cell_volt_c11          | no                 |                                                                |
| Module C: Cell Voltage C12      | sensor.senec_bms_cell_volt_c12          | no                 |                                                                |
| Module C: Cell Voltage C13      | sensor.senec_bms_cell_volt_c13          | no                 |                                                                |
| Module C: Cell Voltage C14      | sensor.senec_bms_cell_volt_c14          | no                 |                                                                |
| Module D: Cell Voltage D1       | sensor.senec_bms_cell_volt_d1           | no                 |                                                                |
| Module D: Cell Voltage D2       | sensor.senec_bms_cell_volt_d2           | no                 |                                                                |
| Module D: Cell Voltage D3       | sensor.senec_bms_cell_volt_d3           | no                 |                                                                |
| Module D: Cell Voltage D4       | sensor.senec_bms_cell_volt_d4           | no                 |                                                                |
| Module D: Cell Voltage D5       | sensor.senec_bms_cell_volt_d5           | no                 |                                                                |
| Module D: Cell Voltage D6       | sensor.senec_bms_cell_volt_d6           | no                 |                                                                |
| Module D: Cell Voltage D7       | sensor.senec_bms_cell_volt_d7           | no                 |                                                                |
| Module D: Cell Voltage D8       | sensor.senec_bms_cell_volt_d8           | no                 |                                                                |
| Module D: Cell Voltage D9       | sensor.senec_bms_cell_volt_d9           | no                 |                                                                |
| Module D: Cell Voltage D10      | sensor.senec_bms_cell_volt_d10          | no                 |                                                                |
| Module D: Cell Voltage D11      | sensor.senec_bms_cell_volt_d11          | no                 |                                                                |
| Module D: Cell Voltage D12      | sensor.senec_bms_cell_volt_d12          | no                 |                                                                |
| Module D: Cell Voltage D13      | sensor.senec_bms_cell_volt_d13          | no                 |                                                                |
| Module D: Cell Voltage D14      | sensor.senec_bms_cell_volt_d14          | no                 |                                                                |
| Module A: Voltage               | sensor.senec_bms_voltage_a              | no                 |                                                                |
| Module B: Voltage               | sensor.senec_bms_voltage_b              | no                 |                                                                |
| Module C: Voltage               | sensor.senec_bms_voltage_c              | no                 |                                                                |
| Module D: Voltage               | sensor.senec_bms_voltage_d              | no                 |                                                                |
| Module A: Current               | sensor.senec_bms_current_a              | no                 |                                                                |
| Module B: Current               | sensor.senec_bms_current_b              | no                 |                                                                |
| Module C: Current               | sensor.senec_bms_current_c              | no                 |                                                                |
| Module D: Current               | sensor.senec_bms_current_d              | no                 |                                                                |
| Module A: State of charge       | sensor.senec_bms_soc_a                  | no                 |                                                                |
| Module B: State of charge       | sensor.senec_bms_soc_b                  | no                 |                                                                |
| Module C: State of charge       | sensor.senec_bms_soc_c                  | no                 |                                                                |
| Module D: State of charge       | sensor.senec_bms_soc_d                  | no                 |                                                                |
| Module A: State of Health       | sensor.senec_bms_soh_a                  | no                 |                                                                |
| Module B: State of Health       | sensor.senec_bms_soh_b                  | no                 |                                                                |
| Module C: State of Health       | sensor.senec_bms_soh_c                  | no                 |                                                                |
| Module D: State of Health       | sensor.senec_bms_soh_d                  | no                 |                                                                |
| Module A: Cycles                | sensor.senec_bms_cycles_a               | no                 |                                                                |
| Module B: Cycles                | sensor.senec_bms_cycles_b               | no                 |                                                                |
| Module C: Cycles                | sensor.senec_bms_cycles_c               | no                 |                                                                |
| Module D: Cycles                | sensor.senec_bms_cycles_d               | no                 |                                                                |
| Wallbox Power                   | sensor.senec_wallbox_power              | no                 |                                                                |
| Fan LV-Inverter                 | binary_sensor.senec_fan_inv_lv          | no                 | looks like that lala.cgi currently does not provide valid data |
| Fan HV-Inverter                 | binary_sensor.senec_fan_inv_hv          | no                 | looks like that lala.cgi currently does not provide valid data |
| Wallbox I EV Connected          | sensor.senec_wallbox_1_ev_connected     | no                 |                                                                |
