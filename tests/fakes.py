"""
Lightweight stand-ins for the modules EnclosureFanController depends on
(RPi.GPIO, w1thermsensor, octoprint) so the plugin's control logic can be
unit tested off a real Raspberry Pi / OctoPrint install, without needing
those packages available.

These are intentionally minimal - just enough surface area for
EnclosureFanController/__init__.py to import and run.
"""

import importlib.util
import os
import sys
import types


def install_fake_modules():
    """Register fake RPi.GPIO / w1thermsensor / octoprint modules in
    sys.modules if they aren't already real, importable packages. Safe to
    call more than once."""

    if "RPi" not in sys.modules:
        rpi = types.ModuleType("RPi")
        gpio = types.ModuleType("RPi.GPIO")
        gpio.BCM = "BCM"
        gpio.OUT = "OUT"
        gpio.HIGH = "HIGH"
        gpio.LOW = "LOW"
        gpio.calls = []

        def _output(pin, value):
            gpio.calls.append((pin, value))

        gpio.output = _output
        gpio.setmode = lambda mode: None
        gpio.setup = lambda pin, mode: None
        gpio.cleanup = lambda: None

        rpi.GPIO = gpio
        sys.modules["RPi"] = rpi
        sys.modules["RPi.GPIO"] = gpio

    if "w1thermsensor" not in sys.modules:
        w1 = types.ModuleType("w1thermsensor")

        class FakeW1ThermSensor:
            """Stand-in for w1thermsensor.W1ThermSensor. Tests replace
            ctrl._sensor with their own FakeSensor for per-test control;
            this only needs to exist so the constructor call in
            EnclosureFanController.__init__ doesn't blow up."""

            def get_temperature(self):
                return 20.0

        w1.W1ThermSensor = FakeW1ThermSensor
        sys.modules["w1thermsensor"] = w1

    if "octoprint" not in sys.modules:
        octoprint_mod = types.ModuleType("octoprint")
        plugin_mod = types.ModuleType("octoprint.plugin")

        for name in (
            "StartupPlugin",
            "SettingsPlugin",
            "TemplatePlugin",
            "AssetPlugin",
            "ShutdownPlugin",
            "EventHandlerPlugin",
        ):
            setattr(plugin_mod, name, type(name, (object,), {}))

        events_mod = types.ModuleType("octoprint.events")

        class Events:
            USER_LOGGED_IN = "UserLoggedIn"

        events_mod.Events = Events

        util_mod = types.ModuleType("octoprint.util")

        class RepeatedTimer:
            def __init__(self, interval, function, run_first=False):
                self.interval = interval
                self.function = function
                self.run_first = run_first
                self.started = False
                self.cancelled = False

            def start(self):
                self.started = True

            def cancel(self):
                self.cancelled = True

        util_mod.RepeatedTimer = RepeatedTimer

        octoprint_mod.plugin = plugin_mod
        octoprint_mod.events = events_mod
        octoprint_mod.util = util_mod

        sys.modules["octoprint"] = octoprint_mod
        sys.modules["octoprint.plugin"] = plugin_mod
        sys.modules["octoprint.events"] = events_mod
        sys.modules["octoprint.util"] = util_mod


def load_plugin_module():
    """Load a fresh copy of EnclosureFanController/__init__.py as its own
    module object, so each test gets an independent class/instance instead
    of sharing state through sys.modules caching."""

    install_fake_modules()

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    module_path = os.path.join(repo_root, "EnclosureFanController", "__init__.py")

    spec = importlib.util.spec_from_file_location(
        "enclosure_fan_controller_under_test", module_path
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeSensor:
    """Per-test controllable stand-in for a W1ThermSensor instance."""

    def __init__(self, temp_c=20.0):
        self.temp_c = temp_c
        self.raise_error = False

    def get_temperature(self):
        if self.raise_error:
            raise RuntimeError("simulated sensor failure")
        return self.temp_c


class FakeLogger:
    def __init__(self):
        self.messages = []

    def _record(self, level, msg, *args):
        self.messages.append((level, msg % args if args else msg))

    def info(self, msg, *args):
        self._record("info", msg, *args)

    def warning(self, msg, *args):
        self._record("warning", msg, *args)

    def error(self, msg, *args):
        self._record("error", msg, *args)


class FakeSettings:
    def __init__(self, values):
        self.values = dict(values)

    def get_int(self, path):
        value = self.values.get(path[0])
        return None if value is None else int(value)

    def get(self, path):
        return self.values.get(path[0])


class FakePluginManager:
    def __init__(self):
        self.messages = []

    def send_plugin_message(self, identifier, data):
        self.messages.append((identifier, data))


def make_controller(module, settings_values, temp_c=20.0):
    """Build an EnclosureFanController instance wired up with fakes, with
    GetSettingValues() already applied and hardware treated as having
    initialized successfully (ctrl._hardwareOk = True) - i.e. as if
    on_after_startup() had already run and found working hardware. Tests
    that specifically want to exercise the hardware-unavailable path
    (see HardwareUnavailableTests) call on_after_startup() themselves
    instead of relying on this shortcut."""

    ctrl = module.EnclosureFanController()
    ctrl._logger = FakeLogger()
    ctrl._settings = FakeSettings(settings_values)
    ctrl._plugin_manager = FakePluginManager()
    ctrl._identifier = "EnclosureFanController"
    ctrl._sensor = FakeSensor(temp_c=temp_c)
    ctrl._hardwareOk = True
    ctrl.GetSettingValues()
    return ctrl
