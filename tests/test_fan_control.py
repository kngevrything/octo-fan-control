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

    def test_shutdown_drives_pin_off_before_cleanup(self):
        ctrl = make_controller(self.module, DEFAULT_SETTINGS)
        ctrl.on_shutdown()
        self.assertIn((23, "HIGH"), self.gpio.calls)


if __name__ == "__main__":
    unittest.main()
