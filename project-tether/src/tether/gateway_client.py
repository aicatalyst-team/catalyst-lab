"""Local-development bridge for Tether's runtime verification mirror.

The container build copies the canonical mirror from ``tests/tether`` into
this package. Keeping this small bridge in the source tree makes
``tether.server`` importable before the container build has assembled that
runtime package.
"""

# pylint: disable=wildcard-import,unused-wildcard-import
from tests.tether.gateway_client import *  # noqa: F401,F403
