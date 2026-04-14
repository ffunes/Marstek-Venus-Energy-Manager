# Solución de problemas

## Compatibilidad con la app de Marstek

**No es necesario realizar ningún cambio en la app de Marstek** para que la integración funcione — incluyendo desactivar el medidor de energía o modificar cualquier configuración. La integración opera junto a la app sin requerir ningún ajuste desde ella.

Sin embargo, **no cambies ningún modo de operación ni configuración desde la app de Marstek mientras la integración de Home Assistant esté en ejecución**. Hacerlo romperá la compatibilidad y necesitarás deshabilitar y volver a habilitar la integración para restaurar el funcionamiento normal.

---

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

## Recibo una notificación de alarma o fallo de batería

La integración monitoriza los registros `Alarm Status` y `Fault Status` de la batería (solo v2) cada 5 segundos. Cuando se activa un nuevo bit, aparece una notificación persistente en Home Assistant con el nombre exacto de la condición (p. ej. *BAT Overvoltage*, *Fan Abnormal Warning*). La notificación se descarta automáticamente cuando todas las condiciones se resuelven.

**Niveles de severidad de la notificación:**

| Prefijo del título | Significado |
|---|---|
| 🚨 Battery Fault | Al menos un bit de fallo está activo — requiere atención inmediata |
| ⚠️ Battery Warning | Al menos un bit de alarma está activo — conviene monitorizar la situación |

**Qué hacer al recibir una notificación:**

1. Consulta el sensor **`System Alarm Status`** en el dispositivo *Marstek Venus System* — sus atributos indican qué batería está afectada y qué condiciones están activas.
2. Revisa los sensores **Alarm Status** y **Fault Status** individuales en el dispositivo de la batería afectada para ver el estado completo.
3. Consulta la documentación de Marstek Venus o la app de Marstek para el código de fallo concreto.
4. Si la condición no se resuelve sola, considera reiniciar la batería o contactar con el soporte de Marstek.

!!! note "Solo baterías v2"
    La monitorización de registros de alarma y fallo solo está disponible para hardware v2. Las baterías v3, vA y vD no exponen estos registros vía Modbus.

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

## El dispositivo de medida no está disponible o pierde conexión

Si el sensor de red (por ejemplo, un medidor con conexión Wi-Fi inestable) se desconecta, el controlador se comporta de forma diferente según cómo falle el sensor.

### El sensor reporta `unavailable` o `unknown`

El bucle de control sale inmediatamente sin enviar ningún nuevo comando. Las baterías **mantienen el último nivel de potencia comandado** hasta que el sensor vuelva a estar disponible.

### El sensor se congela (el valor deja de actualizarse)

La integración detecta que la marca de tiempo del sensor no ha cambiado:

- Durante hasta **15 ciclos (~30 segundos)** mantiene el último comando sin cambios.
- Pasado ese período de gracia, realiza un nuevo cálculo de seguridad usando el valor congelado, con el término derivativo suprimido para evitar picos de potencia.

### Resumen

| Estado del sensor | Comportamiento |
|---|---|
| `unavailable` / `unknown` | El bucle de control sale — las baterías mantienen la última potencia |
| Valor congelado (sin nuevas lecturas) | ~30 s de gracia, luego recalcula con el valor obsoleto |

!!! warning "Sin fallback automático a 0 W"
    Si el medidor se pierde mientras la batería estaba descargando a, por ejemplo, 2000 W, **seguirá descargando a 2000 W** hasta que el medidor se recupere. No hay ningún temporizador integrado que lleve la batería a reposo. Considera mejorar la fiabilidad del Wi-Fi de tu medidor, o usar una alternativa cableada o Zigbee si los cortes son frecuentes.

---

## Reportar un problema — Sensor de Resumen de Configuración

Al abrir un informe de error o pedir ayuda, es muy útil compartir la configuración actual de la integración. El sensor **Resumen de Configuración** expone toda la configuración como atributos de la entidad.

**Cómo activarlo:**

1. Ve a **Configuración → Dispositivos y servicios → Marstek Venus Energy Manager**.
2. Selecciona el dispositivo **Marstek Venus System**.
3. Busca el sensor **Resumen de Configuración** (está oculto por defecto) y actívalo.
4. Abre la tarjeta de detalle del sensor y comparte sus atributos (estado + atributos).

El sensor es de solo lectura y diagnóstico. No afecta al comportamiento de la integración de ninguna manera.

---

## Registros de depuración

Activa el nivel de log `debug` para la integración pulsando en "Enable debug logging" en la configuración de la integración. Una vez que lo hayas ejecutado durante el tiempo apropiado, desactívalo para no llenar los logs, y se creará un archivo de log con la información de depuración.
