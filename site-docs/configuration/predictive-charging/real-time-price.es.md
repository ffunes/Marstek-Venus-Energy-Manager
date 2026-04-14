# Carga predictiva — Modo Precio en Tiempo Real

Activa o desactiva la carga desde la red en cada ciclo del controlador (~2,5 s) en función del **precio actual de la electricidad**.

A diferencia del Modo Precio Dinámico, no requiere previsión de precios ni evaluación nocturna. Reacciona puramente al precio en curso.

## Configuración

| Campo | Descripción |
|---|---|
| **Sensor de precio** | Cualquier sensor HA con el precio del periodo actual (PVPC, Nordpool, CKW…) |
| **Umbral fijo de precio** | Precio por debajo del cual se activa la carga |
| **Sensor de precio medio diario** | (Opcional) Umbral dinámico en lugar del valor fijo |
| **Descargar solo cuando el precio supere el umbral** | (Opcional) Descarga condicionada al precio actual — ver abajo |

![Formulario de configuración — Modo Precio en Tiempo Real](../../assets/screenshots/configuration/predictive-charging/real-time-price-form.png){ width="650"  style="display: block; margin: 0 auto;"}

## Comportamiento de carga

Cada ciclo (~2,5 s) el controlador evalúa si arrancar o detener la carga desde la red:

```
Si precio_actual ≤ umbral:
    Y si (batería + solar) < consumo_esperado:
        → Activar carga desde la red
Si precio_actual > umbral:
    → Desactivar carga desde la red
```

El balance energético (batería + solar vs. consumo esperado) se evalúa igualmente antes de arrancar la carga, igual que en los otros modos.

### Determinación del umbral de carga

El umbral se resuelve en este orden de prioridad:

1. **Sensor de precio medio diario** — si está configurado y disponible, su valor es el umbral dinámico.
2. **Umbral fijo de precio** — valor numérico estático configurado en el flujo de configuración.

Si ninguno está disponible, el modo no actúa.

---

## Control de descarga por precio

La opción **"Descargar solo cuando el precio supere el umbral"** añade una condición adicional al comportamiento de descarga, independiente de la carga.

Cuando está activa, en **cada ciclo del controlador (~2,5 s)** se comprueba si el precio actual justifica la descarga usando el mismo umbral que para la carga:

```
Si precio_actual > umbral:
    → Descarga permitida (el controlador PD opera con normalidad)
Si precio_actual ≤ umbral:
    → Descarga BLOQUEADA (la batería se mantiene en espera)
```

La lógica inversa a la de carga: se carga cuando el precio es bajo, se descarga cuando es alto.

### Interacción con franjas horarias

Si tienes franjas de descarga configuradas, **ambas condiciones deben cumplirse**:

```
Descarga permitida = dentro_de_franja_horaria AND precio_actual > umbral
```

### Efecto en el controlador PD

Cuando la descarga está bloqueada por precio, el controlador congela completamente su estado (potencia a 0, sin actualización del término derivativo), igual que ocurre durante una restricción de franja horaria. La batería se reactiva sin perturbaciones en cuanto el precio supera el umbral.

---

## Diferencias respecto a Precio Dinámico

| Característica | Precio Dinámico | Precio Tiempo Real |
|---|---|---|
| Previsión de precios necesaria | ✅ | ❌ |
| Evaluación nocturna (00:05) | ✅ | ❌ |
| Reacción al precio en vivo | ❌ | ✅ |
| Selección de horas óptimas | ✅ | ❌ |
| Umbral de descarga | Media del día (calculada a las 00:05) | Umbral configurable (fijo o sensor dinámico) |
