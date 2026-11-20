# Changelog

Each release lists what changed and which files were updated. Newest first.

Versions use `MAJOR.MINOR.PATCH`: MAJOR for changes that break `config.json` or the API, MINOR for new features, PATCH for fixes. The version is set in `hl_lifx_control.py` (`VERSION`) and shown in Settings.

## 1.1.1 - 2026-11-19

**Files updated:** `index.html`, `hl_lifx_control.py` (version number only), `README.md` (version number only), `CHANGELOG.md`

### Changed
- **IP addresses are now hidden by default.** The "Show light IP addresses on cards" setting starts off on every device and shows IPs only after you turn it on there. A device where you'd already switched it on or off in 1.1.0 keeps that choice. Devices that never touched the setting (which were showing IPs) now hide them until you turn it on.

## 1.1.0 - 2026-11-19

**Files updated:** `index.html`, `hl_lifx_control.py` (version number only), `README.md` (version number only), `CHANGELOG.md`

### Added
- **Show/hide light IP addresses:** new "Show light IP addresses on cards" switch in Settings (under a new Display section). Turning it off removes the IP from every light card for a cleaner look. It's on by default, so nothing changes until you switch it off.
  - It applies instantly, with no Save needed, and is remembered per device (like the theme), so a phone can stay clean while a desktop keeps showing IPs. It is not stored in `config.json`.

## 1.0.1 - 2026-11-19

Repository setup. No change to how the service or page behaves.

**Files updated:** `hl_lifx_control.py` (version number only), `README.md`, `CHANGELOG.md`, `LICENSE` (new), `.gitignore` (new)

### Added
- `LICENSE`: MIT license.
- `.gitignore`: keeps `config.json` (your home coordinates, light IPs, groups, presets and schedules) and `data.json`, Python caches and release zips out of the repository.

### Changed
- README: lists the new files, links to the repository at https://github.com/Pyromancer3D/lifx_personal, and has a License section.
- Version number is now 1.0.1.

## 1.0.0 - 2026-11-19

First numbered release. This is the stable baseline: everything built so far, before versions were tracked.

**Files updated:** `hl_lifx_control.py`, `index.html`, `README.md`, `CHANGELOG.md` (new)

### Added
- **Local control, no cloud:** the service talks to LIFX bulbs over the LAN (UDP 56700) and serves the web page and JSON API itself. Python standard library only (3.8+).
- **Discovery:** broadcast, direct scanning of address ranges (works when broadcasts are blocked), and manually added light IPs. Lights that stop responding show as not responding.
- **Light controls:** power switch, Color/White toggle, color picker, warmth slider (1500-9000 K), brightness slider, fade time setting. Each card shows its current state and IP address.
- **Groups:** create, rename and delete in Settings (delete asks for confirmation and warns when presets or schedules depend on the group). Group On/Off, group brightness, and **Set All** (one color or white setting for the whole group). **Hidden groups** have no card but still work in schedules. The group card's top edge shows the average color of its lights that are on. All on / All off for every light.
- **Presets:** saved per group (color/white, color, brightness, on/off per light). Apply, save over, rename, duplicate, delete, and drag to reorder.
- **Fun effects:** breathing, pulsing, candle flicker and strobe for groups and individual lights. Strobe asks for explicit confirmation first. Breathe, pulse and strobe run on the bulb; candle flicker is driven by the server.
- **Schedules:** run at a set time, sunrise or sunset (with minute offsets), on chosen days. Actions: turn on, turn off, apply a preset, or breathe / pulse / candle flicker / strobe in a chosen color. Run now, enable/disable, and "Times Activated" and "Manual Activations" counters. Schedules run on the server, so they work with no browser open.
- **Page layout:** collapsible Schedules, Groups and Lights sections, and collapsible cards (collapsed by default on phones and touch devices, expanded on desktop). Edit mode with drag-to-reorder for groups, lights and schedules. Automatic light/dark theme with an override in Settings. Light bulb favicon. Red banner at the top of the page for connection problems, shown only after repeated failures.
- **Settings:** groups, network (broadcast address, scan ranges, extra IPs, refresh interval), location for sunrise/sunset, fade time, theme, and the version number.
- **Storage:** settings, groups, presets, schedules and light order live in `config.json` (an older `data.json` is renamed automatically).
- **Docs:** README covering how the service controls the lights, the config format and every API call.
