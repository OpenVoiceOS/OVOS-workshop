from json_database import JsonStorageXDG


def settings2meta(settings, section_name="Skill Settings"):
    """ generates basic settingsmeta """
    fields = []

    for k, v in settings.items():
        if k.startswith("_"):
            continue
        label = k.replace("-", " ").replace("_", " ").title()
        if isinstance(v, bool):
            fields.append({
                "name": k,
                "type": "checkbox",
                "label": label,
                "value": str(v).lower()
            })
        if isinstance(v, str):
            fields.append({
                "name": k,
                "type": "text",
                "label": label,
                "value": v
            })
        if isinstance(v, int):
            fields.append({
                "name": k,
                "type": "number",
                "label": label,
                "value": str(v)
            })
    return {
        "skillMetadata": {
            "sections": [
                {
                    "name": section_name,
                    "fields": fields
                }
            ]
        }
    }


class PrivateSettings(JsonStorageXDG):
    def __init__(self, skill_id):
        super(PrivateSettings, self).__init__(skill_id)

    @property
    def settingsmeta(self):
        return settings2meta(self, self.name)
