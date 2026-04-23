import os
from dataclasses import dataclass

MOMO_URLS = {
    "staging":    "https://sandbox.momodeveloper.mtn.com/",
    "production": "https://momodeveloper.mtn.com/",
}

@dataclass
class MoMoConfig:
    env: str
    base_url: str
    primary_key: str
    secondary_key: str

    @classmethod
    def from_env(cls) -> "MoMoConfig":
        env = os.getenv("AIRTEL_ENV", "production").lower()  # default: production
        if env not in MOMO_URLS:
            raise ValueError(f"Invalid AIRTEL_ENV '{env}'. Choose: staging | production")
        return cls(
            env=env,
            base_url=MOMO_URLS[env],
            primary_key=os.getenv("MTN_PRIMARY_KEY", ""),
            secondary_key=os.getenv("MTN_SECONDARY_KEY", ""),
        )

# Singleton — import this everywhere
airtel_config = MoMoConfig.from_env()