# Configuración de baterías

## Número de baterías

Selecciona cuántas unidades Marstek Venus tienes (1–6). La integración te pedirá configurar cada una por separado.

![Control de número de baterías](../assets/screenshots/configuration/battery-slider.png){ width="650"  style="display: block; margin: 0 auto;"}

---

## Parámetros por batería

| Parámetro | Descripción | Valor por defecto |
|---|---|---|
| **Nombre** | Nombre identificativo (p. ej. "Venus 1") | — |
| **Host** | IP del conversor Modbus TCP | — |
| **Puerto** | Puerto TCP Modbus | `502` |
| **Versión** | Modelo de la batería | — |
| **Potencia máx. carga/descarga** | Potencia nominal de la instalación | — |
| **SOC máximo** | Detiene la carga al alcanzar este % | `100 %` |
| **SOC mínimo** | Detiene la descarga al alcanzar este % | `12 %` |
| **Histéresis de carga** | Margen para evitar ciclos rápidos cerca del límite | — |
| **Umbral offgrid backup** | Carga offgrid mínima (W) para considerarse un evento de backup activo | `50 W` |

### Versiones de batería

| Versión | Modelos |
|---|---|
| `v1/v2` | Venus E v1, Venus E v2 |
| `v3` | Venus E v3 |
| `vA` | Venus A |
| `vD` | Venus D |

!!! warning "Potencia máxima 2500 W"
    Usa el modo **2500 W** solo si tu instalación doméstica puede soportar esa potencia de forma segura.

![Formulario de conexión a la batería](../assets/screenshots/configuration/battery-connection-form.png){ width="650"  style="display: block; margin: 0 auto;"}
![Formulario de configuración de batería](../assets/screenshots/configuration/battery-config-form.png){ width="650"  style="display: block; margin: 0 auto;"}

---

## SOC y límites de potencia en tiempo de ejecución

Los valores de SOC máximo/mínimo y potencia máxima de carga/descarga se pueden ajustar en cualquier momento desde los sliders de la integración sin necesidad de reconfigurar. Los cambios se persisten y se restauran en cada reinicio de Home Assistant.

![Sliders de SOC y potencia](../assets/screenshots/configuration/battery-runtime-sliders.png){ width="650"  style="display: block; margin: 0 auto;"}

---

## Umbral offgrid backup en tiempo de ejecución

La entidad numérica **Umbral Offgrid Backup** (visible en la tarjeta de dispositivo de cada batería, entre las entidades de configuración) permite ajustar el umbral en cualquier momento sin entrar al flujo de opciones. Auméntalo si tu batería tiene cargas permanentes pequeñas en el puerto offgrid — como un switch PoE, router o cámaras IP — que de otro modo mantendrían la batería permanentemente excluida del control PD.

| Escenario | Umbral recomendado |
|---|---|
| Sin cargas permanentes en offgrid | `0 W` (cualquier carga activa la exclusión) |
| Cargas pequeñas (router + switch, ~20–40 W) | `50 W` (valor por defecto) |
| Cargas más pesadas (NAS, AP, cámaras, ~80–120 W) | `150 W` |

!!! tip "Cómo funciona"
    Cuando el switch **Función Backup** está activado y la carga offgrid medida supera el umbral, la batería queda excluida del control PD y se gestiona de forma autónoma. Se aplica un período de enfriamiento de 5 minutos tras bajar del umbral, para evitar enviar comandos inmediatamente después de que termine un evento de backup.

