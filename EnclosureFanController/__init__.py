# coding=utf-8
from __future__ import absolute_import

import octoprint.plugin
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

	def on_event(self, event, payload):
		if event == octoprint.events.Events.USER_LOGGED_IN:
			self._logger.info("login event caught")

	def GetSettingValues(self):
		self._tempThreshold = self._settings.get_int(["thresholdTemp"])
		self._interval = self._settings.get_int(["timerInterval"])
		self._fanControlPin = self._settings.get_int(["fanControlPin"])

		self._logger.info("threshold = %s" % self._settings.get(["thresholdTemp"]))
		self._logger.info("timer interval = %s" % self._settings.get(["timerInterval"]))
		self._logger.info("fanControlPin = %s" % self._settings.get(["fanControlPin"]))


	def after_UpdateSettings(self):
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
			timerInterval = 5,
			fanControlPin = 2)

	def get_template_vars(self):
		return dict(
			thresholdTemp = self._settings.get(["thresholdTemp"]),
			timerInterval = self._settings.get(["timerInterval"]),
			fanControlPin = self._settings.get(["fanControlPin"]),
			enclosureTemp = self.getCurrentTemperature()
			)

	def get_template_configs(self):
		return [
			dict(type="settings", custom_bindings=False)
			]

	def __init__(self):
		self._checkTempTimer = None
		self._sensor= W1ThermSensor()

		self._fanIsOn = False

	def __del__(self):
		self._checkTempTime.stop()

	def on_shutdown(self):
		GPIO.cleanup()

	def on_after_startup(self):
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
		temp = 0

		try:
			temp = self._sensor.get_temperature()
			temp = (float(temp) * 9 / 5) + 32
			lastReadTemperature = temp

			self._plugin_manager.send_plugin_message(self._identifier, dict(enclosureTemp=temp))

		except:
			temp = 0
			self._logger.info("Couldn't Read Temperature")

		return temp

	def update_temp(self):
		temp = self.getCurrentTemperature()
		self._logger.info("temperature = %f"  % temp)

		if temp > self._tempThreshold and not self._fanIsOn:
			GPIO.output(2,GPIO.LOW)
			self._fanIsOn = True
		elif temp < self._tempThreshold and self._fanIsOn:
			GPIO.output(2, GPIO.HIGH)
			self._fanIsOn = False

	def on_settings_save(self, data):
		octoprint.plugin.SettingsPlugin.on_settings_save(self, data)
		self._logger.info("threshold = %s" % self._settings.get(["thresholdTemp"]))
		self._logger.info("timerInterval = %s" % self._settings.get(["timerInterval"]))
		self._logger.info("fanControlPin = %s" % self._settings.get(["fanControlPin"]))

		self.after_UpdateSettings()

__plugin_pythoncompat__ = ">=3.7,<4"
__plugin_implementation__ = EnclosureFanController()
