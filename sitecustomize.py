from __future__ import annotations

import os


if os.environ.get("TB2_HARBOR_NETWORK_POOL_CIDR"):
    from tb2_harbor_network_patch import install

    install()
