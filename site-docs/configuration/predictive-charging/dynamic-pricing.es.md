# Carga predictiva — Modo Precio Dinámico

Selecciona automáticamente las **horas más baratas del día** para cubrir el déficit energético calculado.

## Integraciones de precio compatibles

- **Nordpool**
- **PVPC** (ESIOS REE, España)
- **CKW** (Suiza)

## Configuración

| Campo | Descripción |
|---|---|
| **Tipo de integración de precios** | Nordpool / PVPC / CKW |
| **Sensor de precio** | Entidad HA con el precio actual (y atributos de previsión horaria) |
| **Umbral máximo de precio** | (Opcional) Precio techo; no carga aunque la hora sea "barata" si supera este valor |
| **Potencia ICP contratada** | Límite de red para calcular la duración de carga necesaria |
| **Descargar solo cuando el precio supere la media diaria** | (Opcional) Descarga condicionada al precio actual — ver abajo |

![Formulario de configuración — Modo Precio Dinámico](../../assets/screenshots/configuration/predictive-charging/dynamic-pricing-form.png){ width="650"  style="display: block; margin: 0 auto;"}

## Evaluación diaria (00:05)

A las 00:05 el controlador:

1. Calcula el déficit energético (batería + solar vs. consumo esperado).
2. Recupera los precios horarios del día de la integración configurada.
3. Selecciona las horas más baratas necesarias para cubrir el déficit.
4. Calcula y almacena el **precio medio del día** a partir del perfil horario de precios.
5. Programa los slots de carga para el día.

### Lógica de reintentos

Si los datos de precios no están disponibles a las 00:05, el sistema reintenta cada 15 minutos durante la primera hora.

### Reinicio de HA a mitad del día

Si HA se reinicia después de la ventana de las 00:05 sin evaluación previa, el controlador lanza una evaluación automática en el arranque (tras 15 segundos) considerando solo los slots del día actual.

---

## Control de descarga por precio

La opción **"Descargar solo cuando el precio supere la media diaria"** añade una condición adicional al comportamiento de descarga.

Cuando está activa, en **cada ciclo del controlador (~2,5 s)** se evalúa si el precio actual permite la descarga:

```
Si precio_actual > precio_medio_del_día:
    → Descarga permitida (el controlador PD opera con normalidad)
Si precio_actual ≤ precio_medio_del_día:
    → Descarga BLOQUEADA (la batería se mantiene en espera)
```

El precio medio del día se calcula automáticamente durante la evaluación de las 00:05 a partir del perfil horario de precios. El objetivo es preservar la batería para las horas más caras del día.

### Umbral de respaldo

Si la evaluación de las 00:05 aún no se ha ejecutado (p. ej. HA recién arrancado antes de medianoche), el umbral cae de forma automática al **umbral máximo de precio** configurado. Si tampoco hay umbral fijo configurado, el control de descarga no actúa.

### Interacción con franjas horarias

Si tienes franjas de descarga configuradas, **ambas condiciones deben cumplirse** para que la batería descargue:

```
Descarga permitida = dentro_de_franja_horaria AND precio_actual > precio_medio
```

Fuera de la franja nunca descarga. Dentro de la franja, solo descarga si el precio es suficientemente alto.

### Efecto en el controlador PD

Cuando la descarga está bloqueada por precio, el controlador congela completamente su estado (potencia a 0, sin actualización del término derivativo), igual que ocurre durante una restricción de franja horaria. La batería se reactiva sin perturbaciones en cuanto el precio vuelve a superar la media.

---

## Atributos de diagnóstico

El sensor binario `predictive_charging_active` expone:

| Atributo | Descripción |
|---|---|
| `charging_needed` | Si se necesita carga según el balance |
| `selected_hours` | Horas seleccionadas con sus precios individuales |
| `average_price` | Precio medio de las horas seleccionadas |
| `estimated_cost` | Coste estimado de la carga |
| `evaluation_timestamp` | Cuándo se realizó la última evaluación |
| `price_data_status` | Estado del sensor de precios (`ok (N slots)`, `sensor_unavailable`, `no_slots`, `not_evaluated`) |

![Atributos del sensor predictive_charging_active](../../assets/screenshots/configuration/predictive-charging/diagnostic-attributes.png){ width="650"  style="display: block; margin: 0 auto;"}
