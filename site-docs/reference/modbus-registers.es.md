# Registros Modbus

Referencia completa de los registros Modbus utilizados por la integración para cada versión de batería.

!!! info "Documento de referencia completo"
    La tabla completa de registros está disponible en [`docs/registers.md`](../../docs/registers.md) del repositorio.

## Versiones de firmware

| Código | Modelo |
|---|---|
| `a` | Venus A |
| `d` | Venus D |
| `e_v12` | Venus E v1/v2 |
| `e_v3` | Venus E v3 |

## Tipos de datos

| Tipo | Tamaño | Descripción |
|---|---|---|
| `uint16` | 2 bytes | Entero sin signo de 16 bits |
| `int16` | 2 bytes | Entero con signo de 16 bits |
| `uint32` | 4 bytes | Entero sin signo de 32 bits |
| `int32` | 4 bytes | Entero con signo de 32 bits |
| `uint48` | 6 bytes | Entero sin signo de 48 bits |
| `uint64` | 8 bytes | Entero sin signo de 64 bits |
| `char` | variable | Cadena de texto |
| `bit` | — | Campo de bits / flags |

## Registros clave

| Registro | Nombre | Descripción |
|---|---|---|
| 32104 | `battery_soc` | Estado de carga (%) — Venus E v3 |
| 34002 | `battery_soc` | Estado de carga (%) — Venus A/D/E v2 |
| 32102 | `battery_power` | Potencia de la batería (W) — Venus E v3 |
| 30001 | `battery_power` | Potencia de la batería (W) — Venus A/D/E v2 |
| 44000 | — | Corte de carga (manipulado por carga semanal completa) |

Para la tabla completa consulta el [documento de registros](../../docs/registers.md).
