import unittest
from pprint import pformat
from logging import getLogger

LOG = getLogger("licheck")
LOG.setLevel("DEBUG")

from lichecker import LicenseChecker

# these packages dont define license in setup.py
# manually verified and injected
license_overrides = {
    "kthread": "MIT",
    'yt-dlp': "Unlicense",
    'pyxdg': 'GPL-2.0',
    'ptyprocess': 'ISC license',
    'psutil': 'BSD3'
}
# explicitly allow these packages that would fail otherwise
whitelist = []

# validation flags
allow_nonfree = False
allow_viral = False
allow_unknown = False
allow_unlicense = True
allow_ambiguous = False

pkg_name = "ovos_workshop"


class TestLicensing(unittest.TestCase):
    @classmethod
    def setUpClass(self):
        licheck = LicenseChecker(pkg_name,
                                 license_overrides=license_overrides,
                                 whitelisted_packages=whitelist,
                                 allow_ambiguous=allow_ambiguous,
                                 allow_unlicense=allow_unlicense,
                                 allow_unknown=allow_unknown,
                                 allow_viral=allow_viral,
                                 allow_nonfree=allow_nonfree)
        LOG.info("Package " + pkg_name)
        LOG.info("Version" + licheck.version)
        LOG.info("License" + licheck.license)
        LOG.info("Transient Requirements (dependencies of dependencies)")
        LOG.info(pformat(licheck.transient_dependencies))
        self.licheck = licheck

    def test_license_compliance(self):
        LOG.info("Package Versions")
        LOG.info(pformat(self.licheck.versions))

        LOG.info("Dependency Licenses")
        LOG.info(pformat(self.licheck.licenses))

        self.licheck.validate()
