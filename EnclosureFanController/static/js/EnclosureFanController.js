$(function() {
    function EnclosureFanControllerViewModel(parameters) {
        var self = this;

        self.settings = parameters[0];
	self.enclosureTemp = ko.observable();
	self.fanState = ko.observable();
	// Raw temperature value (no "Enclosure: " label baked in, unlike
	// enclosureTemp above) and the fan's boolean state, kept separate so
	// the Enclosure tab can lay them out as a status card with its own
	// labels/badge styling instead of reusing the navbar's plain-text
	// strings. undefined means "no reading yet".
	self.enclosureTempValue = ko.observable();
	self.fanIsOn = ko.observable();
	// Intentionally not cleared before binding - if hardware failed to
	// initialize at startup, the initial value is rendered server-side
	// directly into the tab/settings/navbar templates, since that's the
	// common case (page load/reload after a restart) and shouldn't depend
	// on a websocket message having already arrived. This observable is a
	// secondary path that only matters for a tab that was already open at
	// the moment OctoPrint restarted.
	self.hardwareError = ko.observable();

        // This will get called before the EnclosureFanControllerViewModel gets bound to the DOM, but after its
        // dependencies have already been initialized. It is especially guaranteed that this method
        // gets called _after_ the settings have been retrieved from the OctoPrint backend and thus
        // the SettingsViewModel been properly populated.
        self.onBeforeBinding = function() {
		self.enclosureTemp("");
		self.fanState("");
		self.enclosureTempValue("");
		self.fanIsOn(undefined);
        };

	self.onDataUpdaterPluginMessage = function(plugin, data) {
		if (plugin != "EnclosureFanController"){
			return;
		}

		if (data.hardwareError){
			self.hardwareError(data.hardwareError);
		}

		if (data.sensorError){
			self.enclosureTemp("N/A");
			self.enclosureTempValue("N/A");
		}
		else if (data.enclosureTemp !== undefined && data.enclosureTemp !== null){
			var temperature = parseFloat(data.enclosureTemp);
			var unit = (data.tempUnit === "C") ? "C" : "F";
			var formatted = sprintf("%.1f&deg;" + unit, temperature);
			self.enclosureTemp("Enclosure: " + formatted);
			self.enclosureTempValue(formatted);
		}

		if (data.fanIsOn !== undefined){
			self.fanState(data.fanIsOn ? "Fan: ON" : "Fan: OFF");
			self.fanIsOn(data.fanIsOn);
		}
	};

	// Badge text/CSS class for the Enclosure tab's fan status. Separate
	// from fanState above so the tab can show a colored badge (green/ON,
	// dark/OFF, neutral/unknown) while the navbar keeps its plain text.
	// Also treated as unknown whenever hardwareError is set, since a
	// stale "OFF" reading next to an error banner would be misleading -
	// we genuinely don't know the physical fan state in that case.
	self.fanBadgeText = ko.pureComputed(function() {
		if (self.hardwareError() || self.fanIsOn() === undefined) {
			return "—";
		}
		return self.fanIsOn() ? "ON" : "OFF";
	});

	self.fanBadgeClass = ko.pureComputed(function() {
		if (self.hardwareError() || self.fanIsOn() === undefined) {
			return "label";
		}
		return self.fanIsOn() ? "label label-success" : "label label-inverse";
	});

	// Client-side feedback for invalid hysteresis/threshold combinations,
	// mirroring the defensive clamping the server also applies to saved
	// settings.
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
