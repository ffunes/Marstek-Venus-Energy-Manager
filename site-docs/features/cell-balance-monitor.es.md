# Monitor de equilibrio de celdas

Registra la diferencia de tensión entre la celda más alta y la más baja en la parte final de una carga completa. Esa lectura se usa para ver si el pack mantiene las celdas equilibradas con el tiempo y para generar avisos cuando el desbalanceo es alto.

## Por qué es necesario en baterías LFP

Las baterías Marstek Venus usan celdas LFP. La química LFP es muy estable y duradera, pero tiene una curva de tensión muy plana durante casi todo el rango útil de SOC. En la zona media de carga, dos celdas pueden tener un SOC distinto y aun así mostrar tensiones muy parecidas. Por eso una lectura de tensión a medio SOC no sirve bien para medir el equilibrio real.

La zona útil para medir y balancear está cerca del final de carga. A partir de unos 3.45 V por celda, la curva de tensión LFP sube mucho más deprisa y las diferencias entre celdas se hacen visibles. También es la zona en la que el BMS debería hacer balanceo pasivo, descargando ligeramente las celdas más altas.

En la práctica, el BMS de Marstek no siempre balancea bien las celdas por sí solo. Si el pack llega al 100 % rápido y vuelve enseguida al uso normal, una celda puede quedar repetidamente más alta que las demás. Por eso la integración hace dos cosas:

- ralentiza la parte final de la carga al 100 % para dar tiempo al BMS a trabajar en la ventana de balanceo;
- mide el desbalanceo siempre en un punto de tensión alto y repetible, en lugar de usar lecturas ruidosas a medio SOC.

## Disponibilidad

El monitor de equilibrio de celdas está siempre activo. No hay una opción de configuración separada porque las lecturas son datos útiles de salud de la batería y por sí solas no cambian el funcionamiento normal.

Hay dos controles relacionados que deciden cuándo se lleva la batería a la ventana de medición en tensión alta:

- **Reducción por voltaje al cargar al 100 %**: opción por batería. Cuando el objetivo de carga es 100 %, la integración ralentiza la carga final y registra una lectura de balance en tensión alta.
- **Modo de balanceo activo**: switch por batería. Cuando está activado, la integración cicla activamente esa batería en la zona alta hasta que el delta de celdas baja lo suficiente.

La carga semanal completa puede fijar temporalmente el SOC máximo de la batería al 100 %. Cuando lo hace, se usan exactamente las mismas reglas de reducción por voltaje al 100 %.

## Reducción por voltaje al 100 %

Esta ruta se usa cuando una batería tiene objetivo de carga al 100 %:

- el usuario ha configurado esa batería con `max_soc = 100`, o
- la carga semanal completa ha elevado temporalmente esa batería al 100 %.

La carga semanal completa no usa un perfil de balanceo distinto. Solo cambia el objetivo de SOC a 100 %; los voltajes, la potencia y la medición son los mismos.

### Perfil de carga

| Condición para una batería | Acción |
|---|---:|
| `max_cell_voltage` por debajo de 3.48 V | Límite de carga configurado normal |
| `max_cell_voltage` igual o superior a 3.48 V | Limita la carga a 95 W |
| `max_cell_voltage` igual o superior a 3.58 V | Para la carga y espera 60 s |
| Tras la espera de 60 s | Registra `delta_mV = (Vmax - Vmin) * 1000` |

La lógica se basa en tensión de celda. El SOC no se usa para decidir cuándo empieza o termina la reducción por voltaje, porque cerca del final de carga los registros de tensión de celda son más fiables que el SOC reportado.

No hay histéresis adicional de voltaje en esta ruta. Cuando la batería llega a 3.58 V y se toma la lectura, la integración no fuerza una descarga. Deja la carga parada en esa tensión y permite que la lógica normal de SOC/carga decida cuándo se podrá volver a cargar.

En sistemas con varias baterías, la lógica se evalúa por batería. Una batería puede estar limitada o pausada mientras otra sigue cargando con normalidad.

## Modo de balanceo activo

El modo de balanceo activo es una ruta de recuperación más fuerte para baterías que necesitan más tiempo en la ventana de balanceo.

Cuando el switch está activado, esa batería queda excluida del control PD normal. El resto de baterías pueden seguir funcionando normalmente. La integración eleva temporalmente el objetivo de carga de esa batería al 100 % y ordena carga directa para esa batería.

### Perfil de balanceo activo

| Fase | Acción |
|---|---|
| Antes de la zona alta | Carga desde la red a la potencia máxima configurada de la batería hasta `max_cell_voltage >= 3.49 V` |
| Carga regulada en la parte alta | Carga a 95 W hasta `max_cell_voltage >= 3.58 V` |
| Espera de medición | Para carga/descarga, espera 60 s y mide el delta de celdas |
| Si `delta_V > 0.03 V` | Descarga a 25 W hasta `max_cell_voltage <= 3.49 V` y vuelve a cargar |
| Si `delta_V <= 0.03 V` | Descarga final a 25 W hasta `max_cell_voltage <= 3.48 V`, termina y apaga el switch |

Si el BMS acepta el comando de carga pero la batería no carga realmente antes de llegar a 3.58 V, la integración lo interpreta como rechazo de carga. Primero descarga y después baja el voltaje de reintento en 0.01 V, hasta un mínimo de 3.40 V, para que el siguiente ciclo empiece desde un punto en el que el BMS tenga más probabilidad de aceptar carga.

El modo de balanceo activo no tiene un límite fijo de 48 horas. Se ejecuta hasta que el delta medido en tensión alta es igual o inferior a 0.03 V, o hasta que el usuario apaga el switch.

## Cómo se mide el desbalanceo

La única lectura que alimenta el estado de balance, los avisos y la tendencia es la medición explícita en tensión alta:

1. la batería llega a `max_cell_voltage >= 3.58 V`;
2. se detiene la carga;
3. la integración espera 60 segundos;
4. registra la diferencia entre `max_cell_voltage` y `min_cell_voltage`.

Las antiguas lecturas tipo OCV, las lecturas oportunistas y las retenciones pasivas largas ya no se usan. Medir siempre en el mismo punto de tensión alta hace que las lecturas sean más comparables entre cargas completas.

## Umbrales

| Estado | Rango de delta | Significado |
|---|---|---|
| Verde | < 50 mV | Buen equilibrio |
| Amarillo | 50-99 mV | Desbalanceo leve; monitorizar con el tiempo |
| Naranja | 100-149 mV | Desbalanceo moderado |
| Rojo | >= 150 mV | Desbalanceo alto |

Los umbrales son fijos y se aplican por igual a todos los packs LFP compatibles.

## Notificaciones

La integración envía notificaciones persistentes de Home Assistant en estos casos:

| Evento | Título de la notificación |
|---|---|
| Lectura naranja o roja en tensión alta | Cell imbalance - `{nombre de la batería}` |
| Rojo en 2 o más cargas completas consecutivas | Possible degraded cell - `{nombre de la batería}` |
| Tendencia creciente con media por encima de 75 mV | Rising imbalance trend - `{nombre de la batería}` |
| Inicio/final del modo de balanceo activo | Active balancing started/finished - `{nombre de la batería}` |

## Entidades de sensor

Cuando la función está activada se crean cinco entidades de sensor por batería:

| Entidad | Descripción | Unidad |
|---|---|---|
| `sensor.*_cell_delta` | Diferencia de tensión entre la celda máxima y mínima | mV |
| `sensor.*_balance_status` | Resultado del equilibrio: `green` / `yellow` / `orange` / `red` | - |
| `sensor.*_delta_trend` | Tendencia en las lecturas recientes: `rising` / `stable` / `falling` | - |
| `sensor.*_last_balance_read` | Marca de tiempo de la última lectura | timestamp |
| `sensor.*_delta_avg_4w` | Media móvil de las últimas 4 lecturas | mV |

Los valores se restauran desde el almacenamiento persistente tras un reinicio de Home Assistant, de modo que los sensores muestran el último estado conocido al arrancar.

## Diagnóstico

El sensor **Integration Status** expone un atributo `normal_balance_protection` con detalles por batería:

| Atributo | Significado |
|---|---|
| `enabled` | Si la reducción por voltaje al 100 % está activada para esa batería |
| `in_zone` | Si `max_cell_voltage` está en la ventana de balanceo superior |
| `paused` | Si la carga está parada por tensión alta de celda |
| `max_cell_voltage` / `min_cell_voltage` | Tensiones máxima y mínima actuales |
| `delta_V` | Diferencia actual de tensión en voltios |
| `voltage_taper_latched` | Si la reducción a 95 W está activa |
| `active_balance_phase` | Fase actual de medición al 100 %, si existe |
| `charge_limit_w` | Límite efectivo de carga por batería antes del reparto |

El modo de balanceo activo también expone su fase actual, delta medido, potencia ordenada y voltaje de reintento en los diagnósticos del estado de integración.

!!! info
    Los registros de tensión de celda (`max_cell_voltage`, `min_cell_voltage`) se leen en todas las versiones de batería compatibles (v2, v3, vA, vD).
