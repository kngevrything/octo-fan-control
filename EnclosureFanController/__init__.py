# coding=utf-8
from __future__ import absolute_import

import octoprint.plugin
import octoprint.events
import RPi.GPIO as GPIO
from w1thermsensor import W1ThermSensor
from octoprint.util import RepeatedTimer

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
			enclosureTemp = self.getCurrentTemperature() or 0
			)

	def get_template_configs(self):
		return [
			dict(type="settings", custom_bindings=False),
			dict(type="navbar", custom_bindings=True),
			dict(type="tab", custom_bindings=True, name="Enclosure")
			]

	def __init__(self):
		self._checkTempTimer = None
		self._sensor= W1ThermSensor()

		self._fanIsOn = False
		self._sensorFailureCount = 0

	def __del__(self):
		# Clean up timer
		if self._checkTempTimer is not None:
			self._checkTempTimer.cancel()

	def on_shutdown(self):
		# Leave the fan relay in a known-safe (off) state before releasing
		# the GPIO pins - GPIO.cleanup() alone just floats the pin, which
		# can leave the fan in whatever state it was last driven to.
		try:
			GPIO.output(self._fanControlPin, GPIO.HIGH)
		except Exception as ex:
			self._logger.warning("Couldn't reset fan pin on shutdown: %s" % ex)
		finally:
			GPIO.cleanup()

	def on_after_startup(self):
		# Retrieve settings and initialize GPIO and sensor
		self.GetSettingValues()
		fanGpioPin = self._settings.get_int(["fanControlPin"])

		GPIO.setmode(GPIO.BCM)
		GPIO.setup(fanGpioPin, GPIO.OUT)
		GPIO.output(fanGpioPin, GPIO.HIGH)
		self._sensor= W1ThermSensor()

		if self._interval <= 0:
			self._interval = 5
			self._logger.info("Invalid Interval -  Defaulting to 5 min")

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

	def sendStatusUpdate(self, temp, sensorError):
		# Broadcast the current temperature (in the configured display unit)
		# and fan state to the UI via the existing send_plugin_message /
		# onDataUpdaterPluginMessage mechanism.
		self._plugin_manager.send_plugin_message(
			self._identifier,
			dict(
				enclosureTemp = temp,
				tempUnit = getattr(self, "_tempUnit", "F"),
				fanIsOn = self._fanIsOn,
				sensorError = sensorError,
			)
		)

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
				GPIO.output(self._fanControlPin, GPIO.LOW)
				self._fanIsOn = True

			# Otherwise leave the fan in whatever state it was already in -
			# don't act on a reading we don't trust.
			self.sendStatusUpdate(None, sensorError=True)
			return

		self._sensorFailureCount = 0
		self._logger.info("temperature = %f"  % temp)

		if temp > self._tempThreshold and not self._fanIsOn:
			GPIO.output(self._fanControlPin, GPIO.LOW)
			self._fanIsOn = True
		elif temp < (self._tempThreshold - self._tempHysteresis) and self._fanIsOn:
			GPIO.output(self._fanControlPin, GPIO.HIGH)
			self._fanIsOn = False

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
