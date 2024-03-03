$(function() {
    function EnclosureFanControllerViewModel(parameters) {
        var self = this;

        self.settings = parameters[0];
	self.enclosureTemp = ko.observable();

        // This will get called before the EnclosureFanControllerViewModel gets bound to the DOM, but after its
        // dependencies have already been initialized. It is especially guaranteed that this method
        // gets called _after_ the settings have been retrieved from the OctoPrint backend and thus
        // the SettingsViewModel been properly populated.
        self.onBeforeBinding = function() {
		self.enclosureTemp("");
        };

	self.onDataUpdaterPluginMessage = function(plugin, data) {
		if (plugin != "EnclosureFanController"){
			return;
		}

		if (data.enclosureTemp){
			var temperature = 0
			temperature = parseFloat(data.enclosureTemp);

			if (temperature > 0){
				self.enclosureTemp("Enclosure: " +  sprintf("%.1f&deg;F", temperature));
			}
			else
			{
				self.enclosurerTemp("N/A");
			}
		}
	};
    }

    // This is how our plugin registers itself with the application, by adding some configuration
    // information to the global variable OCTOPRINT_VIEWMODELS
    OCTOPRINT_VIEWMODELS.push([
	EnclosureFanControllerViewModel,
	["settingsViewModel"],
	["#tab_plugin_EnclosureFanController","#settings_plugin_EnclosureFanController","#navbar_plugin_EnclosureFanController"]
    ]);
});
