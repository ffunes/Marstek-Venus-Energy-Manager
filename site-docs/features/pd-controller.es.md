# Controlador PD

El controlador PD (Proporcional-Derivativo) es el núcleo de la integración. Se ejecuta **dirigido por eventos** —recalcula cada vez que el sensor de consumo de red publica un valor nuevo— y ajusta la potencia de la batería para mantener el flujo de red cercano al objetivo configurado (por defecto, 0 W).

## Algoritmo

```
error = grid_power - target_power

P = Kp × error
D = Kd × (error - error_anterior) / dt

ajuste = P + D
nueva_potencia = potencia_actual + ajuste
```

Como el lazo es dirigido por eventos (cadencia variable), el término `P` y el límite de rampa se escalan internamente por el tiempo real transcurrido entre actualizaciones del sensor, de modo que el ajuste se comporta igual independientemente de la rapidez con que publique tu sensor.

### Parámetros por defecto

| Parámetro | Valor | Descripción |
|---|---|---|
| `Kp` | `0.65` | Ganancia proporcional |
| `Kd` | `0.5` | Ganancia derivativa |
| Deadband | `±40 W` | Zona muerta: ignora errores pequeños |
| Rate limit | `±800 W/ciclo` | Límite de cambio por ciclo |

## Cadencia de control

El controlador es **dirigido por eventos**: recalcula en el instante en que el sensor de consumo de red publica un valor nuevo, por lo que reacciona a la cadencia nativa del sensor (a menudo una vez por segundo) en lugar de esperar a un tick de temporizador fijo.

En paralelo corre un **watchdog de 2 segundos**. Mientras el sensor se actualiza con normalidad casi no hace nada —el evento ya procesó el último valor—; su función es mantener en marcha los subsistemas basados en tiempo y forzar una **recálculo de seguridad si el sensor se queda en silencio** (tras ~30 s sin actualizaciones el controlador reevalúa en vez de mantener el último comando indefinidamente).

Un lock evita ejecuciones solapadas: si un ciclo sigue en curso cuando se dispara el siguiente trigger, ese trigger se descarta (el ciclo en curso ya lee el estado actual). Así las escrituras Modbus a la batería quedan serializadas.

## Mecanismos de estabilización

### Deadband (zona muerta)

Si el error es menor de ±40 W, el controlador no ajusta la potencia. Evita micro-oscilaciones continuas por ruido del sensor.

### Rate limiting

El cambio de potencia se limita por ciclo para suavizar las transiciones y proteger la batería de cambios bruscos. Un «ciclo» es una actualización de control, que se dispara con cada valor nuevo del sensor. El límite por ciclo configurado se escala internamente por el tiempo real transcurrido entre actualizaciones, de modo que la tasa efectiva de rampa (W/s) se mantiene constante independientemente de la rapidez con que publique el sensor. Baja el límite si la respuesta se siente brusca.

### Detección de oscilaciones

El controlador monitoriza reversiones de dirección (carga↔descarga) frecuentes. Si detecta oscilación sostenida, reduce temporalmente la ganancia efectiva.

### Histéresis direccional

Evita cambios de dirección por variaciones de carga momentáneas (como el arranque de electrodomésticos). El controlador requiere que el error supere un umbral durante varios ciclos antes de cambiar de carga a descarga o viceversa.

### Filtrado del término derivativo

El término derivativo se filtra con un paso-bajo (constante de tiempo corta) antes de llegar a la salida. Derivar una señal de red apenas suavizada amplificaría el ruido de cuantización del medidor y el PWM del inversor, inyectándolo en la potencia de la batería; el filtrado mantiene el derivativo útil sin ese ruido.

### Anti-windup por potencia medida

El controlador asume que cada batería entrega exactamente la potencia comandada. Cuando no puede —por ejemplo por reducción (taper) de SOC/voltaje o por retardo de rampa—, el controlador detecta el déficit sostenido comparando el comando con la potencia AC medida y reancla su línea base interna a la realidad. Así evita que la salida de control «se acumule» (windup) por encima de lo que el hardware entregó realmente, lo que de otro modo causaría un sobreimpulso o una breve exportación a red cuando la carga baja después.

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
