"""
Staging settings - similar to production but with DEBUG=True for testing
"""
from .production import *

DEBUG = True
ALLOWED_HOSTS = os.getenv('ALLOWED_HOSTS', '').split(',')

# Use less restrictive logging for staging
LOGGING['root']['level'] = 'DEBUG'
