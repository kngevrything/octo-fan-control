# coding=utf-8
from __future__ import absolute_import

import octoprint.plugin
import octoprint.events
from octoprint.util import RepeatedTimer

# RPi.GPIO and w1thermsensor are both only available (and only importable)
# on real hardware. w1thermsensor in particular runs `modprobe` as a *side
# effect of being imported*, so if the kernel's 1-Wire interface isn't
# enabled yet, the import raises rather than failing later when the sensor
# is actually used. Previously that exception propagated up through
# OctoPrint's plugin loader, which made the whole plugin silently disappear
# from the plugin list instead of just disabling temperature/fan control.
# Import both defensively so a missing or misconfigured 1-Wire setup
# degrades gracefully at startup: hardware features get disabled (with a
# clear log message) instead of the plugin failing to load at all.
_GPIO_IMPORT_ERROR = None
_W1THERMSENSOR_IMPORT_ERROR = None

try:
	import RPi.GPIO as GPIO
except Exception as ex:
	GPIO = None
	_GPIO_IMPORT_ERROR = ex

try:
	from w1thermsensor import W1ThermSensor
except Exception as ex:
	W1ThermSensor = None
	_W1THERMSENSOR_IMPORT_ERROR = ex

class EnclosureFanController(	octoprint.plugin.StartupPlugin,
				octoprint.plugin.SettingsPlugin,
				octoprint.plugin.TemplatePlugin,
				octoprint.plugin.AssetPlugin,
				octoprint.plugin.ShutdownPlugin,
				octoprint.plugin.EventHandlerPlugin):

	lastReadTemperature = 0

	# Number of consecutive failed sensor reads before we stop trusting the
	# last known state and fail safe by turning the fan on.
	MAX_SENSOR_FAILURES = 3

	def on_event(self, event, payload):
		# Handle user login events
		if event == octoprint.events.Events.USER_LOGGED_IN:
			self._logger.info("login event caught")

	def GetSettingValues(self):
		# Retrieve setting values from the OctoPrint configuration page
		self._tempThreshold = self._settings.get_int(["thresholdTemp"])
		self._tempHysteresis = self._settings.get_int(["thresholdHysteresis"])
		self._interval = self._settings.get_int(["timerInterval"])
		self._fanControlPin = self._settings.get_int(["fanControlPin"])
		self._tempUnit = self._settings.get(["tempUnit"])

		if self._tempUnit not in ("C", "F"):
			self._tempUnit = "F"

		if self._tempThreshold is None:
			self._tempThreshold = 90

		# Hysteresis must be a positive number, and smaller than the threshold -
		# otherwise the "off" point (threshold - hysteresis) would be at or below
		# zero degrees of margin, defeating the point of a hysteresis band (or,
		# if hysteresis > threshold, pushing the off point below whatever the
		# fan-on comparison could ever produce).
		if self._tempHysteresis is None or self._tempHysteresis <= 0:
			self._logger.warning(
				"Hysteresis (%s) must be a positive number - defaulting to 5"
				% self._tempHysteresis
			)
			self._tempHysteresis = 5

		if self._tempHysteresis >= self._tempThreshold:
			clamped = max(1, self._tempThreshold - 1)
			self._logger.warning(
				"Hysteresis (%s) must be less than threshold (%s) - clamping to %s"
				% (self._tempHysteresis, self._tempThreshold, clamped)
			)
			self._tempHysteresis = clamped

		# timerInterval/fanControlPin are plain text fields in the settings UI,
		# so get_int() can come back None (blank/non-numeric input) same as the
		# fields above. Unlike threshold/hysteresis this used to go unvalidated
		# here and only got sanity-checked in on_after_startup - so a bad value
		# saved via the settings page (which calls after_UpdateSettings, not
		# on_after_startup) would reach start_timer()/GPIO.setup() as None or
		# <= 0 and blow up. Validate both here so every caller gets it for free.
		if self._interval is None or self._interval <= 0:
			self._logger.warning(
				"Timer interval (%s) must be a positive number - defaulting to 5"
				% self._interval
			)
			self._interval = 5

		if self._fanControlPin is None:
			self._logger.warning(
				"Fan control pin (%s) must be a number - defaulting to 17"
				% self._fanControlPin
			)
			self._fanControlPin = 17

		self._logger.info("threshold = %s" % self._tempThreshold)
		self._logger.info("hysteresis = %s" % self._tempHysteresis)
		self._logger.info("timer interval = %s" % self._settings.get(["timerInterval"]))
		self._logger.info("fanControlPin = %s" % self._settings.get(["fanControlPin"]))
		self._logger.info("tempUnit = %s" % self._tempUnit)


	def after_UpdateSettings(self):
		# Update settings and restart the timer
		self.GetSettingValues()
		if self._checkTempTimer is not None:
			self._checkTempTimer.cancel()

		# Settings can be saved at any time, including while hardware is
		# unavailable (self._hardwareOk == False) - e.g. the user just opens
		# the settings tab and hits Save after a failed startup. Starting the
		# timer in that state would poll update_temp() against a None
		# sensor/GPIO, which eventually hits the sensor-failure fail-safe and
		# calls GPIO.output() on hardware that was never (or couldn't be)
		# initialized - the exact crash this plugin's startup path already
		# guards against.
		if not self._hardwareOk:
			self._logger.info("Hardware unavailable - not restarting timer")
			return

		self.start_timer(self._interval)

	def get_assets(self):
		return dict(
			js=["js/EnclosureFanController.js"],
			css=["css/EnclosureFanController.css"]
			)

	def get_settings_defaults(self):
		return dict(
			thresholdTemp = 90,
			thresholdHysteresis = 5,
			timerInterval = 5,
			# BCM 17 - a general-purpose pin, unlike the previous default of BCM 2
			# which doubles as the I2C1 SDA line on most Pi boards.
			fanControlPin = 17,
			# Display/threshold unit. "F" preserves the plugin's historical
			# behavior (thresholdTemp/thresholdHysteresis in Fahrenheit); the
			# sensor itself always reads Celsius from w1thermsensor regardless
			# of this setting.
			tempUnit = "F")

	def get_template_vars(self):
		return dict(
			thresholdTemp = self._settings.get(["thresholdTemp"]),
			thresholdHysteresis = self._settings.get(["thresholdHysteresis"]),
			timerInterval = self._settings.get(["timerInterval"]),
			fanControlPin = self._settings.get(["fanControlPin"]),
			enclosureTemp = self.getCurrentTemperature() or 0,
			# Rendered directly (not via knockout) so it's correct as soon
			# as the page loads/reloads, without waiting for a websocket
			# push - important since the plugin only re-evaluates hardware
			# availability once, at startup.
			hardwareError = getattr(self, "_hardwareError", None)
			)

	def get_template_configs(self):
		return [
			dict(type="settings", custom_bindings=False),
			dict(type="navbar", custom_bindings=True),
			dict(type="tab", custom_bindings=True, name="Enclosure")
			]

	def __init__(self):
		self._checkTempTimer = None
		self._sensor = None
		# Set True only once hardware initialization has actually
		# succeeded. Everything that touches GPIO/the sensor should check
		# this first rather than assuming it's available.
		self._hardwareOk = False
		# Set to a user-facing, actionable message if hardware
		# initialization fails, so it can be surfaced in the UI and in the
		# log - both on page load and to any tab already open at the time.
		self._hardwareError = None

		self._fanIsOn = False
		self._sensorFailureCount = 0

	def _hardware_import_problems(self):
		# Returns a list of human-readable problems describing which
		# required hardware libraries failed to import, or an empty list
		# if both are available.
		problems = []
		if GPIO is None:
			problems.append("RPi.GPIO could not be imported (%s)" % _GPIO_IMPORT_ERROR)
		if W1ThermSensor is None:
			problems.append("w1thermsensor could not be imported (%s)" % _W1THERMSENSOR_IMPORT_ERROR)
		return problems

	def __del__(self):
		# Clean up timer
		if self._checkTempTimer is not None:
			self._checkTempTimer.cancel()

	def on_shutdown(self):
		# Leave the fan relay in a known-safe (off) state before releasing
		# the GPIO pins - GPIO.cleanup() alone just floats the pin, which
		# can leave the fan in whatever state it was last driven to. Skipped
		# entirely if hardware init never succeeded - nothing to clean up,
		# and GPIO may not even be importable.
		if not self._hardwareOk:
			return

		try:
			GPIO.output(self._fanControlPin, GPIO.HIGH)
		except Exception as ex:
			self._logger.warning("Couldn't reset fan pin on shutdown: %s" % ex)
		finally:
			GPIO.cleanup()

	def on_after_startup(self):
		# Retrieve settings and initialize GPIO and sensor
		self.GetSettingValues()

		# Reset explicitly (rather than relying on the constructor's
		# default) so this stays correct even if startup initialization
		# ever runs more than once.
		self._hardwareOk = False
		self._hardwareError = None

		# RPi.GPIO / w1thermsensor failing to import (most commonly:
		# w1thermsensor's kernel module autoload failing because 1-Wire
		# isn't enabled yet) used to take the whole plugin down with it,
		# making it silently vanish from the plugin list. Check first and
		# degrade gracefully instead: log a clear, actionable error, notify
		# the UI, and leave the plugin loaded (settings/tab still visible)
		# rather than crashing. self._hardwareError is the user-facing
		# version of this - surfaced in the UI both on page load and to any
		# tab already open, not just buried in the log.
		problems = self._hardware_import_problems()
		if problems:
			for problem in problems:
				self._logger.error("EnclosureFanController: %s" % problem)

			self._hardwareError = (
				"Hardware unavailable (%s). This is commonly caused by the "
				"Raspberry Pi's 1-Wire interface not being enabled yet - run "
				"'sudo raspi-config' -> Interface Options -> 1-Wire -> "
				"Enable (or add 'dtoverlay=w1-gpio' to "
				"/boot/firmware/config.txt), reboot the Pi, then restart "
				"OctoPrint. Fan/temperature control is disabled until this "
				"is fixed." % "; ".join(problems)
			)
			self._logger.error("EnclosureFanController: %s" % self._hardwareError)
			self.sendStatusUpdate(None, sensorError=True, hardwareError=self._hardwareError)
			return

		fanGpioPin = self._settings.get_int(["fanControlPin"])

		try:
			GPIO.setmode(GPIO.BCM)
			GPIO.setup(fanGpioPin, GPIO.OUT)
			GPIO.output(fanGpioPin, GPIO.HIGH)
			self._sensor = W1ThermSensor()
		except Exception as ex:
			self._hardwareError = (
				"Hardware unavailable: failed to initialize GPIO/sensor "
				"hardware (%s). Check your wiring and that "
				"/sys/bus/w1/devices/ shows a 28-... folder, then restart "
				"OctoPrint. Fan/temperature control is disabled until this "
				"is fixed." % ex
			)
			self._logger.error("EnclosureFanController: %s" % self._hardwareError)
			self.sendStatusUpdate(None, sensorError=True, hardwareError=self._hardwareError)
			return

		self._hardwareOk = True

		self.update_temp()
		self.start_timer(self._interval)

	def start_timer(self, interval):
		self._checkTempTimer = RepeatedTimer(interval, self.update_temp, run_first=True)
		self._checkTempTimer.start()

	def getCurrentTemperature(self):
		# Retrieve the current temperature from the sensor, converted to
		# whichever unit is configured for display/thresholds (self._tempUnit).
		# The sensor itself always reads Celsius; w1thermsensor never returns
		# Fahrenheit directly. Returns None on a failed read so callers can
		# tell "sensor error" apart from a legitimate low (or sub-zero, in
		# Celsius mode) reading, instead of silently treating both as 0.
		if self._sensor is None:
			# Hardware unavailable - nothing to read. Don't log here; the
			# startup error already explains why, and logging a confusing
			# attribute error on every page render/poll would just be noise.
			return None

		try:
			tempCelsius = float(self._sensor.get_temperature())
			temp = self.convertTemperature(tempCelsius)
			self.lastReadTemperature = temp
			return temp

		except Exception as ex:
			self._logger.warning("Couldn't read temperature sensor: %s" % ex)
			return None

	def convertTemperature(self, tempCelsius):
		# Convert a raw Celsius sensor reading into the configured display
		# unit. Defaults to Fahrenheit (the plugin's historical behavior) for
		# any unrecognized/unset unit.
		if getattr(self, "_tempUnit", "F") == "C":
			return tempCelsius
		return (tempCelsius * 9 / 5) + 32

	def sendStatusUpdate(self, temp, sensorError, hardwareError=None):
		# Broadcast the current temperature (in the configured display unit)
		# and fan state to the UI over the plugin's existing push-message
		# channel. hardwareError is only set (non-None) when hardware
		# initialization failed at startup, as opposed to sensorError, which
		# just means this particular poll's read failed.
		self._plugin_manager.send_plugin_message(
			self._identifier,
			dict(
				enclosureTemp = temp,
				tempUnit = getattr(self, "_tempUnit", "F"),
				fanIsOn = self._fanIsOn,
				sensorError = sensorError,
				hardwareError = hardwareError,
			)
		)

	def _setFan(self, on):
		# Drive the fan relay pin, catching GPIO failures instead of letting
		# them escape update_temp() uncaught. update_temp() runs on
		# RepeatedTimer's background thread with nothing above it to catch an
		# exception - one would otherwise silently kill the polling thread,
		# freezing the fan in its last state with no further temperature
		# updates and no error surfaced to the UI. Only updates self._fanIsOn
		# on success, since a failed write means the physical fan state
		# didn't actually change.
		try:
			GPIO.output(self._fanControlPin, GPIO.LOW if on else GPIO.HIGH)
			self._fanIsOn = on
		except Exception as ex:
			self._logger.warning("Couldn't drive fan pin: %s" % ex)

	def update_temp(self):
		# Update the temperature and control the fan accordingly, using a
		# hysteresis band so the fan doesn't chatter on/off right at the
		# threshold, and failing safe if the sensor stops responding.
		temp = self.getCurrentTemperature()

		if temp is None:
			self._sensorFailureCount += 1
			self._logger.warning("Sensor read failed (%d consecutive failures)" % self._sensorFailureCount)

			if self._sensorFailureCount >= self.MAX_SENSOR_FAILURES and not self._fanIsOn:
				self._logger.error(
					"Sensor unreachable after %d attempts - turning fan ON as a fail-safe"
					% self._sensorFailureCount
				)
				self._setFan(True)

			# Otherwise leave the fan in whatever state it was already in -
			# don't act on a reading we don't trust.
			self.sendStatusUpdate(None, sensorError=True)
			return

		self._sensorFailureCount = 0
		self._logger.info("temperature = %f"  % temp)

		if temp > self._tempThreshold and not self._fanIsOn:
			self._setFan(True)
		elif temp < (self._tempThreshold - self._tempHysteresis) and self._fanIsOn:
			self._setFan(False)

		self.sendStatusUpdate(temp, sensorError=False)

	def on_settings_save(self, data):
		octoprint.plugin.SettingsPlugin.on_settings_save(self, data)
		self._logger.info("threshold = %s" % self._settings.get(["thresholdTemp"]))
		self._logger.info("hysteresis = %s" % self._settings.get(["thresholdHysteresis"]))
		self._logger.info("timerInterval = %s" % self._settings.get(["timerInterval"]))
		self._logger.info("fanControlPin = %s" % self._settings.get(["fanControlPin"]))

		self.after_UpdateSettings()

__plugin_pythoncompat__ = ">=3.9,<4"
__plugin_implementation__ = EnclosureFanController()
