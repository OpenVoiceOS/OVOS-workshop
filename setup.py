from setuptools import setup

setup(
    name='ovos_workshop',
    version='0.0.1a1',
    packages=['ovos_workshop',
              'ovos_workshop.utils',
              'ovos_workshop.skills',
              'ovos_workshop.patches',
              'ovos_workshop.frameworks'],
    install_requires=["ovos_utils"],
    url='https://github.com/OpenVoiceOS/OVOS-workshop',
    license='apache-2.0',
    author='jarbasAi',
    author_email='jarbasai@mailfence.com',
    description='frameworks, templates and patches for the mycroft universe'
)
