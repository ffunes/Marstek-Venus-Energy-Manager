# Dispositivos excluidos

Permite "enmascarar" cargas pesadas para que la batería no intente cubrirlas.

## Caso de uso típico

Si tienes un cargador de vehículo eléctrico de 7 kW y una batería de 2,5 kW, sin exclusión la batería intentará compensar todo el consumo del cargador y se agotará rápidamente. Con la exclusión activa, el controlador ignora esa potencia y la batería solo gestiona el resto del hogar.

---

## Configuración de un dispositivo excluido

| Campo | Descripción |
|---|---|
| **Sensor de potencia** | Entidad HA que mide la potencia del dispositivo (p. ej. `sensor.wallbox_power`) |
| **Incluido en el consumo** | Marca si tu sensor principal **ya** incluye esta carga |
| **Permitir excedente solar** | Si está activo, la batería no cargará para compensar este dispositivo cuando hay excedente solar. También puede activarse en tiempo real desde una entidad switch (ver más abajo). |

### ¿Incluido en el consumo?

```
Sensor principal lee: toda la casa
Cargador VE forma parte de "toda la casa" → ✅ Incluido en el consumo

Sensor principal lee: solo circuito doméstico
Cargador VE está en circuito separado → ❌ No incluido en el consumo
```

La integración usa esta configuración para calcular correctamente el consumo neto sin el dispositivo excluido.

![Formulario de dispositivo excluido](../assets/screenshots/configuration/excluded-device-form.png){ width="650"  style="display: block; margin: 0 auto;"}

---

## Switch de excedente solar

Por cada dispositivo excluido se crea automáticamente una entidad switch **Solar Surplus – \<nombre del dispositivo\>** que refleja el ajuste *Permitir excedente solar* y puede activarse en cualquier momento sin entrar en el flujo de opciones.

Esto permite cambiar la prioridad de carga desde automatizaciones — por ejemplo:

- Activar cuando el VE está conectado, para que el solar cargue primero el coche.
- Desactivar a una hora programada para que la batería capture el excedente de la mañana.
- Reaccionar al SOC de la batería: activar por encima del 80 %, desactivar por debajo del 50 %.

El estado del switch se persiste en la entrada de configuración y sobrevive reinicios.
