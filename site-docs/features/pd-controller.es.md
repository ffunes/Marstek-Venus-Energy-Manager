# Controlador PD

El controlador PD (Proporcional-Derivativo) es el núcleo de la integración. Se ejecuta cada **2,5 segundos** y ajusta la potencia de la batería para mantener el flujo de red cercano al objetivo configurado (por defecto, 0 W).

## Algoritmo

```
error = grid_power - target_power

P = Kp × error
D = Kd × (error - error_anterior) / dt

ajuste = P + D
nueva_potencia = potencia_actual + ajuste
```

### Parámetros por defecto

| Parámetro | Valor | Descripción |
|---|---|---|
| `Kp` | `0.65` | Ganancia proporcional |
| `Kd` | `0.5` | Ganancia derivativa |
| Deadband | `±40 W` | Zona muerta: ignora errores pequeños |
| Rate limit | `±500 W/ciclo` | Límite de cambio por ciclo |

## Mecanismos de estabilización

### Deadband (zona muerta)

Si el error es menor de ±40 W, el controlador no ajusta la potencia. Evita micro-oscilaciones continuas por ruido del sensor.

### Rate limiting

El cambio de potencia se limita a ±500 W por ciclo para suavizar las transiciones y proteger la batería de cambios bruscos.

### Detección de oscilaciones

El controlador monitoriza reversiones de dirección (carga↔descarga) frecuentes. Si detecta oscilación sostenida, reduce temporalmente la ganancia efectiva.

### Histéresis direccional

Evita cambios de dirección por variaciones de carga momentáneas (como el arranque de electrodomésticos). El controlador requiere que el error supere un umbral durante varios ciclos antes de cambiar de carga a descarga o viceversa.

## Exclusión por función de reserva

Una batería queda excluida del controlador PD cuando se cumplen **las dos** condiciones siguientes:

1. El switch **Función de reserva** (`switch.*_backup_function`) está activado.
2. El sensor **Potencia AC offgrid** (`sensor.*_ac_offgrid_power`) reporta un valor distinto de 0 W, lo que confirma que la batería está proporcionando energía offgrid activamente.

Tener el switch activado por sí solo no es suficiente. Si el switch está activo pero la potencia AC offgrid lee 0 W (la batería no está sirviendo ninguna carga offgrid), la batería sigue participando en el control PD con normalidad.

Mientras está excluida, el controlador no envía ningún comando de potencia, cambio de modo forzado ni escritura de registros de configuración. La batería sigue siendo consultada con normalidad, por lo que todos los sensores de solo lectura (SOC, potencia, temperatura, etc.) se mantienen actualizados.

### Cooldown post-backup

Cuando la carga offgrid vuelve a 0 W, la batería no se reincorpora inmediatamente al control PD. Se aplica un **cooldown de 5 minutos** que mantiene la batería excluida tras el fin del evento de reserva, evitando enviar comandos de escritura a una batería que puede estar aún estabilizándose.

Desactivar el switch de **Función de reserva** elimina el cooldown de forma inmediata.

!!! info
    La exclusión también aplica a las escrituras de registro de la carga semanal completa y a la secuencia de apagado.

## Potencia objetivo por franja

Cada [franja horaria](../configuration/time-slots.md) puede tener su propia **potencia objetivo de red** (`target_grid_power`), permitiendo distintas estrategias según el momento del día.

![Entidades del controlador PD en Home Assistant](../assets/screenshots/features/pd-controller-entities.png){ width="700"  style="display: block; margin: 0 auto;"}
