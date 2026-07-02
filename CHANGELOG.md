# Changelog

All notable changes to this project are documented here.
Format loosely follows [Keep a Changelog](https://keepachangelog.com/), and this
project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Fixed
- **Hardware-unavailable banner (added in 0.3.0) never actually rendered**:
  the banner's Jinja templates referenced the value returned from
  `get_template_vars()` as a bare `{{ hardwareError }}`, but OctoPrint
  injects `get_template_vars()` keys into the template context prefixed
  with `plugin_<identifier>_` - so the real variable name is
  `plugin_EnclosureFanController_hardwareError`. The bare name was simply
  undefined, which Jinja treats as falsy with no error, so the
  `{% if %}` block silently never rendered - loading, settings, and the
  rest of the UI all worked fine, only the new banner was invisible.
  Templates now reference the correctly-prefixed variable name.

## [0.3.0] - 2026-07-02

UI/UX polish pass, plus a real-world reliability find: the plugin could
silently vanish from OctoPrint's plugin list entirely if the 1-Wire interface
wasn't enabled yet.

### Added
- **Hardware-unavailable banner**: if `RPi.GPIO`/`w1thermsensor` fail to
  import or initialize (see "Plugin could silently disappear..." below), a
  red "Hardware unavailable" alert with the specific error and fix now
  appears on the Settings page and the "Enclosure" tab, and the navbar entry
  switches to a short "hardware unavailable" notice - previously this was
  only visible in `octoprint.log`, which most users never check. Rendered
  server-side (`get_template_vars()`) so it's correct immediately on page
  load/reload after a restart, and also pushed live for any tab that was
  already open at the moment of the failure.
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
- **Plugin could silently disappear from the plugin list**: `RPi.GPIO` and
  `w1thermsensor` were imported at module level, and `w1thermsensor` runs
  `modprobe` as a side effect of import - if the kernel's 1-Wire interface
  wasn't enabled yet, the import raised `KernelModuleLoadError`, which
  OctoPrint's plugin loader caught by simply not loading the plugin at all
  (no entry in the plugin list, easy to miss in `octoprint.log`). Both
  imports are now wrapped defensively, and hardware init (GPIO setup, sensor
  construction) happens in `on_after_startup()` inside its own try/except.
  If hardware is unavailable for any reason, the plugin now logs a clear,
  actionable error, disables fan/temperature control, and stays loaded with
  its settings/tabs visible, instead of vanishing.
- `getCurrentTemperature()` no longer logs a confusing `'NoneType' object
  has no attribute 'get_temperature'` warning on every page render/poll
  once hardware is known to be unavailable - it now short-circuits and
  returns `None` quietly, since the startup log/UI banner already explains
  why.
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
