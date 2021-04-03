from setuptools import setup

setup(
    name='ovos_workshop',
    version='0.0.1a2',
    packages=['ovos_workshop',
              'ovos_workshop.skills',
              'ovos_workshop.skills.decorators',
              'ovos_workshop.patches',
              'ovos_workshop.frameworks',
              'ovos_workshop.frameworks.cps',
              'ovos_workshop.frameworks.ciptv'],
    install_requires=["ovos_utils"],
    url='https://github.com/OpenVoiceOS/OVOS-workshop',
    license='apache-2.0',
    author='jarbasAi',
    author_email='jarbasai@mailfence.com',
    include_package_data=True,
    description='frameworks, templates and patches for the mycroft universe'
)
