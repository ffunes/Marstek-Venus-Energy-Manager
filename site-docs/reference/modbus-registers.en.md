# Modbus registers

Complete reference of the Modbus registers used by the integration for each battery version.

!!! info "Full reference document"
    The complete register table is available in [`docs/registers.md`](../../docs/registers.md) in the repository.

## Firmware versions

| Code | Model |
|---|---|
| `a` | Venus A |
| `d` | Venus D |
| `e_v12` | Venus E v1/v2 |
| `e_v3` | Venus E v3 |

## Data types

| Type | Size | Description |
|---|---|---|
| `uint16` | 2 bytes | Unsigned 16-bit integer |
| `int16` | 2 bytes | Signed 16-bit integer |
| `uint32` | 4 bytes | Unsigned 32-bit integer |
| `int32` | 4 bytes | Signed 32-bit integer |
| `uint48` | 6 bytes | Unsigned 48-bit integer |
| `uint64` | 8 bytes | Unsigned 64-bit integer |
| `char` | variable | Text string |
| `bit` | — | Bit field / flags |

## Key registers

| Register | Name | Description |
|---|---|---|
| 32104 | `battery_soc` | State of charge (%) — Venus E v3 |
| 34002 | `battery_soc` | State of charge (%) — Venus A/D/E v2 |
| 32102 | `battery_power` | Battery power (W) — Venus E v3 |
| 30001 | `battery_power` | Battery power (W) — Venus A/D/E v2 |
| 44000 | — | Charging cutoff (manipulated by weekly full charge) |

For the full table see the [register reference document](../../docs/registers.md).
