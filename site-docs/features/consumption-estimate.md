# Estimación del consumo diario

La carga predictiva necesita saber cuánta energía consume tu hogar cada día para decidir si hace falta cargar desde la red. En lugar de usar un valor fijo, la integración calcula un **consumo estimado dinámico** a partir del historial real de los últimos 7 días.

---

## Qué mide el consumo estimado

El consumo estimado de un día es la suma de dos componentes:

```
Consumo del día = Descarga real de la batería + Demanda insatisfecha (red a min SOC)
```

### 1. Descarga real de la batería

La energía que la batería ha descargado durante el día, leída directamente de los coordinadores de cada batería (`total_daily_discharging_energy`). Este valor se resetea a medianoche según el reloj interno de la batería.

### 2. Demanda insatisfecha — Red a SOC mínimo

Cuando **todas las baterías están al SOC mínimo** y ya no pueden descargar más, el hogar tiene que tirar de la red para cubrir su consumo. Esa energía importada de la red es consumo real del hogar que la batería no pudo atender.

La integración la acumula en tiempo real cada ciclo del controlador (~2,5 s) mientras se cumplan estas condiciones simultáneamente:

| Condición | Detalle |
|---|---|
| Todas las baterías en SOC mínimo | Ninguna batería disponible para descargar |
| No hay carga de red activa | El sistema no está en modo carga predictiva/precio dinámico |
| Dentro de una franja de descarga | Hay una franja activa, o no hay franjas configuradas |
| La red está importando | El sensor de red lee un valor positivo |

Cuando se cumplen todas las condiciones, el acumulador crece proporcionalmente a la importación de red:

```
incremento (kWh) = potencia_red (W) × 2,5 s / 3 600 000
```

Este acumulador se expone como el sensor **`Grid at Min SOC`** (kWh) y se resetea a medianoche.

---

## Captura diaria a las 23:55

Cada día a las **23:55 (hora local)** la integración guarda el consumo del día calculando:

```
valor_del_día = descarga_batería_acumulada + grid_at_min_soc_acumulado
```

El valor solo se almacena si es ≥ 1,5 kWh (para descartar días sin datos significativos). Si es inferior, la entrada de ese día se omite del historial.

---

## Historial de 7 días

La integración mantiene un historial rodante de las últimas **7 entradas** con formato `(fecha, kWh)`. Este historial se persiste en disco para sobrevivir reinicios de Home Assistant.

### Valor de reserva

Mientras no haya 7 días reales acumulados (p. ej. recién instalada la integración), las entradas que falten se rellenan con el valor de reserva **`DEFAULT_BASE_CONSUMPTION_KWH = 5,0 kWh`**. Este valor actúa solo como marcador temporal y se reemplaza en cuanto hay datos reales disponibles.

### Backfill desde el historial del recorder

Al arrancar, la integración intenta recuperar automáticamente los días que le falten consultando el **recorder de Home Assistant**. Para cada día de los últimos 7, consulta:

- `sensor.marstek_venus_system_daily_discharging_energy` — descarga de la batería
- `sensor.marstek_venus_system_daily_grid_at_min_soc_energy` — demanda insatisfecha

Y suma ambos valores exactamente igual que haría la captura de las 23:55. Esto garantiza que, aunque HA se haya reiniciado o la integración se acabe de instalar, el historial se construye con datos reales desde el primer momento.

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
Lunes:  batería descargó 4,2 kWh + red a min SOC 0,8 kWh = 5,0 kWh
Martes: batería descargó 5,1 kWh + red a min SOC 0,0 kWh = 5,1 kWh
Miér:   batería descargó 3,8 kWh + red a min SOC 1,5 kWh = 5,3 kWh
Jueves: batería descargó 4,5 kWh + red a min SOC 0,3 kWh = 4,8 kWh
Vier:   batería descargó 4,9 kWh + red a min SOC 0,0 kWh = 4,9 kWh
Sábado: batería descargó 6,1 kWh + red a min SOC 0,2 kWh = 6,3 kWh
Domingo:batería descargó 5,5 kWh + red a min SOC 0,5 kWh = 6,0 kWh

Consumo esperado = (5,0 + 5,1 + 5,3 + 4,8 + 4,9 + 6,3 + 6,0) / 7 = 5,34 kWh
```

Sin el componente de red a min SOC (solo descarga), el promedio habría sido 4,87 kWh — un 9% menor, lo que podría haber llevado a no cargar lo suficiente.

---

## Por qué importa el componente de red a min SOC

Sin este ajuste, los días en que la batería se vacía antes de medianoche quedan **subestimados** en el historial: solo se registra la descarga de la batería, pero el consumo real del hogar fue mayor. La media resultante infravaloraría el consumo, y el sistema cargaría menos de lo necesario la noche siguiente.

Al sumar la energía que entró de la red mientras todas las baterías estaban en SOC mínimo dentro de una franja de descarga, el historial refleja el **consumo total real del hogar**, no solo lo que la batería pudo cubrir.

---

## Sensor de diagnóstico

| Sensor | Descripción | Reset |
|---|---|---|
| `sensor.marstek_venus_system_daily_grid_at_min_soc_energy` | Energía acumulada de la red durante periodos de SOC mínimo | Medianoche (hora local) |

El sensor `binary_sensor.marstek_venus_system_predictive_charging_active` expone en sus atributos el historial de consumo de los últimos 7 días y el número de entradas reales vs. valores de reserva, útil para verificar el estado del aprendizaje.

![Atributos del historial de consumo en HA](../assets/screenshots/features/consumption-estimate-attributes.png){ width="700"  style="display: block; margin: 0 auto;"}
