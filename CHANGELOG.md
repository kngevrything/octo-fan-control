# Changelog

All notable changes to this project are documented here.
Format loosely follows [Keep a Changelog](https://keepachangelog.com/), and this
project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- **Fan state indicator**: the navbar and "Enclosure" tab now show whether the
  fan is currently on or off, alongside the temperature, pushed over the
  existing `send_plugin_message`/`onDataUpdaterPluginMessage` channel.
- **Celsius/Fahrenheit display unit** setting. The sensor always reads
  Celsius from `w1thermsensor`; this setting controls the unit used for
  display and for interpreting `Threshold Temperature`/`Hysteresis`.
  Defaults to Fahrenheit, matching prior behavior.
- Settings validation: the settings UI now flags (in red, inline) a
  hysteresis that's zero/negative or greater than or equal to the threshold
  temperature.

### Fixed
- Hysteresis of `0` was previously accepted (only negative values fell back
  to the default); `GetSettingValues()` now rejects zero as well.
- `GetSettingValues()` now defensively clamps hysteresis to below the
  threshold temperature server-side, in addition to the new client-side
  warning, so a bad settings.json can't leave the fan permanently on or
  produce a nonsensical off-point.
- A failed sensor read is now signaled to the UI with an explicit
  `sensorError` flag instead of a `0`-degree sentinel value, so a legitimate
  `0°C` (or negative, in Celsius mode) reading is no longer mistaken for a
  sensor failure and displayed as "N/A".

## [0.2.0] - 2026-07-01

First hardening pass over the original plugin scaffold: fixes several bugs that
kept the plugin from working as configured, adds fail-safe behavior around
sensor and threshold handling, cleans up the repo, and adds a test suite + CI.

### Fixed
- Fan control now switches the GPIO pin set in Settings instead of a hardcoded
  BCM pin 2, so changing the "GPIO Pin" setting actually has an effect.
- The temperature display in the navbar and the "Enclosure" tab now actually
  renders. `get_template_configs()` previously only registered the settings
  template, which silently disabled OctoPrint's auto-detection of the navbar
  and tab templates.
- Fixed a JS typo (`enclosurerTemp` -> `enclosureTemp`) that threw an error
  whenever the sensor reported a non-positive temperature.
- `getCurrentTemperature()` now actually updates `self.lastReadTemperature`
  instead of a same-named local variable that was silently discarded.
- Fixed a crash in `__del__` caused by calling `.stop()` on a mistyped/missing
  timer attribute instead of `self._checkTempTimer.cancel()`.
- `on_event` no longer errors on a `USER_LOGGED_IN` event - `octoprint.events`
  is now imported.
- `setup.py` now declares `RPi.GPIO` and `w1thermsensor` as plugin
  requirements, so a normal `pip install` actually pulls them in.

### Added
- **Hysteresis** setting (default 5°F). The fan now stays on until the
  temperature drops to `threshold - hysteresis`, instead of switching off the
  instant it dips below the threshold, preventing rapid on/off cycling.
- **Sensor failure fail-safe**: a failed temperature read is now distinguished
  from a legitimate low reading. After 3 consecutive failed reads, the plugin
  assumes something is wrong with the sensor and turns the fan **on** rather
  than silently doing nothing. Normal control resumes automatically once a
  valid reading comes back.
- Unit test suite (`tests/`) covering the hysteresis band, the fail-safe and
  its recovery, and the configured-pin fix, using lightweight fakes for
  `RPi.GPIO`, `w1thermsensor`, and `octoprint` so tests run without real
  hardware or an OctoPrint install.
- GitHub Actions workflow to run the test suite on push/PR across Python
  3.9-3.13.
- `.gitignore` for build artifacts (`__pycache__/`, `*.egg-info/`, etc.).

### Changed
- Default GPIO pin changed from BCM 2 (which doubles as the I2C1 SDA line on
  most Pi boards) to BCM 17, a general-purpose pin. Only affects fresh
  installs; existing saved settings are unaffected.
- `on_shutdown()` now explicitly drives the fan pin off before releasing the
  GPIO pins, instead of relying on `GPIO.cleanup()` alone (which just floats
  the pin and doesn't guarantee an off state).
- Minimum supported Python bumped from 3.7 to 3.9, matching current OctoPrint
  (2.0 requires 3.9+); 3.7/3.8 are past their own upstream end-of-life.
- README rewritten with an explanation of the control logic, hardware/wiring
  assumptions (active-low relay, 1-Wire sensor setup), a settings reference
  table, and a troubleshooting section.

### Removed
- `translations/`, which contained a stale, out-of-sync full duplicate of the
  entire plugin (source, `setup.py`, `egg-info`, `__pycache__`) rather than
  actual translation files.
- `archive/main.zip`, a checked-in zip snapshot of the repo, redundant with
  git history and the GitHub archive URL already referenced in the README.
- Tracked build artifacts (`__pycache__/*.pyc`, `*.egg-info/`) that should
  never have been committed.
