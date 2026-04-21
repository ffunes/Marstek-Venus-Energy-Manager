# Marstek Venus Energy Manager

**Marstek Venus Energy Manager** es una integración personalizada para Home Assistant que monitoriza y controla baterías Marstek Venus (series E v2/v3, Venus A y Venus D) mediante Modbus TCP.

<div class="grid cards" markdown>

-   :material-battery-charging: **Control dinámico de potencia**

    Controlador PD que mantiene el flujo de red cerca de cero para maximizar el autoconsumo.

-   :material-calendar-clock: **Carga predictiva**

    Carga automática desde la red cuando la previsión solar no cubre el consumo esperado.

-   :material-battery-sync: **Multi-batería**

    Gestión inteligente de hasta 6 baterías con distribución óptima de carga.

-   :material-tune: **Altamente configurable**

    Franjas horarias, dispositivos excluidos, peak shaving, carga semanal completa y más.

</div>

## Características principales

- **Controlador PD (Zero Export/Import)**: ajusta en tiempo real la potencia de la batería para mantener el intercambio con la red próximo a cero.
- **Carga predictiva**: tres modos (franja horaria, precio dinámico, precio en tiempo real) que cargan desde la red solo cuando el balance energético lo requiere. Utiliza una media móvil de 7 días del consumo real del hogar para decidir si es necesario cargar desde la red.
- **Gestión multi-batería**: selección inteligente con prioridades de SOC, histéresis de energía y eficiencia por zona de operación.
- **Franjas de descarga**: define ventanas horarias y niveles objetivo de red por franja.
- **Peak shaving**: reserva capacidad de la batería para satisfacer picos de demanda que superen un umbral de potencia configurable.
- **Carga semanal completa**: carga al 100% una vez por semana para equilibrar celdas.
- **Monitor de equilibrio de celdas**: mide la diferencia de tensión entre la celda más y menos cargada después de cada carga completa; hace seguimiento de la tendencia de desequilibrio a lo largo del tiempo, envía alertas ante desequilibrios moderados o altos y bloquea la descarga durante el periodo de reposo en circuito abierto.
- **Retraso de carga solar**: pospone la carga matutina de la batería (solar y desde la red) mientras la producción solar prevista es suficiente para cubrir la energía restante necesaria.
- **Exclusión de cargas**: excluye dispositivos de alta potencia (p. ej. cargadores de VE) para que el controlador no intente compensar su consumo.
- **Notificaciones proactivas de alarmas (solo baterías v2)**: monitoriza los registros de fallos y alarmas de la batería cada 5 segundos y envía una notificación de Home Assistant en el momento en que se detecta una nueva condición, con el nombre exacto del fallo o alarma. El sensor de sistema `System Alarm Status` (`OK` / `Warning` / `Fault`) ofrece una vista rápida del estado de todas las baterías.

## Aviso de responsabilidad

!!! danger "Exención de responsabilidad"
    Este software se proporciona "tal cual", sin garantía de ningún tipo. El uso es bajo tu propio riesgo. El desarrollador no asume ninguna responsabilidad por daños a baterías, inversores, instalación eléctrica, pérdidas económicas o lesiones personales.

    **Si no aceptas estos términos, NO instales ni uses esta integración.**

## Soporte

Si encuentras útil esta integración, puedes apoyar el proyecto:

<a href="https://buymeacoffee.com/ffunes" target="_blank"><img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" alt="Buy Me A Coffee" height="40" width="145"></a>
