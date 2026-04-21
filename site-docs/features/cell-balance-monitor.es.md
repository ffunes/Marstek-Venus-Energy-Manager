# Monitor de equilibrio de celdas

Registra la diferencia de tensión entre la celda más cargada y la menos cargada después de cada carga semanal completa, ofreciendo una visión a largo plazo del estado de equilibrio de las celdas de la batería.

## Cómo activarlo

El monitor de equilibrio se activa en el paso de configuración de **Carga semanal completa** (asistente inicial o flujo de opciones). Al activarlo también se omite el retraso de carga solar el día de la carga semanal, manteniendo la batería en flotación mientras haya sol disponible y maximizando el tiempo de equilibrado pasivo.

## Cómo funciona

### Secuencia de lectura OCV (día de carga semanal completa)

Cuando la batería alcanza el 100 % de SOC en el día de carga semanal, la integración:

1. **Bloquea la descarga** — impide que la batería descargue para que las celdas reposen en circuito abierto.
2. **Espera 15 minutos** — permite que el equilibrado activo del BMS se estabilice y que las tensiones superficiales se asienten.
3. **Comprueba la estabilidad** — requiere al menos 5 sondeos consecutivos con potencia inferior a 50 W y variación de tensión menor de 5 mV entre sondeos.
4. **Toma la lectura** — registra `delta_mV = (Vmax − Vmin) × 1000`.
5. **Libera la descarga** — salvo que el resultado sea naranja (ver umbrales más abajo).

### Retención naranja (2,5 horas de equilibrado pasivo)

Si la lectura cae en la zona naranja (100–149 mV), la descarga permanece bloqueada durante 2,5 horas para que el equilibrado pasivo actúe. Tras ese periodo se toma una lectura de seguimiento y la descarga se libera independientemente del resultado.

### Lecturas oportunistas

Los días distintos al día de carga semanal completa, si la batería ya está al 100 % de SOC y la potencia es inferior a 50 W, la integración realiza una lectura ligera sin bloquear la descarga. Limitada a una vez cada 24 horas.

## Umbrales

| Estado | Rango de delta | Significado |
|---|---|---|
| 🟢 Verde | < 50 mV | Buen equilibrio |
| 🟡 Amarillo | 50 – 99 mV | Desequilibrio leve — monitorizar con el tiempo |
| 🟠 Naranja | 100 – 149 mV | Desequilibrio moderado — retención de 2,5 h iniciada |
| 🔴 Rojo | ≥ 150 mV | Desequilibrio elevado |

Los umbrales son fijos y se aplican por igual a todas las químicas de celda LFP.

## Notificaciones

La integración envía notificaciones persistentes de Home Assistant en los siguientes casos:

| Evento | Título de la notificación |
|---|---|
| Lectura naranja o roja | ⚠️ Cell imbalance — {nombre de la batería} |
| Naranja persiste tras 2,5 h | ⚠️ Cell imbalance persists — {nombre de la batería} |
| Rojo en 2 o más cargas consecutivas | 🔴 Possible degraded cell — {nombre de la batería} |
| Tendencia creciente con media por encima de 75 mV | 📈 Rising imbalance trend — {nombre de la batería} |

## Entidades de sensor

Cuando la función está activada se crean cinco entidades de sensor por batería:

| Entidad | Descripción | Unidad |
|---|---|---|
| `sensor.*_cell_delta` | Diferencia de tensión entre la celda máxima y mínima | mV |
| `sensor.*_balance_status` | Resultado del equilibrio: `green` / `yellow` / `orange` / `red` | — |
| `sensor.*_delta_trend` | Tendencia en las últimas lecturas formales: `rising` / `stable` / `falling` | — |
| `sensor.*_last_balance_read` | Marca de tiempo de la última lectura | timestamp |
| `sensor.*_delta_avg_4w` | Media de las últimas 4 lecturas formales | mV |

Los valores se restauran desde el almacenamiento persistente tras un reinicio de Home Assistant, de modo que los sensores muestran el último estado conocido de inmediato al arrancar.

## Notas técnicas

- El pico de tensión visible al 100 % de SOC (antes del periodo de espera) es un comportamiento normal del equilibrado activo del BMS, no un desequilibrio real. La espera de 15 minutos garantiza que la lectura se realiza a tensión real de circuito abierto.
- Se almacenan hasta 52 lecturas por batería (aproximadamente un año de cargas semanales).
- La media a 4 semanas y la tendencia se calculan únicamente a partir de lecturas formales (no oportunistas), para reflejar el patrón a tensión real de circuito abierto.

!!! info
    Los registros de tensión de celda (`max_cell_voltage`, `min_cell_voltage`) se leen en todas las versiones de batería compatibles (v2, v3, vA, vD).
