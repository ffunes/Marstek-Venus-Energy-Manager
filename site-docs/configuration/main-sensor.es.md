# Sensor principal

El primer paso configura las fuentes de datos globales de la integración.

## Sensor de consumo de red

Sensor de Home Assistant que mide el intercambio de potencia con la red (en **W** o **kW**).

!!! tip "Sensores compatibles"
    Cualquier sensor que exponga la potencia de red funciona: Shelly EM, Shelly EM3, Neurio, integraciones de contador inteligente (e.g. `sensor.grid_power`).

!!! warning "Frecuencia de actualización"
    El sensor debe actualizarse lo más rápido posible. El controlador es **dirigido por eventos** —recalcula cada vez que este sensor publica un valor nuevo—, así que la frecuencia de actualización del sensor *es* la frecuencia de control: un sensor más rápido implica una respuesta más rápida y precisa. (Un watchdog de 2 segundos sigue ejecutando el ciclo si el sensor se queda en silencio.)

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

## Potencia máxima contratada

La potencia contratada de tu conexión de red, en **W** (por defecto `7000`).

La integración limita la carga de las baterías para que la **importación de red proyectada nunca supere este límite**, evitando que salte el diferencial. Aplica en **todos los modos** — control normal de setpoint, un objetivo/offset positivo, balance neto horario y carga predictiva desde red — no solo al cargar desde la red de forma programada. Solo limita la carga; nunca fuerza una descarga.

---

## Sensor de previsión solar *(opcional)*

Sensor que proporciona la producción solar estimada para hoy, en **kWh** o **Wh**.

Configurarlo aquí lo pone a disposición de:

- **Carga predictiva** (modos Franja Horaria y Precio Dinámico)
- **Retraso de carga solar**

También puedes dejarlo en blanco y configurarlo más tarde en esas secciones específicas.

---

## Consumo del hogar *(derivado automáticamente)*

**No hay campo de sensor de consumo del hogar** en la configuración — la integración deriva el consumo total del hogar de sensores que ya tiene:

**Consumo del hogar = Potencia de red + Potencia AC de baterías + Producción solar**

Es el valor que muestra el diagrama de flujo de energía y el sensor `sensor.marstek_venus_system_home_consumption`, y alimenta el historial de 7 días que usan la carga predictiva y el retraso de carga. La acumulación corre solo durante la franja solar+batería (fuera de la franja de carga; todo el día si no hay franja); el contador se reinicia a medianoche y sobrevive reinicios de HA.

!!! note "Sensor de hogar heredado"
    Instalaciones creadas antes de quitar este campo pueden conservar un `household_consumption_sensor` guardado en su config. Se honra **solo cuando no hay sensor de producción solar configurado** — con sensor solar, el valor derivado es exacto y preferido, así que el guardado se ignora.

![Configuración del sensor principal](../assets/screenshots/configuration/main-sensor.png){ width="600"  style="display: block; margin: 0 auto;"}