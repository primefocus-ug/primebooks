import os
from dataclasses import dataclass

AIRTEL_URLS = {
    "staging":    "https://openapiuat.airtel.ug",
    "production": "https://openapi.airtel.ug",
}

@dataclass
class AirtelConfig:
    env: str
    base_url: str
    client_id: str
    client_secret: str

    @classmethod
    def from_env(cls) -> "AirtelConfig":
        env = os.getenv("AIRTEL_ENV", "production").lower()  # default: production
        if env not in AIRTEL_URLS:
            raise ValueError(f"Invalid AIRTEL_ENV '{env}'. Choose: staging | production")
        return cls(
            env=env,
            base_url=AIRTEL_URLS[env],
            client_id=os.getenv("AIRTEL_CLIENT_ID", ""),
            client_secret=os.getenv("AIRTEL_CLIENT_SECRET", ""),
        )

# Singleton — import this everywhere
airtel_config = AirtelConfig.from_env()