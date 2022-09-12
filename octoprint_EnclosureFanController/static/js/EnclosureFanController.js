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
	    self.enclosureTemp("N/A");
        };

	self.onDataUpdaterPluginMessage = function(plugin, data) {
		if (plugin != "EnclosureFanController"){
			return;
		}

		if (data.enclosureTemp){
			var temperature = 0
			temperature = data.enclosureTemp;
			if (temperature == 0){
				temperature = "N/A";
			}

			self.enclosureTemp("Enclosure: ". concat(temperature));
		}
	};
    }

    // This is how our plugin registers itself with the application, by adding some configuration
    // information to the global variable OCTOPRINT_VIEWMODELS
    OCTOPRINT_VIEWMODELS.push([
        // This is the constructor to call for instantiating the plugin
        EnclosureFanControllerViewModel,

        // This is a list of dependencies to inject into the plugin, the order which you request
        // here is the order in which the dependencies will be injected into your view model upon
        // instantiation via the parameters argument
        ["settingsViewModel"],

        // Finally, this is the list of selectors for all elements we want this view model to be bound to.
        ["#tab_plugin_EnclosureFanController", "#navbar_plugin_EnclosureFanController"]
    ]);
});
