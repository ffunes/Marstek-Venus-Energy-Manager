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
- **Peak shaving**: protege la batería conservando energía cuando el SOC baja del umbral configurado.
- **Carga semanal completa**: carga al 100% una vez por semana para equilibrar celdas.
- **Retraso de carga solar**: pospone la carga matutina desde la red mientras la producción solar prevista es suficiente para cubrir la energía restante necesaria.
- **Exclusión de cargas**: excluye dispositivos de alta potencia (p. ej. cargadores de VE) para que el controlador no intente compensar su consumo.

## Aviso de responsabilidad

!!! danger "Exención de responsabilidad"
    Este software se proporciona "tal cual", sin garantía de ningún tipo. El uso es bajo tu propio riesgo. El desarrollador no asume ninguna responsabilidad por daños a baterías, inversores, instalación eléctrica, pérdidas económicas o lesiones personales.

    **Si no aceptas estos términos, NO instales ni uses esta integración.**

## Soporte

Si encuentras útil esta integración, puedes apoyar el proyecto:

<a href="https://buymeacoffee.com/ffunes" target="_blank"><img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" alt="Buy Me A Coffee" height="40" width="145"></a>
