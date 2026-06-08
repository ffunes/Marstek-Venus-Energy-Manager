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
| `Kp` | `0.35` | Ganancia proporcional |
| `Kd` | `0.3` | Ganancia derivativa |
| Deadband | `±40 W` | Zona muerta: ignora errores pequeños |
| Rate limit | `±800 W/ciclo` | Límite de cambio por ciclo |

!!! note "Defaults rebajados"
    `Kp`/`Kd` se rebajaron de `0.65`/`0.5` a `0.35`/`0.3` para frenar el sobreimpulso bajo el lazo dirigido por eventos. Las instalaciones que sigan en los defaults antiguos se migran automáticamente; los valores ajustados a mano se respetan.

## Perfiles de ajuste

En vez de ajustar las ganancias a mano, elige un **perfil de ajuste** (`select.*_pd_tuning_profile`): un preset de un clic que fija `Kp`, `Kd` y el límite de rampa a la vez. Ordenados de más suave a más rápido:

| Perfil | Kp | Kd | Rate limit | Cuándo |
|---|---|---|---|---|
| Muy suave | 0.22 | 0.15 | 400 W | Medidor ruidoso, cero cabeceo; calmo pero lento |
| Suave | 0.30 | 0.25 | 600 W | Conservador |
| Equilibrado | 0.35 | 0.30 | 800 W | Por defecto — vale para la mayoría |
| Agresivo | 0.55 | 0.45 | 1200 W | Medidor limpio, respuesta rápida |
| Personalizado | — | — | — | Manual: ajusta tú los sliders |

- Elegir un perfil escribe sus tres ganancias y las recarga en caliente (sin reinicio).
- Mover a mano cualquiera de esos tres sliders pasa el perfil a **Personalizado** automáticamente; tu valor se conserva.
- **El deadband no forma parte de los perfiles.** Es tu preferencia de precisión / ruido del medidor *y* la referencia contra la que mide el sensor de calidad, así que queda como un slider aparte que controlas tú. Cambiarlo no cambia el perfil activo.

En el dashboard, el selector de perfil y el sensor de calidad están al principio de la sección **Controlador PD** de la pestaña Control.

## Sensor de calidad de control

`sensor.marstek_venus_system_pd_control_quality` muestra de un vistazo cómo de bien mantiene el PD el objetivo de red, para que veas el efecto de un cambio de perfil/slider en vez de adivinar.

El **estado es un veredicto**, no un número:

| Estado | Significado | Qué hacer |
|---|---|---|
| Estable | El PD sigue bien el objetivo | Nada |
| Oscilando | Cabeceo (carga↔descarga frecuente) | Usa un perfil más suave, o sube el deadband |
| Lento | Demasiado lento para alcanzar | Usa un perfil más agresivo |
| Limitado por batería | Batería llena/vacía o en su límite de potencia — el PD no puede actuar | No es problema de ajuste |
| Recopilando datos | Calentando (recién arrancado) | Espera |

Los atributos llevan las cifras crudas: `rms_error_w` (error medio de seguimiento), `oscillation_per_min`, las ganancias activas y `active_profile`.

**Cómo ajustar:**

1. Mira el veredicto (y `rms_error_w`).
2. `Oscilando` → baja un perfil (Agresivo → Equilibrado → Suave). `Lento` → sube.
3. Espera **1–2 minutos** — la métrica es una media móvil de 60 s, así que va con retraso.
4. Repite hasta `Estable`.

La métrica es robusta frente a lecturas falsas: se pausa brevemente tras cualquier cambio de objetivo (balance neto horario, protección de capacidad, cambio manual de objetivo…) y mientras la batería está limitada, para no inflar la lectura.

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
