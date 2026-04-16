# MikroTik Extended — Quality Scale Checklist (verified)

> Rule-by-rule audit against the actual codebase, run on commit `2b4b14b` (v0.4.5).
> Reference: `C:\devuser2\homeassistant_dev_mikrotik\docs\HA_QUALITY_SCALE_CHECKLIST.md`
> Canonical per-rule state file: `custom_components/mikrotik_extended/quality_scale.yaml` (currently out of sync with reality — see notes below).

## Headline

- **Bronze:** 17 pass + 1 exempt, **1 FAIL** (`config-flow-test-coverage` — 84% not 100%)
- **Silver:** 9 pass, **1 FAIL** (`test-coverage` — 36.5% overall, not >95%)
- **Gold:** 14 pass, **5 FAIL** (`discovery`, `discovery-update-info`, `docs-data-update`, `docs-known-limitations`, `docs-use-cases`)
- **Platinum:** 1 exempt, **2 FAIL** (`async-dependency`, `strict-typing`)

Realistic current tier: **Bronze – 1**. To declare any tier in `manifest.json`, we must close the FAIL items below that tier first.

---

## Bronze — 18 rules

| Rule | Status | Evidence |
|---|---|---|
| `action-setup` | ✅ PASS | `hass.services.async_register` at `__init__.py:99, 151, 172, 223` all inside `async def async_setup`, not `async_setup_entry`. |
| `appropriate-polling` | ✅ PASS | `coordinator.py:161` `update_interval=timedelta(seconds=10)`, `:260` `update_interval=self.option_scan_interval` (user-tunable). |
| `brands` | ✅ PASS | Local `icon.png`, `logo.png`, `brand/` dir in integration folder — valid under HA 2026.3+ policy. `quality_scale.yaml` still says `todo` — **needs flip**. |
| `common-modules` | ✅ PASS | `coordinator.py` + `entity.py` exist; platforms import from them. |
| `config-flow-test-coverage` | ❌ **FAIL** | Measured **84%** on `config_flow.py`. Missing: lines 85, 87, 175, 373, 406–414, 441–470, 565–566 (reauth edge, reconfigure branch, custom sensor select). Needs 100%. |
| `config-flow` | ✅ PASS | `manifest.json:"config_flow": true`; `config_flow.py` implements `async_step_user` (line 312). |
| `dependency-transparency` | ✅ PASS | `librouteros`, `mac-vendor-lookup` — both on PyPI with visible source. |
| `docs-actions` | ✅ PASS | README section **Actions (Services)** at line 123. |
| `docs-high-level-description` | ✅ PASS | README line 15: clear one-paragraph description. |
| `docs-installation-instructions` | ✅ PASS | **Installation** (325) + **Requirements** (334). |
| `docs-removal-instructions` | ✅ PASS | **Removal** section at line 405. |
| `entity-event-setup` | ⚪ EXEMPT | No `async_added_to_hass` subscriptions anywhere. `quality_scale.yaml` exempt comment accurate. |
| `entity-unique-id` | ⚠️ SOFT PASS | `entity.py:248` composes from `entry_id + key + slugified reference`. Survives restart/rename, but not delete/re-add. HA accepts this pattern; cleaner approach would use router serial/MAC. |
| `has-entity-name` | ✅ PASS | `entity.py:185` `_attr_has_entity_name = True`. |
| `runtime-data` | ✅ PASS | `__init__.py:269` `config_entry.runtime_data = MikrotikData(...)`. No `hass.data[DOMAIN][entry_id]` writes. |
| `test-before-configure` | ✅ PASS | `config_flow.py:330` calls `api.connect()` and maps failure to `errors[CONF_HOST]` before creating entry. |
| `test-before-setup` | ✅ PASS | `__init__.py:261–262` raises `ConfigEntryAuthFailed` / `ConfigEntryNotReady`. |
| `unique-config-entry` | ✅ PASS | `config_flow.py:335–336` `async_set_unique_id(host) + _abort_if_unique_id_configured()`. |

## Silver — 10 rules

| Rule | Status | Evidence |
|---|---|---|
| `action-exceptions` | ✅ PASS | `ServiceValidationError` raised in services (`__init__.py:81, 187`). |
| `config-entry-unloading` | ✅ PASS | `__init__.py:292` `async def async_unload_entry` with platform unload + API close. |
| `docs-configuration-parameters` | ✅ PASS | README **Configuration Parameters** at line 375. |
| `docs-installation-parameters` | ✅ PASS | README **Installation Parameters** at line 362. |
| `entity-unavailable` | ✅ PASS | Base `MikrotikEntity(CoordinatorEntity)` handles availability; `sensor.py:137` overrides for kid-control. |
| `integration-owner` | ✅ PASS | `manifest.json` codeowners: `@Csontikka`. |
| `log-when-unavailable` | ✅ PASS | Coordinator raises `UpdateFailed` (coordinator.py:671, 800) → HA dedup warnings. |
| `parallel-updates` | ✅ PASS | `PARALLEL_UPDATES = 0` in all 6 platforms (sensor, binary_sensor, switch, button, device_tracker, update). |
| `reauthentication-flow` | ✅ PASS | `async_step_reauth` + `async_step_reauth_confirm` (config_flow.py:177, 181); `ConfigEntryAuthFailed` raised. |
| `test-coverage` | ❌ **FAIL** | Measured **36.52%** overall. 0% on sensor/switch/binary_sensor/button/device_tracker/diagnostics; 44% on entity, 38% on coordinator, 53% on mikrotikapi. Needs >95%. |

## Gold — 21 rules

| Rule | Status | Evidence |
|---|---|---|
| `devices` | ✅ PASS | `DeviceInfo` used (grep: 6 hits in entity.py, update.py). |
| `diagnostics` | ✅ PASS | `diagnostics.py` exports config-entry diagnostics using `runtime_data`. |
| `discovery-update-info` | ❌ **FAIL** | No HA-native discovery protocol → N/A rather than pass. Should be **exempt** in yaml if we don't plan to add zeroconf. |
| `discovery` | ❌ **FAIL** | `manifest.json` has NO `zeroconf`/`ssdp`/`dhcp`. MNDP scan in `mndp.py` is user-triggered, not HA discovery. Add zeroconf or mark **exempt**. |
| `docs-data-update` | ❌ **FAIL** | No README section explaining poll cadence / how data is updated. |
| `docs-examples` | ✅ PASS | README **Automation Examples** at line 223 with YAML blocks. |
| `docs-known-limitations` | ❌ **FAIL** | No **Known Limitations** section. (Feature Availability ≠ limitations.) |
| `docs-supported-devices` | ✅ PASS | **Feature Availability** table (line 285) + hardware tested block (line 323: hAP ax³, CHR). |
| `docs-supported-functions` | ✅ PASS | **Features** section (line 17) enumerates every entity/service. |
| `docs-troubleshooting` | ✅ PASS | **Troubleshooting** + **Diagnostics Export** + **Debug Logs** (lines 459–480). |
| `docs-use-cases` | ❌ **FAIL** | Intro paragraph hints at use, but no dedicated **Use Cases** section. |
| `dynamic-devices` | ✅ PASS | `entity.py:140–166` adds new entities + removes orphans/empty devices on every update. |
| `entity-category` | ✅ PASS | `_attr_entity_category` references found in entity.py + update.py. |
| `entity-device-class` | ✅ PASS | `_attr_device_class` referenced. |
| `entity-disabled-by-default` | ✅ PASS | `entity.py:257 entity_registry_enabled_default` property keyed off option. |
| `entity-translations` | ✅ PASS | `translation_key` on all entity types (50+ hits in sensor/switch/binary_sensor types). |
| `exception-translations` | ✅ PASS | `ServiceValidationError(translation_domain=DOMAIN, translation_key=...)` in `__init__.py:81, 187`. |
| `icon-translations` | ✅ PASS | `icons.json` present with per-entity defaults. |
| `reconfiguration-flow` | ✅ PASS | `async_step_reconfigure` at config_flow.py:439. |
| `repair-issues` | ✅ PASS | `async_create_issue` for `wrong_credentials`, `ssl_error`, `insufficient_permissions` in coordinator.py. |
| `stale-devices` | ✅ PASS | `device_registry.async_remove_device` at entity.py:165 for empty devices. |

## Platinum — 3 rules

| Rule | Status | Evidence |
|---|---|---|
| `async-dependency` | ❌ **FAIL** | `librouteros` is sync; called via `hass.async_add_executor_job`. Would require async library or upstream fork. |
| `inject-websession` | ⚪ EXEMPT | Integration uses RouterOS API (TCP socket via librouteros), not HTTP/aiohttp. |
| `strict-typing` | ❌ **FAIL** | No `mypy --strict` config; annotations incomplete. |

---

## `quality_scale.yaml` items that are out of sync with reality

| Rule | yaml says | reality |
|---|---|---|
| `brands` | `todo` | **done** (local assets valid under HA 2026.3+) |
| `config-flow-test-coverage` | `done` | **todo** (84%, not 100%) |
| `test-coverage` | `done` | **todo** (36.5%, not >95%) |
| `discovery` | `done` | **todo / exempt** (no HA discovery declared) |
| `discovery-update-info` | `done` | **exempt** (no HA discovery) |
| `docs-data-update` | `todo` | todo (confirmed) |
| `docs-examples` | `todo` | **done** (already present) |
| `docs-known-limitations` | `todo` | todo (confirmed) |
| `docs-supported-devices` | `todo` | **done** (Feature Availability table) |
| `docs-supported-functions` | `todo` | **done** (Features section) |
| `docs-troubleshooting` | `todo` | **done** (already present) |
| `docs-use-cases` | `todo` | todo (confirmed) |

---

## Suggested order of attack

1. **Sync `quality_scale.yaml` to reality** — flip the 7 mismatched rules above. Low effort, high hygiene.
2. **README patch** — add 3 missing sections (`docs-data-update`, `docs-known-limitations`, `docs-use-cases`). ~30 min.
3. **Discovery decision** — either add zeroconf/dhcp declaration to `manifest.json` + a `async_step_zeroconf` handler, or mark `discovery` + `discovery-update-info` as **exempt** with a comment ("local MikroTik API, no standard HA discovery applies"). 15 min if exempt.
4. **Config-flow coverage to 100%** — add tests for reauth_confirm edge, reconfigure branch, custom sensor_select. ~1–2 hr.
5. **Overall test-coverage to >95%** — biggest item. Needs tests for sensor/switch/binary_sensor/button/device_tracker platforms (all at 0%), plus fill coordinator gaps. **Multi-day effort.**
6. **Strict-typing** — add mypy config, fix annotations. Medium.
7. **async-dependency** — requires an async RouterOS client; not trivial.

After step 1–3 we can declare `"quality_scale": "silver"` once step 4+5 land. Gold = after steps 1–5 + discovery decision.
