from setuptools import setup

setup(
    name='ovos_workshop',
    version='0.0.4a8',
    packages=['ovos_workshop',
              'ovos_workshop.skills',
              'ovos_workshop.skills.decorators',
              'ovos_workshop.patches',
              'ovos_workshop.frameworks',
              'ovos_workshop.frameworks.canvas',
              'ovos_workshop.frameworks.playback',
              'ovos_workshop.frameworks.questions',
              'ovos_workshop.frameworks.tv'],
    install_requires=["ovos_utils"],
    url='https://github.com/OpenVoiceOS/OVOS-workshop',
    license='apache-2.0',
    author='jarbasAi',
    author_email='jarbasai@mailfence.com',
    include_package_data=True,
    description='frameworks, templates and patches for the mycroft universe'
)
