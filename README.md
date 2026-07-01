# OctoPrint-Enclosurefancontroller

An [OctoPrint](https://octoprint.org) plugin that reads a DS18B20 1-Wire temperature
sensor inside your printer enclosure and switches a fan on/off through a GPIO pin
once the enclosure gets too hot.

## How it works

* A background timer polls the sensor every `Timer Interval` minutes (and once at
  startup).
* If the temperature rises above `Threshold Temperature`, the fan is switched on.
* The fan stays on until the temperature drops to `Threshold Temperature -
  Hysteresis`, at which point it switches back off.
* If the sensor can't be read for 3 consecutive polls, the plugin assumes something
  is wrong and fails safe by turning the fan **on** (and logging an error) rather
  than silently doing nothing while the enclosure could be overheating. Normal
  control resumes automatically once a valid reading comes back.
* The current temperature is shown in the OctoPrint navbar and in a dedicated
  "Enclosure" tab.

## Hardware assumptions

* **Sensor**: a single DS18B20 (or compatible) 1-Wire sensor, read via the
  [`w1thermsensor`](https://pypi.org/project/w1thermsensor/) library. Only one
  sensor is supported — if multiple 1-Wire sensors are attached, the plugin will
  read whichever one the library picks first.
* **Fan control**: the plugin drives the configured GPIO pin **active-low** — it
  assumes a relay/MOSFET module where pulling the pin `LOW` turns the fan on and
  `HIGH` turns it off. If your fan hardware is active-high, you'll need to invert
  the pin logic in `EnclosureFanController/__init__.py` (`update_temp` and
  `on_shutdown`).
* **GPIO numbering**: the pin number in settings is a **BCM** GPIO number, not a
  physical header pin number.

### Enabling 1-Wire on the Pi

The DS18B20 needs the kernel's 1-Wire interface enabled before `w1thermsensor` can
see it:

1. `sudo raspi-config` → Interface Options → 1-Wire → Enable, **or** add
   `dtoverlay=w1-gpio` to `/boot/config.txt` (or `/boot/firmware/config.txt` on
   newer Raspberry Pi OS releases) and reboot.
2. Confirm the sensor shows up: `ls /sys/bus/w1/devices/` should list a folder
   starting with `28-`.

## Installation

Installation via the bundled [Plugin Manager](https://docs.octoprint.org/en/master/bundledplugins/pluginmanager.html)
is not yet supported.

Manually install using this URL:

    https://github.com/kngevrything/octo-fan-control/archive/main.zip

This will also install the `RPi.GPIO` and `w1thermsensor` Python packages if they
aren't already present.

## Settings

| Setting | Default | Description |
|---|---|---|
| Threshold Temperature | 90°F | Temperature at which the fan turns on. |
| Hysteresis | 5°F | How far below the threshold the temperature must drop before the fan turns back off. Prevents rapid on/off cycling right at the threshold. |
| Timer Interval | 5 min | How often the sensor is polled. |
| GPIO Pin | 17 (BCM) | The GPIO pin (BCM numbering) wired to your fan relay/MOSFET. |

Changing any setting restarts the polling timer with the new values immediately —
no OctoPrint restart required.

## Troubleshooting

* **Plugin won't load / `ImportError: No module named 'RPi'` or `'w1thermsensor'`**:
  these packages only install on a real Raspberry Pi (or another Linux board with
  GPIO support). They won't install in a dev environment on a regular PC/Mac. Make
  sure you installed the plugin using the same Python environment OctoPrint itself
  runs under.
* **Temperature always shows "N/A"**: the sensor isn't being found. Check that
  1-Wire is enabled (see above) and that `/sys/bus/w1/devices/` shows a `28-...`
  folder. Check `octoprint.log` for "Couldn't read temperature sensor" warnings.
* **Fan turns on and won't turn off / turns on for no clear reason**: check the
  log for "Sensor unreachable ... turning fan ON as a fail-safe" — this means the
  plugin lost contact with the sensor and is deliberately keeping the fan running
  until it recovers.
* **Fan logic seems inverted (on when it should be off)**: your relay hardware is
  likely active-high rather than active-low — see Hardware assumptions above.

## License

AGPLv3
