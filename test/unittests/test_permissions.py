import unittest

from ovos_workshop.permissions import ConverseMode, FallbackMode, ConverseActivationMode


class TestPermissions(unittest.TestCase):
    def test_converse_mode(self):
        self.assertIsInstance(ConverseMode.ACCEPT_ALL, str)
        self.assertIsInstance(ConverseMode.WHITELIST, str)
        self.assertIsInstance(ConverseMode.BLACKLIST, str)

    def test_fallback_mode(self):
        self.assertIsInstance(FallbackMode.ACCEPT_ALL, str)
        self.assertIsInstance(FallbackMode.WHITELIST, str)
        self.assertIsInstance(FallbackMode.BLACKLIST, str)

    def test_converse_activation_mode(self):
        self.assertIsInstance(ConverseActivationMode.ACCEPT_ALL, str)
        self.assertIsInstance(ConverseActivationMode.PRIORITY, str)
        self.assertIsInstance(ConverseActivationMode.WHITELIST, str)
        self.assertIsInstance(ConverseActivationMode.BLACKLIST, str)
