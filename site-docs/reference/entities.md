# Entidades de Home Assistant

La integración crea automáticamente entidades para cada batería configurada y sensores agregados del sistema completo.

## Sensores (por batería)

| Entidad | Descripción | Unidad |
|---|---|---|
| `sensor.*_battery_soc` | Estado de carga | % |
| `sensor.*_battery_power` | Potencia actual | W |
| `sensor.*_battery_voltage` | Tensión | V |
| `sensor.*_battery_current` | Corriente | A |
| `sensor.*_battery_temperature` | Temperatura | °C |
| `sensor.*_total_charging_energy` | Energía total cargada | kWh |
| `sensor.*_total_discharging_energy` | Energía total descargada | kWh |
| `sensor.*_battery_cycle_count` | Ciclos (registros, v3/vA/vD) | — |
| `sensor.*_battery_cycle_count_calc` | Ciclos calculados (todos) | — |
| `sensor.*_max_cell_voltage` | Tensión máx. de celda (v3/vA/vD) | V |
| `sensor.*_min_cell_voltage` | Tensión mín. de celda (v3/vA/vD) | V |

## Sensores de información de dispositivo

| Entidad | Descripción |
|---|---|
| `sensor.*_device_name` | Nombre del dispositivo |
| `sensor.*_sn_code` | Número de serie |
| `sensor.*_software_version` | Versión de firmware |
| `sensor.*_bms_version` | Versión BMS |
| `sensor.*_mac_address` | Dirección MAC |

## Sensores binarios

| Entidad | Descripción |
|---|---|
| `binary_sensor.*_wifi_status` | Estado WiFi |
| `binary_sensor.*_cloud_status` | Estado Cloud |
| `binary_sensor.marstek_venus_system_predictive_charging_active` | Carga predictiva activa (sistema) |

## Números (sliders)

| Entidad | Descripción | Rango |
|---|---|---|
| `number.*_max_soc` | SOC máximo | 0–100 % |
| `number.*_min_soc` | SOC mínimo | 0–100 % |
| `number.*_max_charge_power` | Potencia máx. de carga | W |
| `number.*_max_discharge_power` | Potencia máx. de descarga | W |

## Selectores

| Entidad | Opciones |
|---|---|
| `select.*_force_mode` | None / Charge / Discharge |

## Switches

| Entidad | Descripción |
|---|---|
| `switch.*_rs485_control` | Modo control RS485 |
| `switch.*_backup_function` | Función de reserva — cuando está activo **y** la potencia AC offgrid ≠ 0 W, la batería queda excluida del control PD (no se envían comandos de escritura) |
| `switch.marstek_venus_system_override_predictive_charging` | Cancelar carga predictiva |

## Botones

| Entidad | Descripción |
|---|---|
| `button.*_reset` | Reset del dispositivo |

## Sensores agregados del sistema

Disponibles bajo el prefijo `sensor.marstek_venus_system_*`, suman los valores de todas las baterías:

- `system_battery_power` — Potencia total del sistema
- `system_battery_soc` — SOC promedio del sistema
- `system_total_charging_energy` — Energía total cargada (sistema)
- `system_total_discharging_energy` — Energía total descargada (sistema)
- `grid_at_min_soc` — Importación de red durante periodos en SOC mínimo (kWh)

![Lista de entidades en Home Assistant](../assets/screenshots/reference/entities-list.png){ width="700"  style="display: block; margin: 0 auto;"}
