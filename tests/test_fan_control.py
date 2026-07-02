import sys
import unittest
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fakes import load_plugin_module, make_controller  # noqa: E402


DEFAULT_SETTINGS = {
    "thresholdTemp": 90,
    "thresholdHysteresis": 5,
    "timerInterval": 5,
    "fanControlPin": 23,  # deliberately not the old hardcoded pin (2)
}


def c_to_f(c):
    return (c * 9 / 5) + 32


class FanControlTests(unittest.TestCase):
    def setUp(self):
        self.module = load_plugin_module()
        self.gpio = sys.modules["RPi.GPIO"]
        self.gpio.calls.clear()

    def test_template_configs_include_navbar_and_tab(self):
        ctrl = make_controller(self.module, DEFAULT_SETTINGS)
        configs = ctrl.get_template_configs()
        types_present = {c["type"] for c in configs}
        self.assertEqual(types_present, {"settings", "navbar", "tab"})

    def test_uses_configured_pin_not_hardcoded(self):
        ctrl = make_controller(self.module, DEFAULT_SETTINGS, temp_c=40)  # ~104F, above threshold
        ctrl.update_temp()

        self.assertIn((23, "LOW"), self.gpio.calls)
        self.assertTrue(all(pin == 23 for pin, _ in self.gpio.calls))

    def test_fan_turns_on_above_threshold(self):
        ctrl = make_controller(self.module, DEFAULT_SETTINGS, temp_c=1)  # ~34F, below threshold
        ctrl.update_temp()
        self.assertFalse(ctrl._fanIsOn)

        ctrl._sensor.temp_c = 40  # ~104F, above 90F threshold
        ctrl.update_temp()
        self.assertTrue(ctrl._fanIsOn)
        self.assertIn((23, "LOW"), self.gpio.calls)

    def test_hysteresis_prevents_chatter_near_threshold(self):
        ctrl = make_controller(self.module, DEFAULT_SETTINGS, temp_c=40)  # fan on, ~104F
        ctrl.update_temp()
        self.assertTrue(ctrl._fanIsOn)

        # Threshold is 90F, hysteresis is 5F -> fan should stay on anywhere
        # down to 85F, not switch off the instant it dips below 90F.
        ctrl._sensor.temp_c = (87 - 32) * 5 / 9  # ~87F in C
        self.gpio.calls.clear()
        ctrl.update_temp()
        self.assertTrue(ctrl._fanIsOn, "fan should stay on within the hysteresis band")
        self.assertEqual(self.gpio.calls, [], "no GPIO write should happen while state is unchanged")

        # Below threshold - hysteresis (85F) -> fan should now turn off.
        ctrl._sensor.temp_c = (80 - 32) * 5 / 9  # ~80F in C
        ctrl.update_temp()
        self.assertFalse(ctrl._fanIsOn)
        self.assertIn((23, "HIGH"), self.gpio.calls)

    def test_sensor_failure_does_not_immediately_change_fan_state(self):
        ctrl = make_controller(self.module, DEFAULT_SETTINGS, temp_c=1)  # fan off, cold
        ctrl._sensor.raise_error = True

        ctrl.update_temp()
        self.assertFalse(ctrl._fanIsOn)
        self.assertEqual(ctrl._sensorFailureCount, 1)
        self.assertEqual(self.gpio.calls, [], "single failed read shouldn't drive any pin")

    def test_sensor_failsafe_turns_fan_on_after_repeated_failures(self):
        ctrl = make_controller(self.module, DEFAULT_SETTINGS, temp_c=1)  # fan off, cold
        ctrl._sensor.raise_error = True

        ctrl.update_temp()
        ctrl.update_temp()
        self.assertFalse(ctrl._fanIsOn, "shouldn't fail safe before MAX_SENSOR_FAILURES is reached")

        ctrl.update_temp()  # 3rd consecutive failure
        self.assertTrue(ctrl._fanIsOn, "should fail safe (fan on) after MAX_SENSOR_FAILURES")
        self.assertIn((23, "LOW"), self.gpio.calls)

    def test_sensor_recovery_resumes_normal_control(self):
        ctrl = make_controller(self.module, DEFAULT_SETTINGS, temp_c=1)
        ctrl._sensor.raise_error = True
        for _ in range(3):
            ctrl.update_temp()
        self.assertTrue(ctrl._fanIsOn)

        # Sensor comes back with a cold reading -> fan should turn back off,
        # and the failure counter should reset.
        ctrl._sensor.raise_error = False
        ctrl._sensor.temp_c = 1
        ctrl.update_temp()
        self.assertFalse(ctrl._fanIsOn)
        self.assertEqual(ctrl._sensorFailureCount, 0)

    def test_negative_or_missing_hysteresis_falls_back_to_default(self):
        settings = dict(DEFAULT_SETTINGS)
        settings["thresholdHysteresis"] = -5
        ctrl = make_controller(self.module, settings)
        self.assertEqual(ctrl._tempHysteresis, 5)

    def test_zero_hysteresis_falls_back_to_default(self):
        settings = dict(DEFAULT_SETTINGS)
        settings["thresholdHysteresis"] = 0
        ctrl = make_controller(self.module, settings)
        self.assertEqual(ctrl._tempHysteresis, 5)

    def test_hysteresis_greater_than_threshold_is_clamped(self):
        settings = dict(DEFAULT_SETTINGS)
        settings["thresholdTemp"] = 90
        settings["thresholdHysteresis"] = 200
        ctrl = make_controller(self.module, settings)
        self.assertLess(ctrl._tempHysteresis, ctrl._tempThreshold)
        self.assertEqual(ctrl._tempHysteresis, 89)

    def test_hysteresis_equal_to_threshold_is_clamped(self):
        settings = dict(DEFAULT_SETTINGS)
        settings["thresholdTemp"] = 90
        settings["thresholdHysteresis"] = 90
        ctrl = make_controller(self.module, settings)
        self.assertLess(ctrl._tempHysteresis, ctrl._tempThreshold)

    def test_missing_threshold_falls_back_to_default(self):
        settings = dict(DEFAULT_SETTINGS)
        del settings["thresholdTemp"]
        ctrl = make_controller(self.module, settings)
        self.assertEqual(ctrl._tempThreshold, 90)

    def test_missing_interval_falls_back_to_default(self):
        # Timer interval is a plain text field in the settings UI, so a
        # blank/non-numeric save can leave it unset - same failure mode
        # negative/zero hysteresis already guards against above.
        settings = dict(DEFAULT_SETTINGS)
        del settings["timerInterval"]
        ctrl = make_controller(self.module, settings)
        self.assertEqual(ctrl._interval, 5)

    def test_zero_or_negative_interval_falls_back_to_default(self):
        settings = dict(DEFAULT_SETTINGS)
        settings["timerInterval"] = 0
        ctrl = make_controller(self.module, settings)
        self.assertEqual(ctrl._interval, 5)

    def test_missing_fan_control_pin_falls_back_to_default(self):
        settings = dict(DEFAULT_SETTINGS)
        del settings["fanControlPin"]
        ctrl = make_controller(self.module, settings)
        self.assertEqual(ctrl._fanControlPin, 17)

    def test_update_temp_survives_gpio_write_failure(self):
        # A transient GPIO error (e.g. pin claimed elsewhere) driving the fan
        # pin must not escape update_temp() uncaught - it runs on
        # RepeatedTimer's background thread with nothing above it to catch
        # an exception, which would otherwise silently kill the polling
        # thread and freeze the fan in its last state.
        ctrl = make_controller(self.module, DEFAULT_SETTINGS, temp_c=1)  # fan off, cold

        def _boom(*args, **kwargs):
            raise RuntimeError("pin busy")

        original_output = self.gpio.output
        self.addCleanup(setattr, self.gpio, "output", original_output)
        self.gpio.output = _boom

        ctrl._sensor.temp_c = 40  # above threshold - would normally turn fan on
        ctrl.update_temp()  # must not raise

        self.assertFalse(ctrl._fanIsOn, "fan state shouldn't flip if the GPIO write itself failed")
        self.assertTrue(
            any("Couldn't drive fan pin" in msg for _, msg in ctrl._logger.messages)
        )

    def test_after_update_settings_restarts_timer_when_hardware_ok(self):
        ctrl = make_controller(self.module, DEFAULT_SETTINGS)
        ctrl.on_after_startup()
        old_timer = ctrl._checkTempTimer

        ctrl.after_UpdateSettings()

        self.assertTrue(old_timer.cancelled)
        self.assertIsNotNone(ctrl._checkTempTimer)
        self.assertTrue(ctrl._checkTempTimer.started)

    def test_after_update_settings_does_not_start_timer_when_hardware_unavailable(self):
        # Saving settings (even unrelated ones) after a failed startup used
        # to start the timer unconditionally, which would eventually hit the
        # sensor-failure fail-safe and call GPIO.output() on hardware that
        # was never initialized - crashing the exact way on_after_startup's
        # own guard was designed to prevent.
        ctrl = make_controller(self.module, DEFAULT_SETTINGS)
        ctrl._hardwareOk = False
        ctrl._sensor = None

        ctrl.after_UpdateSettings()

        self.assertIsNone(ctrl._checkTempTimer)

    def test_shutdown_drives_pin_off_before_cleanup(self):
        ctrl = make_controller(self.module, DEFAULT_SETTINGS)
        ctrl.on_shutdown()
        self.assertIn((23, "HIGH"), self.gpio.calls)

    def test_default_unit_is_fahrenheit(self):
        ctrl = make_controller(self.module, DEFAULT_SETTINGS, temp_c=20)
        self.assertEqual(ctrl._tempUnit, "F")
        self.assertAlmostEqual(ctrl.getCurrentTemperature(), c_to_f(20))

    def test_invalid_unit_falls_back_to_fahrenheit(self):
        settings = dict(DEFAULT_SETTINGS)
        settings["tempUnit"] = "K"
        ctrl = make_controller(self.module, settings, temp_c=20)
        self.assertEqual(ctrl._tempUnit, "F")

    def test_celsius_unit_reports_raw_sensor_value(self):
        settings = dict(DEFAULT_SETTINGS)
        settings["tempUnit"] = "C"
        ctrl = make_controller(self.module, settings, temp_c=20)
        self.assertEqual(ctrl.getCurrentTemperature(), 20)

    def test_update_temp_broadcasts_temperature_and_fan_state(self):
        ctrl = make_controller(self.module, DEFAULT_SETTINGS, temp_c=40)  # above threshold
        ctrl.update_temp()

        self.assertEqual(len(ctrl._plugin_manager.messages), 1)
        identifier, data = ctrl._plugin_manager.messages[0]
        self.assertEqual(identifier, "EnclosureFanController")
        self.assertTrue(data["fanIsOn"])
        self.assertFalse(data["sensorError"])
        self.assertEqual(data["tempUnit"], "F")
        self.assertAlmostEqual(data["enclosureTemp"], c_to_f(40))

    def test_update_temp_broadcasts_fan_off_state(self):
        ctrl = make_controller(self.module, DEFAULT_SETTINGS, temp_c=1)  # below threshold
        ctrl.update_temp()

        _, data = ctrl._plugin_manager.messages[0]
        self.assertFalse(data["fanIsOn"])

    def test_failed_read_broadcasts_sensor_error(self):
        ctrl = make_controller(self.module, DEFAULT_SETTINGS, temp_c=1)
        ctrl._sensor.raise_error = True
        ctrl.update_temp()

        _, data = ctrl._plugin_manager.messages[0]
        self.assertTrue(data["sensorError"])
        self.assertIsNone(data["enclosureTemp"])


class HardwareUnavailableTests(unittest.TestCase):
    """Covers the graceful-degradation path added after a real-world
    failure: w1thermsensor raising KernelModuleLoadError at import time
    (1-Wire not enabled) used to take the whole plugin down with it, so it
    silently vanished from OctoPrint's plugin list instead of just having
    fan/temperature control disabled."""

    def setUp(self):
        self.module = load_plugin_module()
        self.gpio = sys.modules["RPi.GPIO"]
        self.gpio.calls.clear()

    def test_on_after_startup_disables_control_when_imports_missing(self):
        # Simulates RPi.GPIO / w1thermsensor failing to import (e.g. 1-Wire
        # not enabled yet) - startup initialization should not raise.
        ctrl = make_controller(self.module, DEFAULT_SETTINGS)
        self.module.GPIO = None
        self.module.W1ThermSensor = None

        ctrl.on_after_startup()

        self.assertFalse(ctrl._hardwareOk)
        self.assertIsNone(ctrl._checkTempTimer, "timer should never be started")
        self.assertTrue(
            any("Hardware unavailable" in msg for _, msg in ctrl._logger.messages),
            "expected a clear error log explaining hardware is unavailable",
        )
        identifier, data = ctrl._plugin_manager.messages[-1]
        self.assertTrue(data["sensorError"])
        self.assertIsNone(data["enclosureTemp"])

        # The failure must also be surfaced to the UI, not just the log -
        # both via the live push and via the server-rendered template data,
        # so a fresh page load shows it too without depending on a
        # websocket message having already arrived.
        self.assertIsNotNone(ctrl._hardwareError)
        self.assertEqual(data["hardwareError"], ctrl._hardwareError)
        self.assertIn("1-Wire", ctrl._hardwareError)
        self.assertEqual(ctrl.get_template_vars()["hardwareError"], ctrl._hardwareError)

    def test_on_after_startup_disables_control_when_hardware_init_fails(self):
        # Imports succeed, but actual init (e.g. GPIO.setup, or no sensor
        # found on the bus) throws - should degrade the same way.
        ctrl = make_controller(self.module, DEFAULT_SETTINGS)

        def _boom(*args, **kwargs):
            raise RuntimeError("no sensor found on bus")

        # The fake RPi.GPIO module lives in sys.modules and is reused across
        # tests, so restore it afterwards - otherwise this monkeypatch leaks
        # into later tests.
        original_setup = self.gpio.setup
        self.addCleanup(setattr, self.gpio, "setup", original_setup)
        self.gpio.setup = _boom

        ctrl.on_after_startup()

        self.assertFalse(ctrl._hardwareOk)
        self.assertIsNone(ctrl._checkTempTimer)
        self.assertTrue(
            any("failed to initialize GPIO/sensor hardware" in msg for _, msg in ctrl._logger.messages)
        )
        self.assertIsNotNone(ctrl._hardwareError)
        identifier, data = ctrl._plugin_manager.messages[-1]
        self.assertEqual(data["hardwareError"], ctrl._hardwareError)

    def test_sensor_read_returns_none_quietly_when_hardware_unavailable(self):
        # self._sensor stays None when hardware initialization never
        # succeeded - reading temperature in that state should just return
        # None, not log a confusing attribute error on every page
        # render/poll.
        ctrl = make_controller(self.module, DEFAULT_SETTINGS)
        ctrl._sensor = None

        result = ctrl.getCurrentTemperature()

        self.assertIsNone(result)
        self.assertFalse(
            any("Couldn't read temperature sensor" in msg for _, msg in ctrl._logger.messages)
        )

    def test_get_template_vars_hardware_error_none_when_healthy(self):
        ctrl = make_controller(self.module, DEFAULT_SETTINGS)
        self.assertIsNone(ctrl.get_template_vars()["hardwareError"])

    def test_shutdown_is_noop_when_hardware_unavailable(self):
        ctrl = make_controller(self.module, DEFAULT_SETTINGS)
        ctrl._hardwareOk = False
        self.gpio.calls.clear()

        ctrl.on_shutdown()  # must not raise, even though GPIO was never set up

        self.assertEqual(self.gpio.calls, [])

    def test_on_after_startup_succeeds_when_hardware_available(self):
        # Sanity check that the normal (hardware-present) path still works.
        ctrl = make_controller(self.module, DEFAULT_SETTINGS)

        ctrl.on_after_startup()

        self.assertTrue(ctrl._hardwareOk)
        self.assertIsNotNone(ctrl._checkTempTimer)


if __name__ == "__main__":
    unittest.main()
