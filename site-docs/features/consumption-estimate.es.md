# Estimación del consumo diario

La carga predictiva necesita saber cuánta energía consume tu hogar cada día para decidir si hace falta cargar desde la red. En lugar de usar un valor fijo, la integración calcula un **consumo estimado dinámico** a partir del historial real de los últimos 7 días.

---

## Qué mide el consumo estimado

El estimado es el **consumo total del hogar durante la ventana solar+batería** — las horas fuera de la franja de carga de red, cuando se espera que la batería cubra la casa. Se promedia sobre los últimos 7 días.

### Origen del consumo del hogar

La potencia del hogar de cada ciclo se **deriva** de los valores que la integración ya tiene:

```
hogar = red + Σ(potencia AC de baterías) + solar
```

Es el mismo valor que muestra el diagrama de flujo de energía y el sensor **`sensor.marstek_venus_system_home_consumption`** (Consumo de la Casa, W). La FV acoplada en DC (MPPT) no aparece aquí — ya está neteada en la potencia AC de cada batería en el inversor.

!!! note "Sensor de hogar heredado"
    Un `household_consumption_sensor` guardado en una instalación antigua se lee directamente **en vez** de derivar, pero **solo cuando no hay sensor de producción solar configurado** — con sensor solar, el valor derivado es exacto y preferido. El campo ya no se ofrece en la configuración.

### Dispositivos excluidos / adicionales

Si has configurado [dispositivos excluidos o adicionales](excluded-devices.md), la potencia del hogar se corrige antes de acumular:

- **Excluido** (`included_in_consumption = true`): el dispositivo ya está en la lectura del hogar/red pero la batería no debe alimentarlo → su potencia se **resta**.
- **Adicional** (`included_in_consumption = false`): el dispositivo no es visible para la lectura del hogar pero la batería sí debe cubrirlo → su potencia se **suma**.

---

## Acumulación en tiempo real

En cada ciclo de control (dirigido por eventos, a la cadencia del sensor de red), la potencia del hogar se integra en un acumulador diario **solo mientras `is_in_consumption_window()` es verdadero**: las 24 horas completas si no hay franja de carga configurada, o las horas fuera de la franja de carga en los días de la franja. Este acotamiento garantiza que la ventana medida coincide con lo que la carga predictiva espera al proyectar después la demanda restante.

```
incremento (kWh) = potencia_hogar (W) × Δt (s) / 3 600 000
```

`Δt` es el tiempo real transcurrido desde la muestra anterior, así se adapta a la cadencia variable. El valor diario en curso se expone como el atributo `household_consumption_battery_window_kwh` en `binary_sensor.marstek_venus_system_predictive_charging_active`, y se persiste para sobrevivir reinicios dentro del mismo día.

---

## Captura diaria a las 23:55

Cada día a las **23:55 (hora local)** la integración guarda una instantánea del acumulador en el historial de 7 días antes de que se resetee a medianoche. El valor solo se almacena si es ≥ 1,5 kWh (para descartar días sin datos significativos).

---

## Historial de 7 días

La integración mantiene un historial rodante de las últimas **7 entradas** con formato `(fecha, kWh)`, persistido en disco para sobrevivir reinicios de Home Assistant.

### Valor de reserva

Mientras no haya 7 días reales acumulados (p. ej. recién instalada la integración), las entradas que falten se rellenan con el valor de reserva **`DEFAULT_BASE_CONSUMPTION_KWH = 5,0 kWh`**. Actúa solo como marcador temporal y se reemplaza en cuanto hay datos reales disponibles.

### Backfill desde el historial del recorder

Al arrancar, la integración recupera los días que falten consultando el **recorder de Home Assistant** para el sensor `sensor.marstek_venus_system_home_consumption` (que ya resuelve al valor derivado, o al sensor de hogar heredado cuando aplica). Para cada día que falte integra el historial de ese sensor sobre la ventana de consumo, aplica los ajustes de dispositivos excluidos/adicionales, y almacena el resultado igual que haría la captura de las 23:55. Así el historial se construye con datos reales incluso tras un reinicio de HA o una instalación nueva.

---

## Media móvil de 7 días

El consumo estimado que usa la carga predictiva es la **media aritmética** de todos los valores del historial:

```
consumo_esperado = Σ(consumo_i) / n días
```

donde `n` puede ser menor de 7 si aún no hay suficientes días reales (los valores de reserva también cuentan en el promedio hasta ser reemplazados).

---

## Ejemplo completo

```
Lunes:     consumo del hogar (ventana batería) = 5,0 kWh
Martes:    consumo del hogar (ventana batería) = 5,1 kWh
Miércoles: consumo del hogar (ventana batería) = 5,3 kWh
Jueves:    consumo del hogar (ventana batería) = 4,8 kWh
Viernes:   consumo del hogar (ventana batería) = 4,9 kWh
Sábado:    consumo del hogar (ventana batería) = 6,3 kWh
Domingo:   consumo del hogar (ventana batería) = 6,0 kWh

Consumo esperado = (5,0 + 5,1 + 5,3 + 4,8 + 4,9 + 6,3 + 6,0) / 7 = 5,34 kWh
```

---

## Sensor de diagnóstico

| Sensor | Descripción | Reset |
|---|---|---|
| `sensor.marstek_venus_system_daily_grid_at_min_soc_energy` | Energía importada de la red mientras todas las baterías estaban en SOC mínimo dentro de una franja de descarga — demanda del hogar que la batería no pudo cubrir | Medianoche (hora local) |

Este sensor **Grid at Min SOC** es informativo: muestra la demanda que la batería no atendió por estar vacía. Ya **no** se suma al consumo estimado (el consumo del hogar derivado ya captura la carga total de la casa, incluida la parte servida desde la red).

El sensor `binary_sensor.marstek_venus_system_predictive_charging_active` expone en sus atributos el historial de consumo de los últimos 7 días y el número de entradas reales vs. valores de reserva, útil para verificar el estado del aprendizaje.

![Atributos del historial de consumo en HA](../assets/screenshots/features/consumption-estimate-attributes.png){ width="700"  style="display: block; margin: 0 auto;"}
