# Solución de problemas

## La batería no responde a los comandos

1. Verifica que el conversor Modbus TCP (Elfin-EW11 o similar) está accesible por IP desde Home Assistant.
2. Comprueba que el puerto configurado es correcto (por defecto `502`).
3. Revisa que el switch **RS485 Control Mode** está activado.
4. Asegúrate de que la versión de batería configurada coincide con el hardware real.

!!! note "Delay para v3/vA/vD"
    Las baterías v3, vA y vD requieren al menos 150 ms entre mensajes Modbus consecutivos. La integración lo aplica automáticamente según la versión configurada.

---

## El controlador PD oscila

El sistema cambia continuamente entre carga y descarga.

**Posibles causas y soluciones:**

| Causa | Solución |
|---|---|
| Deadband demasiado pequeño | El ±40 W por defecto es adecuado para la mayoría de instalaciones |
| Sensor de red con latencia alta | Usa un sensor con actualización frecuente (1–2 s) |
| Cargas con arranque repentino | Configura la carga como [dispositivo excluido](configuration/excluded-devices.md) |

---

## Los valores de SOC/potencia no se persisten tras reiniciar HA

A partir de la v1.5.0 este problema está corregido. Los cambios en sliders de SOC y potencia se guardan inmediatamente en la configuración y se restauran en cada reinicio.

Si persiste el problema, verifica que estás usando la versión **1.5.0** o superior.

---

## La carga predictiva no se activa

1. Verifica que el sensor de previsión solar está disponible y tiene valor.
2. Comprueba el atributo `price_data_status` del sensor `predictive_charging_active` (modo Precio Dinámico).
3. Revisa las notificaciones de HA: la evaluación de las 00:05 reporta el resultado.
4. Asegúrate de que el balance energético realmente requiere carga (puede que haya suficiente energía).

---

## El switch RS485 se reactiva solo tras reiniciar

Corregido en v1.5.0. La preferencia del usuario se persiste y se restaura en el arranque.

---

## Registros de depuración

Activa el nivel de log `debug` para la integración pulsando en "Enable debug logging" en la configuración de la integración. Una vez que lo hayas ejecutado durante el tiempo apropiado, desactívalo para no llenar los logs, y se creará un archivo de log con la información de depuración.
