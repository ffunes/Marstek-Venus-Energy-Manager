# Sensor principal

El primer paso configura las fuentes de datos globales de la integración.

## Sensor de consumo de red

Sensor de Home Assistant que mide el intercambio de potencia con la red (en **W** o **kW**).

!!! tip "Sensores compatibles"
    Cualquier sensor que exponga la potencia de red funciona: Shelly EM, Shelly EM3, Neurio, integraciones de contador inteligente (e.g. `sensor.grid_power`).

!!! warning "Frecuencia de actualización"
    El sensor debe actualizarse lo más rápido posible. El controlador opera cada **2,5 segundos** y toma decisiones basadas en la última lectura disponible — cuanto más antigua sea la lectura, menos precisa será la respuesta.

    El consumo del hogar puede variar varios kilovatios en fracciones de segundo (arranque de electrodomésticos, horno, lavadora…). Un sensor que reporta cada 10 segundos o más introduce un desfase que hace que el controlador reaccione a una situación que ya no existe, provocando sobreoscilaciones o correcciones innecesarias.

    **Recomendado: actualización cada 1–2 segundos.** Los dispositivos como Shelly EM/EM3 soportan este intervalo de forma nativa.

### Detección automática de kW

Si el atributo `unit_of_measurement` del sensor es `kW`, la integración multiplica el valor por 1000 automáticamente.

### Signo invertido

Activa **"Signo del medidor invertido"** si tu sensor usa la convención opuesta:

| Convención | Importación | Exportación |
|---|---|---|
| Estándar (por defecto) | Valor positivo | Valor negativo |
| Invertida | Valor negativo | Valor positivo |

Déjalo desactivado si no estás seguro.

---

## Sensor de previsión solar *(opcional)*

Sensor que proporciona la producción solar estimada para mañana, en **kWh** o **Wh**.

Configurarlo aquí lo pone a disposición de:

- **Carga predictiva** (modos Franja Horaria y Precio Dinámico)
- **Retraso de carga solar**

También puedes dejarlo en blanco y configurarlo más tarde en esas secciones específicas.

---

## Sensor de consumo del hogar *(opcional)*

Sensor de potencia (W o kW) que mide el consumo eléctrico total del hogar.

Cuando está configurado, la integración integra la lectura del sensor en el tiempo — únicamente durante la **franja solar+batería** (fuera de la franja de carga desde red) — para obtener un valor diario en kWh. Esto sustituye al método de estimación por defecto, que deriva el consumo a partir de la descarga de la batería + importación de red en SOC mínimo.

**Cuándo configurarlo:**

- Tienes un pinzímetro, Shelly EM u otro dispositivo que mide la carga total del hogar.
- Quieres que la carga predictiva y el retraso de carga solar usen datos de consumo reales.
- Tu producción solar varía significativamente de semana en semana (semanas muy soleadas hacen que el método por defecto subestime la demanda real).

**Cómo funciona:**

| Modo | Fuente de consumo |
|------|------------------|
| Sensor configurado | Integración del sensor de potencia (W→kWh) durante la franja solar+batería |
| Sin sensor | Descarga de batería + importación de red en SOC mínimo (comportamiento actual) |

La integración acumula energía únicamente durante la franja solar+batería (fuera de la franja de carga configurada). Si no hay franja configurada, acumula durante todo el día. El contador se reinicia a medianoche y sobrevive reinicios de HA.

El consumo diario resultante alimenta el mismo historial que leen la carga predictiva y el retraso de carga solar — no es necesaria ninguna configuración adicional en esas secciones.

!!! tip "Unidades admitidas"
    Se aceptan sensores en **W** y en **kW**. La integración lee el atributo `unit_of_measurement` y convierte automáticamente.

![Configuración del sensor principal](../assets/screenshots/configuration/main-sensor.png){ width="600"  style="display: block; margin: 0 auto;"}