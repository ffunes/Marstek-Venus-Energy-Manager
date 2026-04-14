# Exclusión de cargas

Ver [Dispositivos excluidos](../configuration/excluded-devices.md) para la configuración.

## Cómo funciona internamente

Cuando un dispositivo excluido está activo, el controlador resta su potencia del consumo de red antes de calcular el ajuste del controlador PD:

```
consumo_efectivo = consumo_red - potencia_excluida
error = consumo_efectivo - target_grid_power
```

Esto hace que la batería "ignore" esa carga y no intente compensarla.

### Si el dispositivo NO está incluido en el sensor principal

La integración **suma** la potencia del dispositivo excluido al consumo de red medido (porque el sensor principal no la ve) y luego la resta, resultando en el mismo consumo efectivo neto.

## Opción "Permitir excedente solar"

Cuando está activa, si el sistema opera con excedente solar (la batería está cargando por excedente), la exclusión no se aplica para la parte de carga. En otras palabras: la batería no cargará para compensar el consumo de este dispositivo cuando ya hay excedente solar disponible.

Esta opción es la base para la **prioridad batería vs. carga del VE**:

| Modo | ¿La batería carga con solar? | ¿La batería descarga para el dispositivo? |
|---|---|---|
| Excluido, excedente OFF | Sí | No |
| Excluido, excedente ON | **No** — el solar va primero al dispositivo | No |

### Switch de excedente solar (control en tiempo real)

Cada dispositivo excluido dispone de una entidad switch **Solar Surplus** dedicada que permite cambiar este comportamiento en tiempo real sin reconfigurar la integración. Úsalo en automatizaciones de HA para cambiar la prioridad dinámicamente:

```yaml
# Ejemplo: priorizar el VE cuando está conectado
automation:
  trigger:
    - platform: state
      entity_id: binary_sensor.ev_conectado
      to: "on"
  action:
    - service: switch.turn_on
      target:
        entity_id: switch.solar_surplus_wallbox_power
```

![Sensor de potencia de dispositivo excluido en HA](../assets/screenshots/features/load-exclusion-entities.png){ width="700"  style="display: block; margin: 0 auto;"}

## Cargador VE sin telemetría de potencia

Para cargadores VE que solo exponen un sensor de estado (sin lectura de potencia en tiempo real), existe la opción **Cargador VE sin telemetría de potencia**. En lugar de leer vatios, el controlador monitoriza el estado del sensor y reacciona ante cualquier cadena de carga (`Charging`, `Cargando`, etc.).

| Fase | Comportamiento de la batería |
|---|---|
| Estado VE → Cargando (primeros 5 min) | 0 W — carga y descarga bloqueadas, estado PD congelado |
| VE cargando (después de 5 min) | Se permite cargar con excedente solar; descarga siempre bloqueada |
| Estado VE → cualquier otro valor | Operación normal |

Ver [Cargador VE sin telemetría de potencia](../configuration/excluded-devices.md#cargador-ve-sin-telemetría-de-potencia) en la referencia de configuración para los detalles de configuración.
