pkgbase='python-ovos-workshop'
pkgname=('python-ovos-workshop')
_module='ovos-workshop'
pkgver='0.0.11'
pkgrel=1
pkgdesc="frameworks, templates and utils for the OVOS universe"
url="https://github.com/OpenVoiceOS/OVOS-workshop"
depends=('python')
makedepends=('python-setuptools')
license=('unknown')
arch=('any')
source=("https://files.pythonhosted.org/packages/08/0c/7eb55b41f7a93f7d7078b8ab7968feb49c36b131d3bcee66976ff7cf878b/ovos_workshop-${pkgver}-py3-none-any.whl")
sha256sums=('98703a4de5076a0bbd6d9bb3fbf47175a68022870f44cca989c53eb1bbeb1d52')

build() {
    cd "${srcdir}/${_module}-${pkgver}"
    python setup.py build
}

package() {
    depends+=()
    cd "${srcdir}/${_module}-${pkgver}"
    python setup.py install --root="${pkgdir}" --optimize=1 --skip-build
}
