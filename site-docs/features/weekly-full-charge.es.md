# Carga semanal completa

Carga las baterías al **100 % una vez por semana** para que el pack llegue a la ventana superior de balanceo LFP y la integración pueda medir el desbalanceo de celdas en condiciones repetibles.

## Comportamiento

1. El día configurado de la semana, si el SOC máximo habitual es inferior al 100 %, la integración eleva temporalmente el límite de corte de carga de la batería al 100 %.
2. La batería carga hasta que entra la reducción por voltaje en la parte alta.
3. Desde `max_cell_voltage >= 3.48 V`, la carga se limita a 95 W.
4. En `max_cell_voltage >= 3.58 V`, la carga se detiene y la integración espera 60 segundos.
5. Tras la espera, el monitor de equilibrio registra `delta_mV = (Vmax - Vmin) * 1000`.
6. Tras finalizar, el límite de SOC máximo vuelve automáticamente al valor configurado por el usuario.

La carga semanal completa usa el mismo perfil de voltaje que una batería configurada normalmente con `max_soc = 100`. La función semanal solo eleva el objetivo a 100 %; no usa un algoritmo de balanceo distinto.

!!! note "SOC desviado"
    Si un pack llega a 3.58 V mientras el BMS sigue reportando un SOC por debajo del 90 %, la carga *no* se pausa en el paso 4: la integración sigue cargando a 95 W hasta que el BMS corta, *intentando* que recalibre el SOC al 100 % para que la carga semanal pueda completarse. Es de mejor esfuerzo y depende del firmware del BMS — no está garantizado. Ver [Recalibración de SOC con tensión alta atascada](cell-balance-monitor.md#recalibracion-de-soc-con-tension-alta-atascada).

## Monitor de equilibrio de celdas

El **monitor de equilibrio de celdas** está siempre activo. Registra la diferencia de tensión entre la celda más alta y la más baja tras cada medición en tensión alta, y mantiene actualizados los sensores, la tendencia y las alertas.

Consulta [Monitor de equilibrio de celdas](cell-balance-monitor.md) para más detalles.

## Interacción con el retraso de carga solar

Si el [retraso de carga solar](solar-charge-delay.md) está activo, la carga semanal puede aplazarse mientras la producción solar prevista sea suficiente para alcanzar el 100 %.

Cuando la carga semanal completa está activa, la integración puede omitir el retraso para que la batería alcance el punto de medición en tensión alta y la lectura de balance no se pierda.

## Registro Modbus implicado

La función manipula el registro **44000** (charging cutoff) de la batería para elevar temporalmente el límite.

!!! info
    Esta función está disponible para todas las versiones de batería compatibles (v2, v3, vA, vD).

![Configuración de carga semanal completa](../assets/screenshots/features/weekly-full-charge-config.png){ width="650"  style="display: block; margin: 0 auto;"}
