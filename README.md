# Mikrotik Router — Home Assistant Integration

![GitHub release (latest by date)](https://img.shields.io/github/v/release/Csontikka/ha-mikrotik-router?style=plastic)
[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=plastic)](https://github.com/hacs/integration)
[![Security Rating](https://sonarcloud.io/api/project_badges/measure?project=Csontikka_ha-mikrotik-router&metric=security_rating)](https://sonarcloud.io/summary/new_code?id=Csontikka_ha-mikrotik-router)
[![Reliability Rating](https://sonarcloud.io/api/project_badges/measure?project=Csontikka_ha-mikrotik-router&metric=reliability_rating)](https://sonarcloud.io/summary/new_code?id=Csontikka_ha-mikrotik-router)
[![Maintainability Rating](https://sonarcloud.io/api/project_badges/measure?project=Csontikka_ha-mikrotik-router&metric=sqale_rating)](https://sonarcloud.io/summary/new_code?id=Csontikka_ha-mikrotik-router)

Full-featured Home Assistant integration for MikroTik routers running **RouterOS 7+**. Monitor system resources, control firewall rules, track network devices, manage WireGuard peers, containers, and more — all from your HA dashboard. Supports multiple routers simultaneously.

## Features

### System Monitoring

CPU load, memory/HDD usage, uptime, temperatures (CPU, board, PHY, switch), voltage, power consumption, PSU metrics (current/voltage for PSU1/PSU2), fan speeds (fan1-fan4), UPS status, GPS coordinates. Each router also gets a reboot button entity.

> **[SCREENSHOT]** System sensors overview — CPU, memory, uptime, temperature entities for a router device

### Network Interfaces

Per-interface monitoring: link status (binary sensor), enable/disable (switch), TX/RX traffic rates and totals (optional), IP address sensor per interface, SFP status and information, PoE status/control/consumption, connected device MAC/IP info per interface.

> **[SCREENSHOT]** Interface entities — port binary sensor, traffic sensors, IP address sensor, and port switch for one interface

### Firewall & Routing Rules

Monitor and control individual rules — each gets a switch entity:

- NAT rules
- Mangle rules
- Filter rules
- Routing rules

More information: [MikroTik Firewall documentation](https://help.mikrotik.com/docs/display/ROS/Firewall)

> **[SCREENSHOT]** Firewall switches — NAT/filter/mangle switch entities

### Device Tracking

ARP-based network host presence tracking. Configurable timeout (default 180s). Shows MAC address, IP, and connected interface as attributes.

> **[SCREENSHOT]** Device tracker entity — tracked device with its attributes

### WireGuard (RouterOS 7+)

Each WireGuard peer gets its own device with:

- **Switch**: enable/disable peer
- **Binary sensor**: connected status (based on last handshake < 3 minutes)
- **Sensors**: RX bytes, TX bytes, last handshake

Peer display name: `name` field, then `comment`, then first 8 chars of public key.

Enable via integration options -> WireGuard peer sensors.

> **[SCREENSHOT]** WireGuard peer device — switch, binary sensor, and traffic sensors

### Containers (RouterOS 7+)

Each container gets its own device with:

- **Switch**: start/stop container
- **Sensor**: status (running/stopped/pulling/building/error)
- **Attributes**: tag, OS, arch, interface, memory/CPU usage

Enable via integration options -> Container sensors.

> **[SCREENSHOT]** Container device — container switch and status sensor

### Client Traffic

Per-device bandwidth monitoring. 2 sensors per tracked device (total TX/RX).

Uses Kid Control backend. The integration auto-creates an `ha-monitoring` profile (unrestricted) on the router when enabled. If the API user lacks write permission, a warning is logged with the manual command:

```
/ip/kid-control/add name=ha-monitoring mon=0s-1d tue=0s-1d wed=0s-1d thu=0s-1d fri=0s-1d sat=0s-1d sun=0s-1d
```

Without the required backend, sensors show "unavailable" instead of 0.

> **[SCREENSHOT]** Client traffic sensors — TX/RX sensors for a tracked client device

### Additional Features

- **Kid Control** — enable/disable/pause rules per child profile
- **PPP Users** — monitor and control PPP secrets and active connections (v7+)
- **Simple Queues** — enable/disable queue rules (note: FastTracked packets bypass queues)
- **Captive Portal** — track hotspot/guest portal authorized clients
- **Scripts** — execute RouterOS scripts via button entities
- **Netwatch** — monitor host reachability (binary sensor per watched host)
- **Environment Variables** — read RouterOS script environment variable values
- **IP Cloud** — public IP address sensor via MikroTik cloud service
- **Device Mode & Packages** — diagnostic sensors showing enabled features and installed packages
- **CAPsMAN** (v6) / **WiFi** (v7) — wireless client detection (auto-detected)

### Firmware Updates

Update RouterOS and RouterBoard firmware directly from Home Assistant.

- RouterOS update entity with changelog
- RouterBoard firmware update entity

> **[SCREENSHOT]** Update entities — RouterOS and RouterBoard update entities

### Services

- **Wake-on-LAN** (`mikrotik_router.send_magic_packet`): send WoL magic packet through the router. Parameters: `mac` (required), `interface` (optional).
- **API Test** (`mikrotik_router.api_test`): diagnostic service for raw RouterOS API queries or coordinator data inspection. Use in Developer Tools -> Services with "Return response" enabled. Parameters: `path` (required), `limit` (optional, default 10), `host` (optional), `coordinator_data` (optional).

## Feature Availability

| Feature | RouterOS 7+ | RouterOS 6* | Optional |
|---------|:---:|:---:|:---:|
| System monitoring (CPU, memory, temps, fans, PSU, uptime) | ✓ | ✓ | No |
| Network interfaces (status, traffic, IP address) | ✓ | ✓ | Traffic: Yes |
| Firewall rules (NAT, mangle, filter) | ✓ | ✓ | Yes |
| Routing rules | ✓ | ✓ | Yes |
| Device tracking (ARP) | ✓ | ✓ | Yes |
| WireGuard peers | ✓ | — | Yes |
| Containers | ✓ | — | Yes |
| Client traffic (Kid Control) | ✓ | — | Yes |
| Kid Control | ✓ | ✓ | Yes |
| PPP users | ✓ | — | Yes |
| Simple queues | ✓ | ✓ | Yes |
| Captive portal | ✓ | ✓ | Yes |
| Scripts | ✓ | ✓ | Yes |
| Netwatch | ✓ | ✓ | Yes |
| Environment variables | ✓ | ✓ | Yes |
| WiFi (wifiwave2/wifi-qcom) | ✓ | — | Auto |
| CAPsMAN (wireless controller) | — | ✓ | Auto |
| UPS monitoring | ✓ | ✓ | Package |
| GPS coordinates | ✓ | ✓ | Package |
| IP Cloud (public IP) | ✓ | ✓ | No |
| Device mode & packages | ✓ | — | No |
| Firmware updates | ✓ | ✓ | No |
| Wake-on-LAN service | ✓ | ✓ | No |
| API Test service | ✓ | ✓ | No |
| Reboot button | ✓ | ✓ | No |
| Multi-router support | ✓ | ✓ | No |

> **\*RouterOS 6 is not officially supported.** Basic features may still work, but v6 is not tested or maintained. Upgrade to RouterOS 7 is strongly recommended.
>
> Active development and testing is done on a **MikroTik hAP ax³** running the latest stable RouterOS 7.

## Installation

This integration is distributed via [HACS](https://hacs.xyz/) as a custom repository.

1. Open HACS -> three-dot menu -> **Custom repositories**
2. URL: `https://github.com/Csontikka/ha-mikrotik-router`
3. Category: **Integration**
4. Search and install **Mikrotik Router**

### Requirements

- Home Assistant 2024.3.0 or later
- RouterOS 7+ (v6 is not officially supported — see [Feature Availability](#feature-availability))
- API user with permissions: `read, write, api, reboot, policy, test, sensitive`
  > All permissions are recommended. Without `write`, switches and Kid Control auto-setup won't work. Without `reboot`, the reboot button is unavailable.

## Configuration

### Initial Setup

1. Create a user on your MikroTik router with the required permissions (see above)
2. In Home Assistant: **Settings -> Devices & Services -> Add Integration -> Mikrotik Router**
3. Enter connection details (host, username, password)

### Connection Options

| Option | Default | Description |
|--------|---------|-------------|
| Port | 0 (auto) | API port (0 = auto-detect: 8728 or 8729 for SSL) |
| SSL Mode | None | `none` (port 8728), `ssl` (8729, self-signed OK), `ssl_verify` (8729, CA required) |
| Scan interval | 30s | Update frequency (minimum 10s) |
| Host tracking timeout | 180s | Seconds before marking a host as away |

### Sensor Presets

During setup, choose a sensor preset:

- **Minimal** — port tracking only
- **Recommended** — ports, NAT, mangle, filter, scripts, netwatch
- **Full** — all sensors enabled (can generate hundreds of entities on large networks)
- **Custom** — manually select each sensor category

### Configurable Traffic Units

Traffic sensors support multiple units: bps, Kbps, Mbps, B/s, KB/s, MB/s — configurable per integration entry.

## Troubleshooting

### Diagnostics Export

Download the integration diagnostics file for bug reports — it includes integration state and the last 1000 debug log entries. Sensitive data (passwords, IPs, MACs) is automatically redacted.

1. **Settings -> Devices & Services**
2. Find **Mikrotik Router** -> click the integration
3. Click the **three-dot menu** -> **Download diagnostics**
4. Attach the `.json` file to your [GitHub issue](https://github.com/Csontikka/ha-mikrotik-router/issues)

### Debug Logs

Debug logs are captured automatically in diagnostics. To also see them in the HA log viewer, add to `configuration.yaml`:

```yaml
logger:
  default: info
  logs:
    custom_components.mikrotik_router: debug
```

## Support

Found a bug or have an idea? [Open an issue](https://github.com/Csontikka/ha-mikrotik-router/issues) — feedback and feature requests are welcome!

## Credits

Originally based on [homeassistant-mikrotik_router](https://github.com/tomaae/homeassistant-mikrotik_router) by [@tomaae](https://github.com/tomaae), licensed under MIT.
