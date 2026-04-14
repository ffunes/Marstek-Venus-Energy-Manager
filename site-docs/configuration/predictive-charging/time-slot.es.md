# Carga predictiva — Modo Franja Horaria

Carga desde la red durante una **ventana horaria fija** (típicamente tarifa nocturna barata).

## Configuración

| Campo | Descripción |
|---|---|
| **Ventana horaria** | Inicio y fin de la franja de carga (p. ej. `02:00` – `05:00`) |
| **Sensor de previsión solar** | Sensor de producción solar del día actual en kWh (opcional) |
| **Potencia ICP contratada** | Límite de la conexión de red (W). Asegura que carga + consumo doméstico no supere el ICP |

!!! danger "Cambio importante en v1.6.0"
    El campo de sensor de previsión solar ahora debe apuntar al sensor de **hoy** (p. ej. `sensor.solcast_pv_forecast_forecast_today`), no al de mañana.

!!! note "Sin sensor solar"
    Si no tienes paneles solares, deja vacío el sensor de previsión. El sistema cargará siempre que la energía de la batería sea insuficiente para cubrir el consumo esperado.

![Formulario de configuración — Modo Franja Horaria](../../assets/screenshots/configuration/predictive-charging/time-slot-form.png){ width="650"  style="display: block; margin: 0 auto;"}

## Flujo de evaluación

1. **Al entrar en el slot**: las baterías se mantienen en reposo durante 5 minutos para que el sensor de previsión solar tenga tiempo de actualizarse (especialmente relevante si el slot comienza a las 00:00).
2. **5 minutos después**: el sistema evalúa el balance energético (`energía usable + previsión solar` vs. `consumo diario estimado`) y decide si cargar o no.
3. Se envía una notificación con la decisión tomada.
4. La carga continúa hasta que la batería alcanza el nivel calculado o finaliza la ventana.

## Reevaluación por caída de SOC

Si el SOC cae un 30 % o más respecto al último punto de evaluación durante el slot (p. ej. por un consumo elevado), el sistema reevalúa el balance energético automáticamente. No se envía notificación adicional en estas reevaluaciones intermedias.
