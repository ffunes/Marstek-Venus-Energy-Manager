# Monitor de equilibrio de celdas

## Proteccion normal de carga en SOC alto

Esta proteccion esta siempre activa durante la carga automatica. No es un modo
activo de recuperacion y no fuerza a la bateria a cargar. Solo limita o pausa la
carga cuando una bateria ya esta cerca de la zona alta de SOC/tension, para que
el uso diario no empeore el desequilibrio de celdas.

La logica se evalua por bateria. En un sistema con varias baterias, una bateria
puede estar pausada o limitada mientras otra continua cargando con normalidad.

### Limites de potencia de carga

| Condicion para una bateria | Potencia maxima asignada a esa bateria |
|---|---:|
| SOC por debajo del 95 % y `max_cell_voltage` por debajo de 3.45 V | Limite configurado normal |
| SOC igual o superior al 95 % | 200 W |
| SOC igual o superior al 98 % | 90 W |
| `max_cell_voltage` igual o superior a 3.45 V | 90 W |
| `max_cell_voltage` igual o superior a 3.60 V | Carga pausada |

Siempre se aplica la regla mas restrictiva. Por ejemplo, al 96 % de SOC el
limite normal es 200 W, pero si la celda mas alta ya ha llegado a 3.45 V el
limite pasa a 90 W.

### Enclavamiento del taper por tension

Cuando `max_cell_voltage` llega a 3.45 V, esa bateria entra en el taper de
90 W por tension. Ese taper queda enclavado mientras la bateria siga en la
zona alta/top-balancing, por lo que la potencia de carga no vuelve a subir solo
porque la tension de celda baje momentaneamente por debajo de 3.45 V.

El enclavamiento se libera solo cuando la bateria sale de la zona de
top-balancing:

- el SOC baja del 95 %, y
- `max_cell_voltage` baja de 3.45 V.

### Pausa y reanudacion

Si `max_cell_voltage` llega a 3.60 V, la carga se pausa para esa bateria. Es un
bloqueo de carga por bateria, asi que el controlador escribe 0 W de carga en esa
unidad mientras otras baterias elegibles pueden seguir cargando.

La carga se reanuda solo cuando `max_cell_voltage` se asienta de nuevo en
3.50 V o menos. Tras reanudar, la bateria sigue en el taper enclavado de 90 W
mientras permanezca en la zona alta/top-balancing.

Esta ruta de proteccion normal no fuerza una descarga para bajar la tension de
celda. Espera a que la tension se asiente de forma natural. La descarga
controlada solo se usa en el perfil de balanceo activo descrito mas abajo.

### Limite diario de exposicion en SOC alto

Para cada bateria, el controlador mide cuanto tiempo ha pasado en la zona de
top-balancing durante el dia actual. La zona cuenta cuando se cumple cualquiera
de estas condiciones:

- SOC igual o superior al 95 %, o
- `max_cell_voltage` igual o superior a 3.45 V.

Despues de 4 horas en esa zona durante el mismo dia, la carga automatica normal
deja de prolongarse para esa bateria. Esto evita que el uso normal mantenga la
bateria en SOC alto durante demasiado tiempo.

Este limite diario no bloquea la ruta de carga semanal/manual completa una vez
que esa ruta ha desbloqueado explicitamente la carga al 100 %. Tampoco bloquea
el perfil de balanceo activo cuando el usuario configura intencionadamente el
SOC maximo normal de una bateria al 100 %. Su objetivo es proteger la operacion
normal, no impedir una carga completa intencionada para balanceo.

## Perfil de balanceo activo

El balanceo activo se usa en dos situaciones:

- **SOC maximo normal configurado al 100 %**: por bateria, cuando esa bateria
  alcanza el 100 % o un corte BMS confirmado cerca de la parte alta.
- **Dia de carga semanal completa o carga completa manual**: de forma global,
  despues de que todas las baterias participantes hayan alcanzado el 100 % o un
  corte BMS confirmado cerca de la parte alta.
- **Modo programado de balanceo activo de 48 horas**: por bateria, cuando el
  switch de esa bateria esta activado y llega el dia de la semana seleccionado.

Una vez activo, el controlador usa `max_cell_voltage` para mantener las celdas
en la ventana de top-balancing:

| Condicion para una bateria | Comando |
|---|---:|
| `max_cell_voltage <= 3.45 V` | Entra en carga a 90 W |
| Durante carga a 90 W, hasta `max_cell_voltage >= 3.53 V` | Continua carga a 90 W |
| `3.53 V <= max_cell_voltage < 3.59 V` | Carga de mantenimiento a 30 W |
| Fase perdida/en espera, SOC lleno, inversor en standby, potencia real casi cero y `max_cell_voltage > 3.45 V` | Descarga a 30 W |
| SOC alto, carga/mantenimiento activo, inversor en standby y potencia real casi cero desde `max_cell_voltage >= 3.58 V` | Descarga a 30 W |
| `max_cell_voltage >= 3.62 V` | Descarga a 30 W como seguridad |
| Durante descarga, hasta `max_cell_voltage <= 3.45 V` | Continua descarga a 30 W |

La separacion 3.45/3.53 V es intencionada: tras una descarga de balanceo no se
vuelve a pedir carga hasta que la celda mas alta baja a 3.45 V, evitando que el
BMS siga rechazando carga por considerar la bateria todavia llena. Si tras una
recarga o reinicio de la integracion, el modo programado restaura la ultima fase
persistida por bateria (`CHARGE`, `HOLD` o `DISCHARGE`). Si no existe una fase
persistida y el controlador queda en espera, reconstruye la descarga cuando ve
SOC lleno, standby, potencia casi cero y `max_cell_voltage` todavia por encima
de 3.45 V. Esta recuperacion no se aplica durante una fase real de carga. Una
vez iniciada la carga a 90 W, se mantiene hasta 3.53 V y a partir de ahi se pasa al
mantenimiento de 30 W. `3.62 V` se mantiene como proteccion dura para usuarios
cuyas baterias alcancen esa tension. Si durante carga o mantenimiento en SOC
alto el BMS deja de aceptar carga y el inversor pasa a standby, el controlador
lo interpreta como senal para descargar e iniciar un nuevo micro-ciclo aunque
la celda aun no haya llegado a `3.62 V`.

El caso normal `max_soc=100 %` sigue ejecutandose mientras la bateria siga
configurada al 100 % y ningun modo de mayor prioridad tome el control. Cuando
el retraso de carga solar esta activado, sale por bateria cuando la entrada del
PD detecta demanda de la casa/red por encima del objetivo activo mas la deadband,
para que el control PD normal pueda atender la demanda.

Tambien sale o se pausa por bateria cuando:

- dejan de estar disponibles los datos de tension de celda,
- la bateria deja de tener `max_soc` configurado al 100 %,
- la bateria deja de tener datos validos,
- empieza una carga semanal/manual completa, que tiene prioridad.

El caso de carga semanal/manual completa sale de forma global tras 4 horas de
balanceo activo. Si durante esta fase una bateria no tiene datos de tension de
celda, esa bateria queda a 0 W hasta que los datos vuelvan o termine la ventana
de 4 horas.

### Modo programado de balanceo de 48 horas

Cada bateria expone:

- un switch para activar o desactivar el modo programado de balanceo activo,
- un selector de dia para elegir cuando empieza la prueba de 48 horas.

Cuando llega el dia seleccionado, esa bateria queda reservada por el modo de
balanceo y se excluye del reparto normal del control PD. El resto de baterias
pueden seguir siendo usadas por el PD. El modo usa el mismo perfil 90/30/30 W
que el balanceo de carga semanal completa y sale cuando ocurre cualquiera de
estas condiciones:

- el delta de celda cae a un rango razonable (`delta_mV <= 50`), o
- han transcurrido 48 horas.

Cambiar el dia seleccionado borra la marca de "completado hoy" para que pueda
ejecutarse de nuevo en el nuevo dia. Desactivar el switch detiene la ejecucion
actual sin marcarla como completada.

### Diagnostico

El sensor **Integration Status** expone un atributo
`normal_balance_protection` con detalles por bateria:

| Atributo | Significado |
|---|---|
| `in_zone` | Si la bateria esta actualmente en zona de top-balancing |
| `exposure_h` | Horas acumuladas hoy en esa zona |
| `daily_limit_h` | Limite diario actual, normalmente 4 h |
| `paused` | Si la carga esta pausada por tension alta de celda |
| `max_cell_voltage` / `min_cell_voltage` | Tensiones maxima y minima actuales |
| `delta_mV` | Diferencia actual entre la celda mas alta y la mas baja |
| `voltage_taper_latched` | Si el taper de 90 W por tension esta enclavado |
| `active_balance_phase` | Fase actual del balanceo activo normal con `max_soc=100 %`, si existe |
| `charge_limit_w` | Limite efectivo de carga por bateria antes del reparto |

Registra la diferencia de tensión entre la celda más cargada y la menos cargada después de cada carga semanal completa, ofreciendo una visión a largo plazo del estado de equilibrio de las celdas de la batería.

## Cómo activarlo

El monitor de equilibrio se activa en el paso de configuración de **Carga semanal completa** (asistente inicial o flujo de opciones). Al activarlo también se omite el retraso de carga solar el día de la carga semanal para que la batería pueda alcanzar la parte alta, ejecutar el balanceo activo y después tomar la lectura OCV formal.

## Cómo funciona

### Secuencia de lectura OCV (día de carga semanal completa)

Tras completar la fase de balanceo activo de la carga semanal, el monitor de
equilibrio de celdas puede seguir tomando la lectura OCV formal usada para el
seguimiento de salud a largo plazo. En ese punto, la integración:

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
