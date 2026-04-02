# Mikrotik Router
![GitHub release (latest by date)](https://img.shields.io/github/v/release/Csontikka/ha-mikrotik-router?style=plastic)
[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=plastic)](https://github.com/hacs/integration)
![Project Stage](https://img.shields.io/badge/project%20stage-Beta-orange.svg?style=plastic)
[![Security Rating](https://sonarcloud.io/api/project_badges/measure?project=Csontikka_ha-mikrotik-router&metric=security_rating)](https://sonarcloud.io/summary/new_code?id=Csontikka_ha-mikrotik-router)
[![Reliability Rating](https://sonarcloud.io/api/project_badges/measure?project=Csontikka_ha-mikrotik-router&metric=reliability_rating)](https://sonarcloud.io/summary/new_code?id=Csontikka_ha-mikrotik-router)

![Mikrotik Logo](https://raw.githubusercontent.com/tomaae/homeassistant-mikrotik_router/master/docs/assets/images/ui/header.png)

Monitor and control your Mikrotik device from Home Assistant.
 * Interfaces:
   * Enable/disable interfaces
   * SFP status and information
   * POE status, control and information
   * Monitor RX/TX traffic per interface
   * Monitor device presence per interface
   * IP, MAC, Link information per an interface for connected devices
   * **IP address sensor per interface** *(added in this fork)*
 * **WireGuard peer sensors and switches** *(added in this fork)*
 * **Container sensors and switches** *(added in this fork)*
 * Enable/disable NAT rule switches
 * Enable/disable Simple Queue switches
 * Enable/disable Mangle switches
 * Enable/disable Filter switches
 * Monitor and control PPP users
 * Monitor UPS
 * Monitor GPS coordinates
 * Captive Portal
 * Kid Control
 * Client Traffic RX/TX WAN/LAN monitoring
 * Device tracker for hosts in network
 * System sensors (CPU, Memory, HDD, Temperature)
 * **Public IP address via IP Cloud** *(added in this fork)*
 * **Device Mode and Packages diagnostic sensors** *(added in this fork)*
 * Check and update RouterOS and RouterBOARD firmware
 * Execute scripts
 * View environment variables
 * Configurable update interval
 * Configurable traffic unit (bps, Kbps, Mbps, B/s, KB/s, MB/s)
 * Supports monitoring of multiple mikrotik devices simultaneously

# Additional Features (this fork)

## Interface IP Address Sensors
Each router interface gets an **IP Address** sensor showing the assigned IP.

- **State**: IP address without mask (e.g. `172.21.11.1`)
- **Attributes**: full address with mask, network, comment, disabled status
- Sensor is grouped under the corresponding interface device in HA
- Multiple IPs on the same interface each get their own sensor entity
- Bridge and virtual interfaces without a network connection are excluded

## IP Cloud — Public Address Sensor
A diagnostic sensor on the System device showing the router's public IP address via the MikroTik IP Cloud service.

- **State**: public IP address (e.g. `80.95.65.203`)
- **Attributes**: `ddns_enabled`, `ddns_hostname`, `ddns_status`, `back_to_home_vpn`
- Fault-tolerant: becomes unavailable if cloud service is disabled

## Wake-on-LAN Service
Send a Wake-on-LAN magic packet through the MikroTik router to wake up any device on the network.

- HA service: `mikrotik_router.send_magic_packet`
- Parameters: `mac` (required), `interface` (optional)
- Works across all configured MikroTik routers simultaneously

## API Test Service
Diagnostic service for querying the RouterOS API directly or inspecting processed coordinator data.

- HA service: `mikrotik_router.api_test`
- **Returns response data** (use in Developer Tools → Services with "Return response" enabled)
- Parameters:
  - `path` (required): RouterOS API path (e.g. `/interface`, `/ip/address`, `/system/resource`)
  - `limit` (optional, default 10): Max items to return (1-500)
  - `host` (optional): Filter to a specific router host
  - `coordinator_data` (optional, default false): Read processed integration data instead of raw API
- Queries all configured routers unless `host` is specified

## Reboot Button
Each router device gets a **Reboot** button entity in Home Assistant.

- Press to reboot the MikroTik device directly from HA
- Requires `reboot` permission on the API user

## WireGuard Peer Sensors
Each WireGuard peer gets its own device with sensors and a switch (RouterOS 7+).

- **Switch**: enable/disable peer
- **Binary sensor**: connected/disconnected (based on last handshake < 3 minutes)
- **Sensors**: RX bytes, TX bytes, Last Handshake (seconds)
- Peer display name: `name` field → `comment` → first 8 chars of public key
- Enable via integration options → **WireGuard peer sensors**

## Container Sensors
Each MikroTik container gets its own device with a switch and a status sensor (RouterOS 7+ with container package).

- **Switch**: start/stop container
- **Sensor**: status (`running` / `stopped` / `pulling` / `building` / `error`)
- **Attributes**: tag, OS, arch, interface, memory usage, CPU usage
- Enable via integration options → **Container sensors**

## Device Mode & Packages Sensors
Two diagnostic sensors on the System device showing router capabilities.

- **Device Mode**: current mode + all feature flags (container, zerotier, ipsec, hotspot, etc.) as attributes
- **Packages**: count of installed packages + version per package (or `false` if not installed)

## Bugfixes

- Fixed duplicate `system_poe_out_consumption` sensor key that could cause entity registration issues
- Fixed disconnect on routers without container support (graceful handling of unsupported API paths)

# Features
## Interfaces
Monitor and control status on each Mikrotik interface, both lan and wlan. Both physical and virtual.

![Interface Info](https://raw.githubusercontent.com/tomaae/homeassistant-mikrotik_router/master/docs/assets/images/ui/interface.png)
![Interface Switch](https://raw.githubusercontent.com/tomaae/homeassistant-mikrotik_router/master/docs/assets/images/ui/interface_switch.png)
![Interface Sensor](https://raw.githubusercontent.com/tomaae/homeassistant-mikrotik_router/master/docs/assets/images/ui/interface_sensor.png)

## NAT
Monitor and control individual NAT rules.

More information about NAT rules can be found on [Mikrotik support page](https://help.mikrotik.com/docs/display/ROS/NAT).

## Mangle
Monitor and control individual Mangle rules.

More information about Mangle rules can be found on [Mikrotik support page](https://help.mikrotik.com/docs/display/ROS/Mangle).

## Simple Queue
Control simple queues.

NOTE: FastTracked packets are not processed by Simple Queues.

## PPP
Control and monitor PPP users.

## Host Tracking
Track availability of all network devices.

## Netwatch Tracking
Track netwatch status.

## Scripts
Execute Mikrotik Router scripts.

## Kid Control
Monitor and control Kid Control.

## Client Traffic

6 sensors per tracked client (LAN TX/RX, WAN TX/RX, upload speed, download speed).

**Without the required backend feature enabled, client traffic sensors will show as "unavailable" instead of 0.**

### Client Traffic for RouterOS v6
Requires **IP Accounting** enabled on the router:
```
/ip accounting set enabled=yes
```

### Client Traffic for RouterOS v7+
IP Accounting is deprecated in RouterOS 7. Use **Kid Control** with device profiles instead:
1. Enable Kid Control (`/ip/kid-control`)
2. Create device profiles and assign devices to them

Without Kid Control device profiles configured, client traffic sensors will show "unavailable".

## Port Traffic

4 sensors per interface: TX bytes, RX bytes, TX total, RX total. Enable via integration options.

## UPS sensor
Monitor your UPS.

## GPS sensors
Monitor your GPS coordinates.

## Update sensor
Update Mikrotik OS and firmware directly from Home Assistant.

# Install integration
This integration is distributed using [HACS](https://hacs.xyz/) as a custom repository.

Add this repository to HACS:
1. HACS → 3 dots menu → **Custom repositories**
2. URL: `https://github.com/Csontikka/ha-mikrotik-router`
3. Category: **Integration**
4. Find and install "Mikrotik Router"

Minimum requirements:
* RouterOS v6.43/v7.1
* Home Assistant 2024.3.0

## Setup integration
1. Create user for homeassistant on your mikrotik router with following permissions:
   * read, write, api, reboot, policy, test, sensitive
2. Setup this integration in Home Assistant via `Configuration -> Integrations -> Add -> Mikrotik Router`.

# Support & Feature Requests

Have an idea for a new feature or found a bug? Don't hesitate to [open an issue](https://github.com/Csontikka/ha-mikrotik-router/issues) — feedback and feature requests are always welcome!

## Reporting a bug

When opening an issue, please attach the **diagnostics file** — it contains the integration state and the last 1000 debug log lines, which makes it much easier to diagnose problems.

**How to download diagnostics:**
1. **Settings → Devices & Services**
2. Find **Mikrotik Router** → click on it
3. Click the **3-dot menu** next to the integration entry
4. Select **Download diagnostics**
5. Attach the downloaded `.json` file to your GitHub issue

> The diagnostics file automatically redacts sensitive data (passwords, IP addresses, MAC addresses) before download.

# Development

## Debug logs in diagnostics

Debug logs are **always captured automatically in the background** (last 1000 entries) and included in the diagnostics download — no configuration needed.

## Showing debug logs in home-assistant.log

If you also want debug messages to appear in the main HA log file, add this to `configuration.yaml`:

```yaml
logger:
  default: info
  logs:
    custom_components.mikrotik_router: debug
```

This is **not required** for diagnostics — only needed if you want to watch logs live via the HA log viewer.


# Credits

Based on [tomaae/homeassistant-mikrotik_router](https://github.com/tomaae/homeassistant-mikrotik_router) by [@tomaae](https://github.com/tomaae), licensed under MIT.
