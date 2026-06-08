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
| `sensor.*_alarm_status` | Condiciones de alarma activas (v2) — diagnóstico | texto |
| `sensor.*_fault_status` | Condiciones de fallo activas (v2) — diagnóstico | texto |

## Sensores del monitor de equilibrio de celdas (por batería)

Solo presentes cuando el [monitor de equilibrio de celdas](../features/cell-balance-monitor.md) está activado en la configuración de carga semanal completa.

| Entidad | Descripción | Unidad |
|---|---|---|
| `sensor.*_cell_delta` | Diferencia de tensión entre la celda máxima y mínima en la última lectura OCV | mV |
| `sensor.*_balance_status` | Resultado del equilibrio: `green` / `yellow` / `orange` / `red` | — |
| `sensor.*_delta_trend` | Tendencia en las últimas lecturas formales: `rising` / `stable` / `falling` | — |
| `sensor.*_last_balance_read` | Marca de tiempo de la última lectura | timestamp |
| `sensor.*_delta_avg_4w` | Media de las últimas 4 lecturas formales | mV |

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
| `number.marstek_venus_system_system_max_charge_power` | Límite opcional de carga combinada para todo el sistema (`0 W` = desactivado). Solo se crea cuando los límites del sistema están activados. | 0–15000 W |
| `number.marstek_venus_system_system_max_discharge_power` | Límite opcional de descarga combinada para todo el sistema (`0 W` = desactivado). Solo se crea cuando los límites del sistema están activados. | 0–15000 W |

## Selectores

| Entidad | Opciones |
|---|---|
| `select.*_force_mode` | None / Charge / Discharge |
| `select.marstek_venus_system_pd_tuning_profile` | Muy suave / Suave / Equilibrado / Agresivo / Personalizado — presets de PD de un clic que fijan `Kp`, `Kd` y el límite de rampa a la vez (el deadband lo controla el usuario) |

## Switches

| Entidad | Descripción |
|---|---|
| `switch.*_rs485_control` | Modo control RS485 |
| `switch.*_allow_charge` | Control de software que permite que esta batería participe en la carga automática |
| `switch.*_allow_discharge` | Control de software que permite que esta batería participe en la descarga automática |
| `switch.*_backup_function` | Función de reserva — cuando está activo **y** la potencia AC offgrid ≠ 0 W, la batería queda excluida del control PD (no se envían comandos de escritura) |
| `switch.marstek_venus_system_override_predictive_charging` | Cancelar carga predictiva |

## Botones

| Entidad | Descripción |
|---|---|
| `button.*_reset` | Reset del dispositivo |

## Sensores del sistema

### Estado de la integración

`sensor.marstek_venus_system_integration_status` muestra de un vistazo qué está haciendo la integración en cada momento. Refleja el modo activo de mayor prioridad:

| Estado | Descripción |
|---|---|
| `Charging from Grid` | Carga predictiva desde la red activa |
| `Weekly Full Charge` | Cargando al 100 % para equilibrado de celdas |
| `Charge Delayed` | Carga bloqueada, esperando el momento óptimo según previsión solar |
| `Waiting for Solar` | Retraso de carga: esperando que comience la producción solar |
| `Charging to Setpoint` | Retraso de carga: cargando hasta el SOC mínimo configurado |
| `Capacity Protection` | Descarga limitada por SOC bajo (peak shaving activo) |
| `No-Discharge Window` | Dentro de una franja horaria sin descarga configurada |
| `Charging` | Cargando (excedente solar u otro) |
| `Discharging` | Descargando para cubrir el consumo del hogar |
| `Standby` | Sistema equilibrado dentro de la banda muerta, sin acción necesaria |
| `Manual Mode` | Modo manual activo — la integración no envía comandos automáticos |
| `Initializing` | Primer ciclo del controlador aún no completado |

El sensor también expone diagnósticos del registro de bloqueos como atributos:

| Atributo | Descripción |
|---|---|
| `charge_blocked` | `true` cuando la carga está bloqueada de forma efectiva en todo el sistema, por un bloqueo global o porque todas las baterías conocidas tienen la carga bloqueada |
| `discharge_blocked` | `true` cuando la descarga está bloqueada de forma efectiva en todo el sistema, por un bloqueo global o porque todas las baterías conocidas tienen la descarga bloqueada |
| `charge_blockers` | Bloqueos globales de carga activos con motivo, detalles y marca temporal |
| `discharge_blockers` | Bloqueos globales de descarga activos con motivo, detalles y marca temporal |
| `battery_charge_blockers` | Bloqueos de carga activos por batería, agrupados por batería, incluyendo permitir carga, SOC máximo e histéresis de carga |
| `battery_discharge_blockers` | Bloqueos de descarga activos por batería, agrupados por batería, incluyendo permitir descarga y SOC mínimo |

### Calidad de control PD

`sensor.marstek_venus_system_pd_control_quality` indica cómo de bien mantiene el controlador PD el objetivo de red, para que se vea el efecto de un [perfil de ajuste](../features/pd-controller.md#perfiles-de-ajuste) o un cambio de slider. El estado es un veredicto:

| Estado | Significado |
|---|---|
| `stable` | El PD sigue bien el objetivo |
| `oscillating` | Cabeceo — usa un perfil más suave o sube el deadband |
| `sluggish` | Demasiado lento — usa un perfil más agresivo |
| `battery_limited` | Batería llena/vacía o en su límite de potencia; el PD no puede actuar (no es problema de ajuste) |
| `collecting_data` | Calentando |

Atributos: `rms_error_w` (error medio de seguimiento), `oscillation_per_min`, los `kp` / `kd` / `deadband_w` / `max_power_change_w` activos, y `active_profile`. La métrica es una media móvil de 60 s y se pausa brevemente tras un cambio de objetivo y mientras está limitada por batería, así que espera 1–2 min tras un cambio.

### Sensores agregados

Disponibles bajo el prefijo `sensor.marstek_venus_system_*`, suman los valores de todas las baterías:

- `system_battery_power` — Potencia total del sistema
- `system_battery_soc` — SOC promedio del sistema
- `system_total_charging_energy` — Energía total cargada (sistema)
- `system_total_discharging_energy` — Energía total descargada (sistema)
- `grid_at_min_soc` — Importación de red durante periodos en SOC mínimo (kWh)
- `system_alarm_status` — Estado de alarma agregado de todas las baterías (`OK` / `Warning` / `Fault`); los atributos listan las condiciones activas por batería
- `system_home_consumption` — Consumo instantáneo del hogar (W). Lee el sensor del hogar si está configurado, en caso contrario lo deriva de `red + AC de baterías + solar`.
- `system_daily_home_energy` — Consumo del hogar de hoy (kWh), integrado del valor de Consumo de la Casa anterior. Se reinicia a medianoche (hora local).

### Resumen de Configuración

`sensor.marstek_venus_system_configuration_summary` es un sensor diagnóstico oculto pensado para informes de soporte. Expone atributos de configuración sin direcciones IP ni puertos de las baterías.

Los atributos relevantes para límites de potencia son:

| Atributo | Descripción |
|---|---|
| `total_max_charge_power_W` | Suma de los límites de carga configurados por batería |
| `total_max_discharge_power_W` | Suma de los límites de descarga configurados por batería |
| `system_power_limits_enabled` | Indica si los límites globales de potencia están activados |
| `system_max_charge_power_W` | Límite global de carga configurado (`0` = desactivado) |
| `system_max_discharge_power_W` | Límite global de descarga configurado (`0` = desactivado) |
| `effective_total_max_charge_power_W` | Capacidad total de carga tras aplicar el límite global |
| `effective_total_max_discharge_power_W` | Capacidad total de descarga tras aplicar el límite global |

![Lista de entidades en Home Assistant](../assets/screenshots/reference/entities-list.png){ width="700"  style="display: block; margin: 0 auto;"}
