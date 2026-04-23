# ============================================================
#   MTN MOBILE MONEY API - CONFIGURATION
#   Replace these values with your actual credentials
# ============================================================

# --- SANDBOX BASE URL (change to production URL when ready) ---
BASE_URL = "https://sandbox.momodeveloper.mtn.com"

# --- SUBSCRIPTION KEY (from MTN Developer Portal) ---
SUBSCRIPTION_KEY = "YOUR_SUBSCRIPTION_KEY_HERE"

# --- API USER (UUID v4 you generated via provisioning) ---
API_USER = "YOUR_API_USER_UUID_HERE"

# --- API KEY (generated via /apiuser/{uuid}/apikey) ---
API_KEY = "YOUR_API_KEY_HERE"

# --- TARGET ENVIRONMENT ---
# Use "sandbox" for testing, change to your country code for production
# e.g. "mtnuganda", "mtnghana", "mtnivorycoast", etc.
TARGET_ENVIRONMENT = "sandbox"

# --- CALLBACK URL (optional - your server endpoint for async callbacks) ---
PROVIDER_CALLBACK_HOST = "https://meager-mayra-deteriorative.ngrok-free.dev"
