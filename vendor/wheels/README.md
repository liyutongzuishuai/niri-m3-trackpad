# Vendored Python wheel

`evdev_binary-2.0.0-cp314-cp314-manylinux1_x86_64...whl` is the pinned
`evdev-binary==2.0.0` wheel from `profiles/elan-touch/requirements.lock`.
Its SHA-256 is `21a10b2d2f16f087693817f5d51c87b196ff2777d7d7ec9565b8763eeecaa3f8`,
matching the lockfile hash.

`scripts/install.sh` installs this wheel into the Elan profile's venv with
`pip install --no-index`, so `./scripts/install.sh --apply` works on an
offline Fedora 44 / Python 3.14 x86_64 machine. If the wheel is absent or
incompatible, the installer falls back to the hash-checked PyPI download in
`requirements.lock`.

Other platforms/Python versions must use the fallback (or replace this wheel
with one built for their interpreter).
