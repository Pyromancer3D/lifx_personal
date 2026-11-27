# Changelog

Each release lists what changed and which files were updated. Newest first.

Versions use `MAJOR.MINOR.PATCH`: MAJOR for changes that break `config.json` or the API, MINOR for new features, PATCH for fixes. The version is set in `hl_lifx_control.py` (`VERSION`) and shown in Settings.

## 2.1.0 - 2026-11-26

**Files updated:** `hl_lifx_control.py`, `index.html`, `README.md`, `CHANGELOG.md`

### Added
- **Runtimes in the routine editor:** each step shows **This step** (its own length) and **Cumulative** (total runtime through the end of that step), bottom-left beside "Delete step", updating as you edit. Fades left blank use the default from Settings; effects use their cycle count or seconds.
- **Time remaining while running:** the schedule card shows "X min Y sec Remaining", right-aligned on the "Running, step N of M" line, and the edit dialog shows the same countdown at the bottom. Times under a minute read "X sec". The countdown follows the server's clock, so it stays right on a page opened mid-run.
- API: each running schedule's `running` object in `GET /api/state` now includes `ends` (expected finish, epoch seconds).

## 2.0.1 - 2026-11-24

**Files updated:** `index.html`, `hl_lifx_control.py` (version number only), `README.md`, `CHANGELOG.md`

### Fixed
- Dragging group cards on the main page (Edit mode) didn't change the order. Reordering in Settings still worked, and both now work and stay in sync (hidden groups keep their place).
- Dragging presets within a group could scramble the order in the same way; fixed.

### Changed
- README: added a prerequisite note that lights must already be on your network via the LIFX app or another method; this controller does not do initial bulb setup.

## 2.0.0 - 2026-11-24

Major release: the configuration layout changed (existing installs are migrated automatically).

**Files updated:** `hl_lifx_control.py`, `index.html`, `README.md`, `CHANGELOG.md`, `.gitignore`

### Added
- **Routines:** a schedule can now have any number of extra steps. In a schedule's edit dialog, **+ Add step** adds another action that runs "N seconds after the previous step has completed" (a 120 s fade followed by a step 120 s later runs 240 s after the start). One action per step; use two steps with 0 seconds for "at the same time". Deleting an untouched step is immediate; deleting a changed one asks first (default "No"). Any existing schedule becomes a routine by adding a step.
- **Per-schedule and per-step fade time.** Leave blank to use the default fade from Settings.
- **Stop button for running schedules.** While a schedule runs its card reads "Running, step N of M" ("Running" for single-step schedules) and shows **Stop** in place of the next-run note; the edit dialog shows Stop instead of Run now. Stop cancels the remaining steps; a fade in progress finishes on its own. New `POST /api/schedule/<id>/stop`.
- **Hidden presets:** a switch in a preset's edit panel hides it from the Presets list, while schedules and routines can still use it (listed as "(hidden)" in the schedule editor). An eye button, right-aligned on the "+ New preset" row, toggles showing them: ⌣ while hidden presets are concealed, 👁 while shown.
- **Server clock** (HH:MM:SS, as seen by the service) on the Schedules title bar, visible while collapsed.
- **"Use 24-hour time" switch** (Settings > Display, per device, default on) for the clock and all schedule times; off shows 12-hour times with AM/PM.
- **Groups in Settings** are collapsible (collapsed by default) and can be reordered by dragging or with the arrow keys, including hidden groups. Each group is a compact row; click it to edit. The order matches the main page.
- API: `GET /api/state` now includes `server_time`, and each schedule's `running`; `apply` accepts a `transition` (seconds).

### Changed
- **Configuration is split into three files in a `.config/` folder:** `config.json` (location, network, default fade), `devices.json` (light order, groups, presets) and `routines.json` (schedules and routines). On first start an existing 1.x `config.json` is split automatically and kept as `config.json.migrated-v1`. Files are written atomically, and an unreadable file is set aside as `.corrupt-<time>` instead of stopping the service. Add `.config/` to backups; `.gitignore` now ignores it.
- The **Settings** button is under "All on" / "All off" at every screen width, and **All off** is red.
- New schedules default to **06:00** instead of 02:00.
- "Next:" run times are shown in the server's timezone (previously the viewing device's).

### Fixed
- A light that is off now fades *in* when turned on with a fade (its color is set first, then it powers on over the fade) instead of popping on.

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
