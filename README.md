# Mikrotik Router — Home Assistant Integration

![Mikrotik Router](https://raw.githubusercontent.com/Csontikka/ha-mikrotik-router/master/images/banner.png)

![GitHub release (latest by date)](https://img.shields.io/github/v/release/Csontikka/ha-mikrotik-router?style=plastic)
[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=plastic)](https://github.com/hacs/integration)
[![Security Rating](https://sonarcloud.io/api/project_badges/measure?project=Csontikka_ha-mikrotik-router&metric=security_rating)](https://sonarcloud.io/summary/new_code?id=Csontikka_ha-mikrotik-router)
[![Reliability Rating](https://sonarcloud.io/api/project_badges/measure?project=Csontikka_ha-mikrotik-router&metric=reliability_rating)](https://sonarcloud.io/summary/new_code?id=Csontikka_ha-mikrotik-router)
[![Maintainability Rating](https://sonarcloud.io/api/project_badges/measure?project=Csontikka_ha-mikrotik-router&metric=sqale_rating)](https://sonarcloud.io/summary/new_code?id=Csontikka_ha-mikrotik-router)
[![Buy Me a Coffee](https://img.shields.io/badge/Buy%20me%20a%20coffee-donate-yellow.svg?style=plastic)](https://buymeacoffee.com/Csontikka)

Full-featured Home Assistant integration for MikroTik routers running **RouterOS 7+**. Monitor system resources, control firewall rules, track network devices, manage WireGuard peers, containers, and more — all from your HA dashboard. Supports multiple routers simultaneously.

## Features

### System Monitoring

CPU load, memory/HDD usage, uptime, temperatures (CPU, board, PHY, switch), voltage, power consumption, PSU metrics (current/voltage for PSU1/PSU2), fan speeds (fan1-fan4), UPS status, GPS coordinates. Each router also gets a reboot button entity.

![System Monitoring](docs/assets/images/screenshots/system_cpu_temp.png)

### Network Interfaces

Per-interface monitoring: link status (binary sensor), enable/disable (switch), TX/RX traffic rates and totals (optional), IP address sensor per interface, SFP status and information, PoE status/control/consumption, connected device MAC/IP info per interface.

![Interface Traffic](docs/assets/images/screenshots/interface_tx.png)

![Interface RX Graph](docs/assets/images/screenshots/interface_rx_graph.png)

### Firewall & Routing Rules

Monitor and control individual rules — each gets a switch entity:

- NAT rules
- Mangle rules
- Filter rules
- Routing rules

More information: [MikroTik Firewall documentation](https://help.mikrotik.com/docs/display/ROS/Firewall)

![Firewall Filter Switch](docs/assets/images/screenshots/firewall_filter.png)

Detailed rule information available per entity (chain, action, protocol, addresses, ports, connection state):

![Firewall Filter Details](docs/assets/images/screenshots/firewall_filter_attributes.png)

### Device Tracking

ARP-based network host presence tracking. Configurable timeout (default 180s). Shows MAC address, IP, and connected interface as attributes.

![Device Tracker](docs/assets/images/screenshots/device_tracker.png)

### WireGuard (RouterOS 7+)

Each WireGuard peer gets its own device with:

- **Switch**: enable/disable peer
- **Binary sensor**: connected status (based on last handshake < 3 minutes)
- **Sensors**: RX bytes, TX bytes, last handshake

Peer display name: `name` field, then `comment`, then first 8 chars of public key.

Enable via integration options -> WireGuard peer sensors.

![WireGuard Peer](docs/assets/images/screenshots/wireguard_connected.png)

### Containers (RouterOS 7+)

Each container gets its own device with:

- **Switch**: start/stop container
- **Sensor**: status (running/stopped/pulling/building/error)
- **Attributes**: tag, OS, arch, interface, memory/CPU usage

Enable via integration options -> Container sensors.

![Container Status](docs/assets/images/screenshots/container_status.png)

![Container Attributes](docs/assets/images/screenshots/container_attributes.png)

### Client Traffic

Per-device bandwidth monitoring. 2 sensors per tracked device (total TX/RX).

Uses Kid Control backend. The integration auto-creates an `ha-monitoring` profile (unrestricted) on the router when enabled. If the API user lacks write permission, a warning is logged with the manual command:

```
/ip/kid-control/add name=ha-monitoring mon=0s-1d tue=0s-1d wed=0s-1d thu=0s-1d fri=0s-1d sat=0s-1d sun=0s-1d
```

Without the required backend, sensors show "unavailable" instead of 0.

<!-- Client traffic screenshot placeholder — enable sensor_client_traffic to capture -->

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

![Packages Details](docs/assets/images/screenshots/packages_attributes.png)

### Firmware Updates

Update RouterOS and RouterBoard firmware directly from Home Assistant.

- **RouterOS update** — with changelog and optional automatic backup before install
- **RouterBoard firmware update** — upgrades board firmware and reboots

![RouterOS Update](docs/assets/images/screenshots/update_routeros.png)

### Actions (Services)

- **Wake-on-LAN** (`mikrotik_router.send_magic_packet`): send a WoL magic packet through the router to wake up a network device.

  **Parameters:** `mac` (required), `interface` (required — the router interface to send the packet from, e.g. `bridge`).

  ```yaml
  action: mikrotik_router.send_magic_packet
  data:
    mac: "AA:BB:CC:DD:EE:FF"
    interface: "bridge"
  ```

  **Example — automation:**

  ```yaml
  automation:
    - alias: "Wake up server when I get home"
      trigger:
        - platform: zone
          entity_id: person.me
          zone: zone.home
          event: enter
      action:
        - action: mikrotik_router.send_magic_packet
          data:
            mac: "AA:BB:CC:DD:EE:FF"
            interface: "bridge"
  ```

- **API Test** (`mikrotik_router.api_test`): diagnostic action for raw RouterOS API queries or coordinator data inspection. Use in **Developer Tools -> Actions** with "Return response" enabled.

  **Parameters:** `path` (required), `limit` (optional, default 10), `host` (optional), `coordinator_data`* (optional).

  ```yaml
  # Query router interfaces
  action: mikrotik_router.api_test
  data:
    path: "/interface"
    limit: 20
  ```

  ```yaml
  # Inspect coordinator's processed data
  action: mikrotik_router.api_test
  data:
    path: "interface"
    coordinator_data: true
  ```

  > **\*coordinator_data:** When set to `true`, the `path` parameter is treated as a coordinator data key (e.g. `interface`, `dhcp`, `arp`) instead of a RouterOS API path. This returns the integration's internally cached and processed data from the last update cycle — useful for debugging what the integration currently "sees" without making an additional API call to the router.

- **Refresh Data** (`mikrotik_router.refresh_data`): force an immediate data refresh from the router, including all sensors, environment variables, and device trackers. Useful in automations when you need up-to-date values without waiting for the next poll cycle.

  **Parameters:** `host` (optional — only refresh a specific router).

  ```yaml
  action: mikrotik_router.refresh_data
  ```

  **Example — refresh after changing a firewall rule:**

  ```yaml
  automation:
    - alias: "Refresh after guest network toggle"
      trigger:
        - platform: state
          entity_id: input_boolean.guest_network
      action:
        - action: mikrotik_router.set_environment
          data:
            name: "guestEnabled"
            value: "{{ states('input_boolean.guest_network') }}"
        - delay: 3
        - action: mikrotik_router.refresh_data
  ```

- **Set Environment Variable** (`mikrotik_router.set_environment`): create, update, or remove a RouterOS script environment variable. Environment variables are accessible from RouterOS scripts via `:global` and can be used to pass values between Home Assistant and router-side scripts.

  **Parameters:** `name` (required), `value` (required for set/add), `action` (optional: `set`, `add`, or `remove` — default `set`), `host` (optional).

  ```yaml
  # Create or update a variable
  action: mikrotik_router.set_environment
  data:
    name: "myVar"
    value: "hello"
    action: "set"
  ```

  ```yaml
  # Remove a variable
  action: mikrotik_router.set_environment
  data:
    name: "myVar"
    action: "remove"
  ```

  > **Note:** Creating a new variable takes ~2 seconds (uses a one-shot RouterOS scheduler internally). Updating an existing variable is instant. The variable is accessible from RouterOS scripts via `:global myVar; :put $myVar`.

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
| Refresh Data service | ✓ | ✓ | No |
| Set Environment service | ✓ | ? | No |
| Reboot button | ✓ | ✓ | No |
| Multi-router support | ✓ | ✓ | No |

> **\*RouterOS 6 is not officially supported.** Basic features may still work, but v6 is not tested or maintained. Upgrade to RouterOS 7 is strongly recommended.
>
> Active development and testing is done on a **MikroTik hAP ax³** running the latest stable RouterOS 7 and a **Cloud Hosted Router (CHR)** virtual instance.

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
3. Choose whether to **scan the network** for MikroTik routers automatically:
   - **Scan** — the integration scans the local /24 subnet, checks the ARP table for MikroTik devices (by MAC OUI), and listens for MNDP broadcast announcements. Found routers are listed sorted by IP address — select one or choose *Enter manually*. If nothing is found, the manual entry form opens with an info message.
   - **Skip** — go directly to manual entry
   > **Tip:** Router names appear in the list if SNMP or MNDP is enabled on the router. For SNMP, enable it with community string `public` (`/snmp set enabled=yes`). For MNDP, ensure neighbor discovery is active on the interface facing HA (`/ip neighbor discovery-settings set discover-interface-list=all`).
4. Fill in the connection details (see parameters below)
5. Choose a sensor preset and finish setup

### Installation Parameters

These fields are shown during the initial setup wizard:

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| Name | Yes | `Mikrotik` | Display name for this integration instance |
| Host | Yes | `192.168.88.1` | IP address or hostname of the MikroTik router |
| Username | Yes | `admin` | RouterOS API username |
| Password | Yes | — | RouterOS API password |
| Port | No | `0` | API port (`0` = auto-detect: 8728 plain, 8729 SSL) |
| SSL Mode | No | `none` | `none` — plain (port 8728); `ssl` — encrypted, self-signed OK (port 8729); `ssl_verify` — encrypted, CA-signed cert required |

### Configuration Parameters

These options can be changed after setup via **Settings -> Devices & Services -> Mikrotik Router -> Configure**. Changes take effect immediately — no HA restart needed.

| Parameter | Default | Description |
|-----------|---------|-------------|
| Scan interval | `30` s | How often the router is polled (minimum 10 s). Lower values increase load on the router. |
| Host tracking timeout | `180` s | Seconds after the last ARP/DHCP/wireless activity before a network device is marked as away. |
| Zone | `home` | HA zone used for device tracker `home`/`not_home` state. |
| Sensor preset | recommended | Quick preset selector — see below. |
| Sensor toggles | see presets | Per-category switches for NAT, mangle, filter, scripts, WireGuard, containers, etc. |

> **Note:** The **Configure** button opens the options flow (scan interval, presets, sensor toggles). The **Reconfigure** option (three-dot menu) is for changing connection settings only (host, port, credentials, SSL).

### Sensor Presets

Available during initial setup and via the **Configure** button at any time:

| Preset | Enabled sensors |
|--------|----------------|
| **Minimal** | Port tracker only |
| **Recommended** | Port tracker, NAT, mangle, filter, scripts, netwatch |
| **Full** | Everything — port traffic, client traffic, queues, routing rules, WireGuard, PPP, Kid Control, containers, environment, host tracking |
| **Custom** | Manually select each sensor category |

Switching presets takes effect after saving:
- Enabling a category **creates and enables** the corresponding entities automatically.
- Disabling a category **removes** the entities and their devices from Home Assistant.
- Entities without a corresponding option (fan speed, PSU sensors, GPS, etc.) remain disabled by default and must be enabled manually.

## Removal

1. **Settings -> Devices & Services**
2. Find **Mikrotik Router** -> click the three-dot menu -> **Delete**
3. Confirm removal

When removed, the integration automatically cleans up the `ha-monitoring` Kid Control profile from the router (if it was created for Client Traffic monitoring). No manual cleanup needed on the router side.

If the integration cannot connect to the router during removal, the cleanup is skipped — in that case you can remove the profile manually:

```
/ip/kid-control/remove [find name=ha-monitoring]
```

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

If you find this integration useful, consider [buying me a coffee](https://buymeacoffee.com/Csontikka).

