from setuptools import setup


def _get_version():
    with open('ovos_workshop/versioning/ows_versions.py') as versions:
        for line in versions:
            if line.startswith('CURRENT_OWS_VERSION'):
                # CURRENT_OSM_VERSION = "0.0.10a9" --> "0.0.10a9"
                return line.replace('"','').strip('\n').split('= ')[1]


setup(
    name='ovos_workshop',
    version=_get_version(),
    packages=['ovos_workshop',
              'ovos_workshop.skills',
              'ovos_workshop.skills.decorators',
              'ovos_workshop.patches'],
    install_requires=["ovos_utils>=0.0.12a5",
                      "ovos_plugin_common_play~=0.0.1a11"],
    url='https://github.com/OpenVoiceOS/OVOS-workshop',
    license='apache-2.0',
    author='jarbasAi',
    author_email='jarbasai@mailfence.com',
    include_package_data=True,
    description='frameworks, templates and patches for the mycroft universe'
)
