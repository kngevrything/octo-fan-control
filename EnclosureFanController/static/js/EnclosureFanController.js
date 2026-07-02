$(function() {
    function EnclosureFanControllerViewModel(parameters) {
        var self = this;

        self.settings = parameters[0];
	self.enclosureTemp = ko.observable();
	self.fanState = ko.observable();

        // This will get called before the EnclosureFanControllerViewModel gets bound to the DOM, but after its
        // dependencies have already been initialized. It is especially guaranteed that this method
        // gets called _after_ the settings have been retrieved from the OctoPrint backend and thus
        // the SettingsViewModel been properly populated.
        self.onBeforeBinding = function() {
		self.enclosureTemp("");
		self.fanState("");
        };

	self.onDataUpdaterPluginMessage = function(plugin, data) {
		if (plugin != "EnclosureFanController"){
			return;
		}

		if (data.sensorError){
			self.enclosureTemp("N/A");
		}
		else if (data.enclosureTemp !== undefined && data.enclosureTemp !== null){
			var temperature = parseFloat(data.enclosureTemp);
			var unit = (data.tempUnit === "C") ? "C" : "F";
			self.enclosureTemp("Enclosure: " + sprintf("%.1f&deg;" + unit, temperature));
		}

		if (data.fanIsOn !== undefined){
			self.fanState(data.fanIsOn ? "Fan: ON" : "Fan: OFF");
		}
	};

	// Client-side feedback for invalid hysteresis/threshold combinations,
	// mirroring the defensive clamping GetSettingValues() does server-side.
	self.hysteresisWarning = ko.pureComputed(function() {
		var pluginSettings = self.settings.settings.plugins.EnclosureFanController;
		if (!pluginSettings) {
			return "";
		}

		var threshold = parseFloat(ko.unwrap(pluginSettings.thresholdTemp));
		var hysteresis = parseFloat(ko.unwrap(pluginSettings.thresholdHysteresis));

		if (isNaN(hysteresis) || hysteresis <= 0) {
			return "Hysteresis must be a positive number.";
		}
		if (!isNaN(threshold) && hysteresis >= threshold) {
			return "Hysteresis must be less than the threshold temperature.";
		}
		return "";
	});
    }

    // This is how our plugin registers itself with the application, by adding some configuration
    // information to the global variable OCTOPRINT_VIEWMODELS
    OCTOPRINT_VIEWMODELS.push([
	EnclosureFanControllerViewModel,
	["settingsViewModel"],
	["#tab_plugin_EnclosureFanController","#settings_plugin_EnclosureFanController","#navbar_plugin_EnclosureFanController"]
    ]);
});
