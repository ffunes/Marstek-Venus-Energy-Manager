# Gestión multi-batería

La integración gestiona hasta **6 baterías** como un sistema agregado, distribuyendo la potencia de forma inteligente para maximizar la eficiencia.

## Principio de eficiencia

Basándose en las curvas de eficiencia medidas de las Venus, las baterías se activan solo cuando la potencia total supera el **punto de cruce de eficiencia** — la potencia a partir de la cual repartir la carga entre dos baterías resulta más eficiente que operar con una sola. Operar con menos baterías activas a mayor potencia es más eficiente que repartir la misma carga entre todas.

Los puntos de cruce (derivados de las mediciones de η externo) son:

| Dirección | Cruce | % del máximo físico (2500 W) |
|---|---:|---:|
| Descarga | 1500 W | 60 % |
| Carga | 1750 W | 70 % |

El umbral de activación se calcula dinámicamente como `cruce_W ÷ máximo_configurado_W`, limitado al rango [50 %, 95 %]. Esto significa que los usuarios que configuran un límite de potencia inferior por batería activan baterías adicionales más tarde (más cerca de su máximo configurado), lo que refleja correctamente que su rango de operación se mantiene dentro del pico de eficiencia de una sola batería.

Las siguientes mediciones muestran la potencia DC consumida/entregada, la potencia AC en el contador (pinza interna) y en la toma de pared (pinza externa), y la eficiencia resultante en cada nivel de potencia:

**Carga**

| % de máx. | Consigna (W) | DC interno (W) | AC interno (W) | AC externo (W) | η interno | η externo |
|---:|---:|---:|---:|---:|---:|---:|
| 3 % | 63 | 41 | 58 | 68 | 70,7 % | 60,3 % |
| 5 % | 125 | 105 | 123 | 136 | 85,4 % | 77,2 % |
| 10 % | 250 | 232 | 247 | 262 | 93,9 % | 88,5 % |
| 15 % | 375 | 357 | 372 | 387 | 96,0 % | 92,2 % |
| 20 % | 500 | 481 | 497 | 513 | 96,8 % | 93,8 % |
| 25 % | 625 | 604 | 621 | 639 | 97,3 % | 94,5 % |
| 30 % | 750 | 727 | 743 | 766 | 97,8 % | 94,9 % |
| 35 % | 875 | 850 | 871 | 892 | 97,6 % | 95,3 % |
| 40 % | 1000 | 973 | 995 | 1019 | 97,8 % | 95,5 % |
| 45 % | 1125 | 1095 | 1120 | 1146 | 97,8 % | 95,5 % |
| 50 % | 1250 | 1245 | 1271 | 1274 | 98,0 % | 97,7 % |
| 55 % | 1375 | 1339 | 1369 | 1401 | 97,8 % | 95,6 % |
| 60 % | 1500 | 1460 | 1494 | 1530 | 97,7 % | 95,4 % |
| 65 % | 1625 | 1581 | 1618 | 1658 | 97,7 % | 95,4 % |
| 70 % | 1750 | 1702 | 1743 | 1786 | 97,6 % | 95,3 % |
| 75 % | 1875 | 1823 | 1868 | 1916 | 97,6 % | 95,1 % |
| 80 % | 2000 | 1942 | 1992 | 2044 | 97,5 % | 95,0 % |
| 85 % | 2125 | 2062 | 2117 | 2175 | 97,4 % | 94,8 % |
| 90 % | 2250 | 2183 | 2242 | 2304 | 97,4 % | 94,7 % |
| 95 % | 2375 | 2304 | 2366 | 2436 | 97,4 % | 94,6 % |
| 100 % | 2500 | 2424 | 2491 | 2567 | 97,3 % | 94,4 % |

**Descarga**

| % de máx. | Consigna (W) | DC interno (W) | AC interno (W) | AC externo (W) | η interno | η externo |
|---:|---:|---:|---:|---:|---:|---:|
| 3 % | 63 | 80 | 63 | 60 | 78,8 % | 75,0 % |
| 5 % | 125 | 160 | 124 | 118 | 77,5 % | 73,8 % |
| 10 % | 250 | 284 | 249 | 243 | 87,7 % | 85,6 % |
| 15 % | 375 | 416 | 373 | 368 | 89,7 % | 88,5 % |
| 20 % | 500 | 550 | 498 | 494 | 90,5 % | 89,8 % |
| 25 % | 625 | 685 | 623 | 619 | 90,9 % | 90,4 % |
| 30 % | 750 | 820 | 747 | 745 | 91,1 % | 90,9 % |
| 35 % | 875 | 956 | 872 | 870 | 91,2 % | 91,0 % |
| 40 % | 1000 | 1092 | 997 | 996 | 91,3 % | 91,2 % |
| 45 % | 1125 | 1230 | 1121 | 1121 | 91,1 % | 91,1 % |
| 50 % | 1250 | 1369 | 1246 | 1246 | 91,0 % | 91,0 % |
| 55 % | 1375 | 1507 | 1370 | 1372 | 90,9 % | 91,0 % |
| 60 % | 1500 | 1647 | 1495 | 1497 | 90,8 % | 90,9 % |
| 65 % | 1625 | 1789 | 1620 | 1623 | 90,6 % | 90,7 % |
| 70 % | 1750 | 1931 | 1745 | 1748 | 90,4 % | 90,5 % |
| 75 % | 1875 | 2073 | 1869 | 1874 | 90,2 % | 90,4 % |
| 80 % | 2000 | 2218 | 1994 | 1999 | 89,9 % | 90,1 % |
| 85 % | 2125 | 2362 | 2118 | 2124 | 89,7 % | 89,9 % |
| 90 % | 2250 | 2508 | 2243 | 2250 | 89,4 % | 89,7 % |
| 95 % | 2375 | 2654 | 2368 | 2375 | 89,2 % | 89,5 % |
| 100 % | 2500 | 2801 | 2492 | 2501 | 89,0 % | 89,3 % |

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
| **Potencia** | 10 pp | Umbral de activación derivado del punto de cruce de eficiencia; desactivación = activación − 10 puntos porcentuales |

## Distribución de potencia

Una vez seleccionadas las baterías activas, la potencia total calculada por el [controlador PD](pd-controller.md) se reparte entre ellas proporcionalmente, respetando los límites individuales de potencia y SOC de cada una.

## Exclusión de baterías sin respuesta

Cuando una batería no entrega la potencia solicitada de forma reiterada — por ejemplo, por un fallo de comunicación Modbus o por una autoprotección del firmware — la integración lo detecta y la retira temporalmente del grupo activo.

Una batería se marca como sin respuesta cuando su potencia entregada es inferior al 5 % de la consigna durante **3 ciclos de control consecutivos**. Una vez marcada, entra en una **ventana de exclusión de 5 minutos** durante la cual no recibe nuevas consignas y las baterías restantes absorben su parte de la carga. Al expirar la ventana, el contador de fallos se reinicia y la batería vuelve a ser elegible.

Este mecanismo impide que una sola batería con problemas degrade silenciosamente el rendimiento del sistema sin generar alarmas ni requerir intervención manual.

## Modos compatibles

La distribución multi-batería se aplica en todos los modos:
- Control PD normal
- Carga solar
- Carga predictiva desde la red

![Estado de baterías múltiples en Home Assistant](../assets/screenshots/features/multi-battery-entities.png){ width="700"  style="display: block; margin: 0 auto;"}
