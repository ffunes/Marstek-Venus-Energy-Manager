# Balance Neto Horario

Registra la importación y exportación de red dentro de cada hora civil y ajusta el punto de trabajo del controlador PD en tiempo real para llevar la energía neta hacia un objetivo configurable. El objetivo por defecto es 0 Wh — balance neto cero cada hora — aunque puede desplazarse para permitir una importación fija o apuntar a una exportación fija.

## Cómo funciona

En cada ciclo del controlador PD (~2,5 s), el gestor:

1. Acumula importación y exportación de red para la hora civil actual.
2. Calcula el déficit respecto al objetivo: `déficit = objetivo_neto_Wh − (imp_Wh − exp_Wh)`.
3. Deriva una corrección de potencia: `offset = déficit / horas_restantes`.
4. Aplica un ramp-in de 5 minutos al inicio de cada hora para evitar correcciones agresivas tempranas.
5. Limita el offset al máximo configurado.
6. Aplica una histéresis configurable (por defecto 15 W): el offset solo se actualiza si cambia más de este umbral (omitida durante los últimos 10 minutos de la hora para que la hora se cierre con precisión).
7. Registra el offset mediante el registro de puntos de trabajo para que se combine correctamente con otras funcionalidades.

El offset se elimina automáticamente cuando:

- La hora actual está fuera de todas las [franjas horarias de descarga](../configuration/time-slots.md) configuradas (o se aplica 24/7 si no hay franjas definidas).
- El modo manual está activo.

## Fuente de datos

Por defecto, la integración integra el sensor de potencia de red mediante la regla trapezoidal. Si existe un sensor llamado `sensor.balance_neto` en Home Assistant, se usa en su lugar. La detección es automática:

| Tipo de sensor | Unidad | `state_class` | Método |
|---|---|---|---|
| Energía acumulada | kWh / Wh | `total` o `total_increasing` | Snapshot al inicio de hora, delta por ciclo |
| Energía instantánea | kWh / Wh | `measurement` | Lectura directa |
| Potencia | W / kW | cualquiera | Integración trapezoidal |

Si el sensor externo queda no disponible, la integración vuelve al método trapezoidal automáticamente. La fuente activa es visible en el atributo `source` del sensor Balance Neto.

La lista de candidatos se define en `const.py → EXTERNAL_NET_BALANCE_CANDIDATES`. Convención de signo: **positivo = exportación neta a la red**.

## Prioridad y composición

El offset de balance horario se registra como **offset aditivo** en el registro de puntos de trabajo (clave `hourly_balance`). Se suma a la preferencia de potencia objetivo del usuario y a cualquier otro offset aditivo. La Protección de Capacidad utiliza una anulación absoluta (prioridad 10) y toma el control total cuando está activa.

## Bloqueo de compensación

Ciertas condiciones impiden que el offset se aplique. El atributo `charge_block_reason` del sensor Balance Neto muestra el motivo:

| Motivo | Significado |
|---|---|
| `solar_charge_delay` | El retraso de carga solar está activo — se bloquean las correcciones de importación y exportación |
| `hysteresis` | La histéresis de carga está activa — solo se bloquea la corrección de importación |
| `max_soc` | Todas las baterías están al SOC máximo — solo se bloquea la corrección de importación |

Mientras está bloqueado, el acumulador sigue registrando para que el offset correcto se aplique en cuanto desaparezca el bloqueo.

## Sensor Balance Neto

Cuando la funcionalidad está activada, se crea un único sensor de diagnóstico (`sensor.*_balance_neto`).

**Estado**: kWh neto de la hora actual (positivo = exportación neta, negativo = importación neta).

**Atributos**:

| Atributo | Descripción |
|---|---|
| `status` | `idle`, `out_of_slot`, `capped`, `compensating_import`, `compensating_export`, `compensation_stopped` |
| `offset_w` | Corrección de punto de trabajo activa en vatios |
| `imp_wh` | Importación de red acumulada en la hora actual |
| `exp_wh` | Exportación de red acumulada en la hora actual |
| `target_net_wh` | Objetivo configurado en Wh |
| `remaining_min` | Minutos restantes en la hora actual |
| `source` | ID de entidad del sensor usado, o `trapezoidal` |
| `hour_iso` | Timestamp ISO del inicio de la hora actual |
| `charge_block_reason` | Solo presente cuando la compensación está bloqueada; indica el motivo |

## Configuración

Activa y configura desde **Configuración → Dispositivos y Servicios → Marstek Venus Energy Manager → Configurar → Balance neto horario**.

| Parámetro | Por defecto | Descripción |
|---|---|---|
| Balance neto objetivo (kWh) | `0.0` | Energía neta objetivo por hora. `0` = balance neto cero. Positivo = permite importación neta. Negativo = apunta a exportación neta. |
| Offset máximo (W) | `1000` | Corrección de potencia máxima que puede aplicar el controlador. |
| Tolerancia de balance neto (kWh) | `0.0` | Banda muerta: sin corrección cuando el balance neto está dentro de ±N kWh del objetivo. `0` = corrección exacta. |
| Histéresis del desplazamiento (W) | `15` | Cambio mínimo en el desplazamiento necesario para aplicar una nueva corrección. Evita micro-ajustes cada ciclo. `0` = actualizar siempre. |

## Persistencia

El estado se persiste en el almacenamiento de Home Assistant cada ~5 minutos y al descargar la integración. Al reiniciar, los acumuladores de la hora actual se restauran solo si el reinicio se produjo en la misma hora civil.
