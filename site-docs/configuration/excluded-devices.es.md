# Dispositivos excluidos

Permite "enmascarar" cargas pesadas para que la batería no intente cubrirlas.

## Caso de uso típico

Si tienes un cargador de vehículo eléctrico de 7 kW y una batería de 2,5 kW, sin exclusión la batería intentará compensar todo el consumo del cargador y se agotará rápidamente. Con la exclusión activa, el controlador ignora esa potencia y la batería solo gestiona el resto del hogar.

---

## Configuración de un dispositivo excluido

| Campo | Descripción |
|---|---|
| **Sensor del dispositivo** | Entidad HA que mide la potencia del dispositivo (p. ej. `sensor.wallbox_power`), o un sensor de estado para cargadores VE sin telemetría de potencia. |
| **Incluido en el consumo** | Marca si tu sensor principal **ya** incluye esta carga |
| **Permitir excedente solar** | Si está activo, la batería no cargará para compensar este dispositivo cuando hay excedente solar. También puede activarse en tiempo real desde una entidad switch (ver más abajo). |
| **Cargador VE sin telemetría de potencia** | Marca si el sensor es un sensor de estado que indica `Charging`/`Cargando` en lugar de un valor en vatios. Ver [Cargador VE sin telemetría](#cargador-ve-sin-telemetría-de-potencia) más abajo. |

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

---

## Cargador VE sin telemetría de potencia

Algunas integraciones de cargadores de vehículo eléctrico no exponen un sensor de potencia en tiempo real — solo informan del **estado de carga** (p. ej. `Charging`, `Idle`, `Disconnected`). Esta opción está diseñada para esos cargadores.

Cuando está activa, el campo **Sensor del dispositivo** debe apuntar a la entidad de estado, no a un sensor de potencia. El controlador reconoce cualquier estado que contenga `charg` o `cargand` (sin distinguir mayúsculas), lo que cubre:

- `Charging` (la mayoría de integraciones en inglés)
- `Cargando`, `Cargando VE`, `Cargando Vehículo` (español)

### Comportamiento cuando el VE empieza a cargar

```
t = 0  Estado VE → "Charging" detectado
       Batería forzada a 0 W (carga Y descarga bloqueadas)
       Estado del controlador PD congelado

t = 5 min  Pausa finalizada
           La batería puede cargar con excedente solar
           La descarga permanece bloqueada mientras el VE sigue cargando

t = N  Estado VE → cualquier otro valor (Idle / Disconnected / …)
       Operación normal reanudada
```

### ¿Por qué la pausa de 5 minutos?

Cuando un cargador VE se activa, negocia la corriente disponible con el coche durante una breve fase de handshake. Cualquier descarga de la batería durante esa ventana puede reducir temporalmente la capacidad de red aparente, haciendo que el cargador se estabilice en una corriente más baja. La pausa da tiempo al handshake para completarse antes de que la batería actúe.

### Comparativa con la opción estándar de excedente solar

| | Exclusión estándar + Excedente solar | VE sin telemetría |
|---|---|---|
| Requiere sensor de potencia | Sí | No |
| La batería descarga para el VE | Nunca | Nunca |
| La batería carga con solar mientras el VE carga | Sí | Sí (tras pausa de 5 min) |
| Pausa inicial de 5 minutos | No | Sí |
| Reacciona automáticamente al estado del VE | No | Sí |
