from ovos_utils.log import LOG


class IntentLayers:
    def __init__(self):
        self._skill = None
        self._layers = {}

    def bind(self, skill):
        if skill:
            self._skill = skill
        return skill

    @property
    def skill(self):
        return self.skill

    @property
    def bus(self):
        return self._skill.bus if self._skill else None

    @property
    def skill_id(self):
        return self._skill.skill_id if self._skill else "IntentLayers"

    def disable(self):
        LOG.info("Disabling layers")
        # disable all layers
        for layer_name, intents in self._layers.items():
            self.deactivate_layer(layer_name)

    def update_layer(self, layer_name, intent_list=None):
        layer_name = f"{self.skill_id}:{layer_name}"
        intent_list = intent_list or []
        self._layers.setdefault(layer_name, [])
        self._layers[layer_name] += intent_list or []
        LOG.info(f"Adding {intent_list} to {layer_name}")

    def activate_layer(self, layer_name):
        layer_name = f"{self.skill_id}:{layer_name}"
        if layer_name in self._layers:
            self.disable()
            LOG.info("activating layer named: " + layer_name)
            for intent in self._layers[layer_name]:
                self.skill.enable_intent(intent)
        else:
            LOG.error("no layer named: " + layer_name)

    def deactivate_layer(self, layer_name):
        layer_name = f"{self.skill_id}:{layer_name}"
        if layer_name in self._layers:
            LOG.info("deactivating layer named: " + layer_name)
            for intent in self._layers[layer_name]:
                self.skill.disable_intent(intent)
        else:
            LOG.error("no layer named: " + layer_name)

    def remove_layer(self, layer_name):
        layer_name = f"{self.skill_id}:{layer_name}"
        if layer_name in self._layers:
            LOG.info("removing layer named: " + layer_name)
            self._layers.pop(layer_name)
        else:
            LOG.error("no layer named: " + layer_name)

    def replace_layer(self, layer_name, intent_list=None):
        layer_name = f"{self.skill_id}:{layer_name}"
        if layer_name in self._layers:
            LOG.info("replacing layer named: " + layer_name)
            self._layers[layer_name] = intent_list or []
        else:
            self.update_layer(layer_name, intent_list)
