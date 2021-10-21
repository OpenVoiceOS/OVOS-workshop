from ovos_utils.log import LOG


class IntentLayers:
    def __init__(self):
        self._skill = None
        self._layers = {}
        self._active_layers = []

    def bind(self, skill):
        if skill:
            self._skill = skill
        return self

    @property
    def skill(self):
        return self._skill

    @property
    def bus(self):
        return self._skill.bus if self._skill else None

    @property
    def skill_id(self):
        return self._skill.skill_id if self._skill else "IntentLayers"

    @property
    def active_layers(self):
        return self._active_layers

    def disable(self):
        LOG.info("Disabling layers")
        # disable all layers
        for layer_name, intents in self._layers.items():
            self.deactivate_layer(layer_name)

    def update_layer(self, layer_name, intent_list=None):
        if not layer_name.startswith(f"{self.skill_id}:"):
            layer_name = f"{self.skill_id}:{layer_name}"
        intent_list = intent_list or []
        if layer_name not in self._layers:
            self._layers[layer_name] = []
        self._layers[layer_name] += intent_list or []
        LOG.info(f"Adding {intent_list} to {layer_name}")

    def activate_layer(self, layer_name):
        if not layer_name.startswith(f"{self.skill_id}:"):
            layer_name = f"{self.skill_id}:{layer_name}"
        if layer_name in self._layers:
            LOG.info("activating layer named: " + layer_name)
            if layer_name not in self._active_layers:
                self._active_layers.append(layer_name)
            for intent in self._layers[layer_name]:
                self.skill.enable_intent(intent)
        else:
            LOG.debug("no layer named: " + layer_name)

    def deactivate_layer(self, layer_name):
        if not layer_name.startswith(f"{self.skill_id}:"):
            layer_name = f"{self.skill_id}:{layer_name}"
        if layer_name in self._layers:
            LOG.info("deactivating layer named: " + layer_name)
            if layer_name in self._active_layers:
                self._active_layers.remove(layer_name)
            for intent in self._layers[layer_name]:
                self.skill.disable_intent(intent)
        else:
            LOG.debug("no layer named: " + layer_name)

    def remove_layer(self, layer_name):
        if not layer_name.startswith(f"{self.skill_id}:"):
            layer_name = f"{self.skill_id}:{layer_name}"
        if layer_name in self._layers:
            self.deactivate_layer(layer_name)
            LOG.info("removing layer named: " + layer_name)
            self._layers.pop(layer_name)
        else:
            LOG.debug("no layer named: " + layer_name)

    def replace_layer(self, layer_name, intent_list=None):
        if not layer_name.startswith(f"{self.skill_id}:"):
            layer_name = f"{self.skill_id}:{layer_name}"
        if layer_name in self._layers:
            LOG.info("replacing layer named: " + layer_name)
            self._layers[layer_name] = intent_list or []
        else:
            self.update_layer(layer_name, intent_list)

    def is_active(self, layer_name):
        if not layer_name.startswith(f"{self.skill_id}:"):
            layer_name = f"{self.skill_id}:{layer_name}"
        return layer_name in self.active_layers
