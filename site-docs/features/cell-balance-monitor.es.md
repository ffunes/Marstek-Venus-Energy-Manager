# Monitor de equilibrio de celdas

Registra la diferencia de tensión entre la celda más alta y la más baja en la parte final de una carga completa. Esa lectura se usa para ver si el pack mantiene las celdas equilibradas con el tiempo y para generar avisos cuando el desbalanceo es alto.

## Por qué es necesario en baterías LFP

Las baterías Marstek Venus usan celdas LFP. La química LFP es muy estable y duradera, pero tiene una curva de tensión muy plana durante casi todo el rango útil de SOC. En la zona media de carga, dos celdas pueden tener un SOC distinto y aun así mostrar tensiones muy parecidas. Por eso una lectura de tensión a medio SOC no sirve bien para medir el equilibrio real.

La zona útil para medir y balancear está cerca del final de carga. A partir de unos 3.45 V por celda, la curva de tensión LFP sube mucho más deprisa y las diferencias entre celdas se hacen visibles. También es la zona en la que el BMS debería hacer balanceo pasivo, descargando ligeramente las celdas más altas.

En la práctica, el BMS de Marstek no siempre balancea bien las celdas por sí solo. Si el pack llega al 100 % rápido y vuelve enseguida al uso normal, una celda puede quedar repetidamente más alta que las demás. Por eso la integración hace dos cosas:

- ralentiza la parte final de la carga al 100 % para dar tiempo al BMS a trabajar en la ventana de balanceo;
- mide el desbalanceo siempre en un punto de tensión alto y repetible, en lugar de usar lecturas ruidosas a medio SOC.

## La curva de carga LFP en detalle

La química LFP (LiFePO4) tiene una curva de carga/descarga radicalmente distinta de la del Li-ion NMC o NCA. Entenderla es lo que justifica cada uno de los umbrales de tensión que usa esta integración.

Una celda LFP típica de 3,2 V nominales se comporta así durante una carga a corriente constante:

| Rango de SOC | Rango de tensión de celda | Pendiente |
|---|---|---|
| 0 – 10 % | 2,50 V → 3,20 V | Rodilla de entrada muy pronunciada |
| 10 – 90 % | 3,20 V → 3,30 V | Casi plana — alrededor de 1 mV por % de SOC |
| 90 – 97 % | 3,30 V → 3,45 V | Empieza una subida suave |
| 97 – 99 % | 3,45 V → 3,55 V | Rodilla — la tensión empieza a subir con fuerza |
| 99 – 100 % | 3,55 V → 3,65 V | Rodilla superior abrupta — el "acantilado" del final de carga |

Esa larga meseta plana es la razón por la que, en mitad de la curva, la tensión LFP apenas dice nada sobre el estado de carga. Dos celdas que parecen idénticas a 3,28 V pueden tener en realidad un 5 – 10 % de diferencia de SOC entre ellas, lo cual es enorme.

La meseta también significa que **el BMS no puede hacer un balanceo pasivo útil en mitad de la curva**. El balanceo pasivo funciona drenando corriente de la celda más alta a través de una resistencia. Para poder decidir cuál es la celda "más alta", el BMS necesita que la diferencia entre celdas se eleve por encima del ruido de medida. En la meseta todas las celdas leen prácticamente lo mismo, así que el BMS no tiene nada con lo que actuar.

Solo cuando el pack entra en la rodilla superior (por encima de unos 3,45 V) las tensiones de celda se separan lo suficiente para que el BMS identifique a la celda líder. Una diferencia de 10 mV en la meseta puede corresponder a un 5 % de diferencia de SOC, pero los mismos 10 mV por encima de 3,50 V representan un delta de SOC minúsculo — que es justo lo que interesa al final de carga.

Por eso el balanceo en LFP solo es eficaz en una ventana estrecha: aproximadamente el último 1 – 3 % de carga, por encima de 3,45 V. Fuera de esa ventana el BMS es prácticamente ciego al desbalanceo, y todo el tiempo que el pack pasa por debajo de la rodilla es tiempo durante el que las celdas *no* se están balanceando.

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

### Recalibración de SOC con tensión alta atascada

Algunos packs llegan al punto de pausa de 3.58 V mientras el BMS sigue reportando un SOC muy por debajo del total (por ejemplo 60–70 %). Esa diferencia indica que el contador de coulombs del BMS se ha desviado: las celdas están realmente llenas pero el SOC reportado es incorrecto.

Cuando esto ocurre, quedarse en 3.58 V nunca deja que el BMS se corrija. Por eso, en vez de pausar, la integración sigue cargando a la potencia reducida de 95 W hasta que el propio BMS corta, *intentando* que recalibre el SOC al 100 %.

Es un intento de mejor esfuerzo, no una solución garantizada. Que un corte en la parte alta de la curva realmente reinicie el SOC reportado depende del firmware del BMS: algunos packs saltan al 100 % con un corte por sobretensión, otros no. La integración solo crea las condiciones para una recalibración — no puede obligar al BMS a aplicarla.

El override se activa automáticamente cuando se cumple **todo** lo siguiente:

- el objetivo de carga es 100 % (la reducción aplica), y
- `max_cell_voltage` ha alcanzado el punto de pausa de 3.58 V, y
- el BMS sigue reportando un SOC por debajo del 90 %.

Es autolimitado:

- la carga continúa solo a 95 W (la potencia suave de reducción), no a plena potencia;
- el corte del BMS se detecta cuando la potencia de la batería cae a ≤ 10 W y el inversor reporta Standby durante 5 ciclos consecutivos (~10 s). En ese momento el override se enclava y se reanuda la pausa normal de 3.58 V, dejando que el SOC se recalibre;
- una vez que el SOC marca 90 % o más (tras recalibrar), la condición ya no se cumple, así que el override no se vuelve a disparar;
- el enclavamiento solo se rearma cuando la batería sale de la zona alta (`max_cell_voltage` por debajo de 3.48 V), para que una carga completa posterior pueda recalibrar de nuevo si hace falta.

Como depende de un objetivo de carga del 100 %, nunca afecta al ciclado diario normal con un `max_soc` más bajo. Tampoco se ejecuta mientras el [modo de balanceo activo](#modo-de-balanceo-activo) controla la batería — ese modo tiene prioridad.

!!! note "Desbalance de celdas"
    El override no comprueba primero la dispersión entre celdas. En un pack muy desbalanceado, la celda más alta puede llegar al corte por sobretensión del BMS antes de que el pack esté lleno, así que la recalibración es correcta pero el balanceo queda para ciclos posteriores. El BMS sigue protegiendo cada celda de forma individual.

## Modo de balanceo activo

El modo de balanceo activo es una ruta de recuperación más fuerte para baterías que necesitan más tiempo en la ventana de balanceo.

Cuando el switch está activado, esa batería queda excluida del control PD normal. El resto de baterías pueden seguir funcionando normalmente. La integración eleva temporalmente el objetivo de carga de esa batería al 100 % y ordena carga directa para esa batería.

### Perfil de balanceo activo

| Fase | Acción |
|---|---|
| Antes de la zona alta | Carga desde la red a la potencia máxima configurada de la batería hasta `max_cell_voltage >= 3.49 V` |
| Carga regulada en la parte alta | Carga a 95 W hasta `max_cell_voltage >= 3.58 V` |
| Espera de medición | Para carga/descarga, espera 60 s y mide el delta de celdas |
| Si `delta_V > 0.03 V` | Descarga a 200 W hasta `max_cell_voltage <= 3.49 V` y vuelve a cargar |
| Si `delta_V <= 0.03 V` | Descarga final a 200 W hasta `max_cell_voltage <= 3.48 V`, termina y apaga el switch |

Si el BMS corta la carga antes de que `max_cell_voltage` llegue a 3.58 V, la integración lo interpreta como rechazo de carga. El rechazo solo se detecta cuando no circula corriente (potencia de batería ~0 W), así que las celdas ya están en reposo: registra una medición del delta de celdas en ese punto, en vez de terminar el ciclo sin lectura. Después descarga y baja el voltaje de reintento en 0.01 V. El voltaje de reintento rebajado **se mantiene entre ciclos de carga/descarga**, bajando otros 0.01 V en cada nuevo rechazo hasta un suelo de 3.40 V, de modo que el pack se va bajando progresivamente hasta que el BMS vuelve a aceptar carga. El voltaje de reintento se restablece a su valor por defecto solo cuando el pack llega a la parte alta de 3.58 V, o cuando el ciclo termina.

El modo de balanceo activo no tiene un límite fijo de 48 horas. Se ejecuta hasta que el delta medido en tensión alta es igual o inferior a 0.03 V, o hasta que el usuario apaga el switch.

## Por qué estos umbrales de tensión

Todos los cortes de tensión usados por la reducción al 100 % y por el modo de balanceo activo se eligen contra la curva LFP descrita arriba. Ninguno de estos números es arbitrario.

| Umbral | Dónde se usa | Por qué este valor |
|---|---|---|
| **3,45 V** | Referencia para el inicio de la rodilla superior | Es aproximadamente donde la curva LFP abandona la meseta. Por debajo no se puede confiar en las decisiones de balanceo, porque las tensiones de las celdas están demasiado juntas para distinguirlas. |
| **3,48 V** | Disparador para reducir la carga a 95 W | Un poco por encima de la rodilla. El pequeño margen confirma que el pack está realmente en la ventana de balanceo — y no en un rebote de tensión transitorio causado por un escalón de carga — antes de bajar la potencia. |
| **3,49 V** | Suelo de descarga entre reintentos del balanceo activo; cambio de carga "rápida" a carga regulada | Está justo dentro de la ventana de balanceo. Parar la descarga aquí mantiene el pack en la zona donde el BMS aún puede ver y drenar la celda alta. Bajar más sacaría al pack de la rodilla y desperdiciaría el tiempo ya invertido en balancear. |
| **3,58 V** | Punto de medida superior; se para la carga y se esperan 60 s antes de leer el delta | Lo bastante alto como para que incluso la celda *más baja* esté firmemente en la rodilla y la diferencia entre celdas sea significativa. Lo bastante bajo como para que la celda *más alta* siga claramente por debajo del techo de 3,65 V que indican las hojas LFP y por debajo del corte por sobretensión del BMS. El margen de ~70 mV es intencional: la diferencia entre celdas es justo lo que se quiere medir, y hay que dejarle sitio. |
| **3,48 V (otra vez)** | Suelo de descarga al final del ciclo — la descarga final a 200 W tras completar un balanceo activo se detiene aquí | El mismo umbral usado para entrar en la reducción se reutiliza para salir de la ventana de balanceo. Parar a 3,48 V deja al pack justo por debajo del comienzo de la rodilla superior sin devolverlo del todo a la meseta profunda. Quedarse a 3,55 – 3,58 V durante mucho tiempo acelera el envejecimiento calendario, así que la integración baja deliberadamente al borde inferior de la ventana antes de soltar el control. |
| **3,40 V** | Límite inferior del voltaje de reintento del balanceo activo cuando se detecta rechazo de carga | La integración baja el voltaje de reintento en 0,01 V cada vez que el BMS rechaza la carga, pero nunca por debajo de 3,40 V. Bajar más saldría completamente de la ventana de balanceo y obligaría a volver a subir toda la curva, lo que es una pérdida de tiempo. |
| **0,03 V (30 mV)** | Umbral de finalización del balanceo activo | Se considera "suficientemente equilibrado" para un pack LFP en la parte alta de la rodilla. Forzar valores más estrictos (10 mV o menos) rara vez compensa, porque las corrientes de balanceo pasivo son minúsculas — ver la sección siguiente. |
| **0,05 V (50 mV)** | Frontera verde / amarillo | Un pack por debajo de 50 mV en la parte alta se considera sano. Es más estricto que las especificaciones típicas de fabricantes LFP (80 – 100 mV) porque la medida se toma en la ventana de balanceo, donde las diferencias entre celdas están exageradas. |

La potencia de carga de 95 W está emparejada con los umbrales de carga a propósito: es lo bastante baja como para que la tensión de celda medida *durante la carga* esté dominada por la propia química de la celda y no por la caída IR (resistiva) en la celda, en las pletinas y en los shunts del BMS. Cargar a cientos de vatios en la rodilla desplazaría la lectura aparente decenas de milivoltios y arruinaría la comprobación del umbral de 3.58 V. La descarga es de 200 W porque el delta de celdas siempre se mide en **reposo** —se paran tanto la carga como la descarga durante 60 s antes de tomar la lectura—, así que la mayor potencia de descarga solo baja el pack más rápido entre mediciones y nunca contamina el delta registrado.

## Por qué tarda tanto

El balanceo de celdas **no** es un proceso rápido — y los packs Marstek Venus no son una excepción. Hay dos razones.

**1. La corriente de balanceo pasivo es muy pequeña.** Un BMS LFP típico drena la celda más alta a través de una resistencia con una corriente de entre 30 mA y 150 mA. Los packs Marstek Venus se mueven por la parte baja de ese rango. Para una celda de 100 Ah, un drenaje de 50 mA quita solo unos 0,05 % de SOC por hora a la celda alta. Por eso igualar diferencias incluso pequeñas entre celdas requiere muchas horas seguidas dentro de la ventana de balanceo.

**2. La ventana de balanceo es estrecha.** El BMS solo puede drenar cuando el pack está por encima de ~3,45 V *y* la celda más alta destaca de forma detectable sobre el resto. En cuanto se para la carga o el pack vuelve a bajar de la rodilla, el balanceo se detiene. Un ciclo de carga normal que llega al 100 % y vuelve enseguida a descargar pasa solo unos minutos en la ventana útil — muy poco para que tenga efecto visible.

La consecuencia práctica es:

> **Reducir el delta de celdas en lo alto de carga unos 5 mV requiere típicamente alrededor de 24 horas de tiempo acumulado en la parte alta de la ventana de balanceo.**

Esa cifra es coherente tanto con el cálculo de corrientes de drenaje de arriba como con lo observado en packs Venus reales. Desbalanceos mayores (50 mV o más) pueden necesitar **varios días** de sesiones repetidas de balanceo arriba antes de que el delta empiece a bajar de forma consistente. Packs que han estado crónicamente desbalanceados durante meses pueden tardar una semana o más en recuperarse.

Esa es también la razón por la que el modo de balanceo activo no tiene una "vía rápida":

- el límite de 95 W de carga por encima de 3,48 V está pensado para mantener al pack en la rodilla el tiempo suficiente para que el BMS avance, en lugar de atravesarla en segundos;
- los 200 W de descarga entre reintentos bajan el pack de vuelta al voltaje de reintento sin salir de la ventana;
- el bucle de balanceo activo puede ejecutarse indefinidamente, porque cualquier duración por debajo de "muchas horas" difícilmente moverá el delta.

Si el objetivo es recuperar un pack visiblemente desbalanceado, lo correcto es activar el modo de balanceo activo y **dejarlo funcionando toda la noche (o más tiempo) y mirar el resultado al día siguiente**. Mirar el delta de celdas en tiempo real esperando movimientos en cuestión de minutos solo lleva a frustración.

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
| Lectura naranja o roja en tensión alta | Desbalanceo de celdas - `{nombre de la batería}` |
| Rojo en 2 o más cargas completas consecutivas | Posible celda degradada - `{nombre de la batería}` |
| Tendencia creciente con media por encima de 75 mV | Tendencia de desbalanceo creciente - `{nombre de la batería}` |
| Inicio/final del modo de balanceo activo | Balanceo activo iniciado/finalizado - `{nombre de la batería}` |

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
| `soc_recal_active` | Si la carga se mantiene más allá de la pausa de 3.58 V para recalibrar un SOC reportado bajo |
| `soc_recal_bms_cutoff` | Si se ha alcanzado el corte del BMS durante la recalibración (override enclavado) |
| `charge_limit_w` | Límite efectivo de carga por batería antes del reparto |

El modo de balanceo activo también expone su fase actual, delta medido, potencia ordenada y voltaje de reintento en los diagnósticos del estado de integración.

!!! info
    Los registros de tensión de celda (`max_cell_voltage`, `min_cell_voltage`) se leen en todas las versiones de batería compatibles (v2, v3, vA, vD).
