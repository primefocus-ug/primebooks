import os
from django.core.wsgi import get_wsgi_application
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
env_path = Path(__file__).resolve().parent.parent / '.env'
load_dotenv(dotenv_path=env_path)

# Set Django settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'tenancy.settings')

application = get_wsgi_application()