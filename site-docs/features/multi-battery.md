# Gestión multi-batería

La integración gestiona hasta **6 baterías** como un sistema agregado, distribuyendo la potencia de forma inteligente para maximizar la eficiencia.

## Principio de eficiencia

Basándose en la curva de eficiencia de las Venus (pico ~91% entre 1000–1500 W), las baterías se activan solo cuando la potencia total supera el **60 % de la capacidad combinada**. Operar con menos baterías activas a mayor potencia es más eficiente que repartir la misma carga entre todas.

## Prioridades de selección

### Descarga

**Mayor SOC primero**: la batería más cargada descarga primero para equilibrar el estado de carga del conjunto.

### Carga

**Menor SOC primero**: la batería menos cargada recibe la energía primero.

## Histéresis

Para evitar el "ping-pong" de activación/desactivación, se aplican tres niveles de histéresis:

| Histéresis | Valor | Descripción |
|---|---|---|
| **SOC** | 5 % | Una batería activa permanece activa hasta que otra la supere en 5 % de SOC |
| **Energía vitalicia** | 2,5 kWh | Desempata el SOC usando la energía acumulada con ventaja para la batería activa |
| **Potencia** | ±100 W | Activa la 2.ª batería al 60 % de la capacidad combinada; la desactiva al 50 % |

## Distribución de potencia

Una vez seleccionadas las baterías activas, la potencia total calculada por el [controlador PD](pd-controller.md) se reparte entre ellas proporcionalmente, respetando los límites individuales de potencia y SOC de cada una.

## Modos compatibles

La distribución multi-batería se aplica en todos los modos:
- Control PD normal
- Carga solar
- Carga predictiva desde la red

![Estado de baterías múltiples en Home Assistant](../assets/screenshots/features/multi-battery-entities.png){ width="700"  style="display: block; margin: 0 auto;"}
