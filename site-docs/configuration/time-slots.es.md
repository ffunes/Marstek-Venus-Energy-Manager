# Franjas horarias

Las franjas horarias definen ventanas de tiempo en las que la batería **está autorizada a descargar**. Fuera de estas ventanas, la batería solo carga (o permanece en espera).

## Cuándo usarlas

- Reservar energía para los picos de consumo vespertinos o nocturnos.
- Optimizar el arbitraje tarifario (descarga en horas caras, carga en horas baratas).
- Controlar la descarga en función de los días de la semana.

---

## Configuración de una franja

| Campo | Descripción |
|---|---|
| **Hora inicio / fin** | Ventana de la franja (p. ej. `14:00` – `18:00`) |
| **Días** | Días de la semana en los que aplica |
| **Aplicar a carga** | Si está activo, la franja también restringe la carga |
| **Potencia objetivo de red** | Nivel de red al que el controlador regula durante la franja |

### Potencia objetivo de red

Por defecto `0 W` (flujo de red cero). Rango: `-500 W` a `+500 W`.

| Valor | Efecto |
|---|---|
| `0 W` | Autoconsumo máximo, sin exportación |
| `< 0` (p. ej. `-150 W`) | Mantiene exportación ligera (útil si la compensación es rentable) |
| `> 0` (p. ej. `+200 W`) | Permite importación ligera (reduce ciclado de la batería) |

![Formulario de configuración de franja horaria](../assets/screenshots/configuration/time-slot-form.png){ width="650"  style="display: block; margin: 0 auto;"}

---

## Franjas y carga predictiva

Cuando la carga predictiva está activa, el controlador puede usar las franjas como ventanas de carga desde la red. Consulta [Carga predictiva – Modo Franja Horaria](predictive-charging/time-slot.md) para más detalles.
