# primebooks/update_api_views.py
"""
Server-side Update API
✅ Version checking
✅ Update file hosting
✅ Release notes management
"""
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, AllowAny
from primebooks.authentication import TenantAwareJWTAuthentication
from django.conf import settings
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

# ============================================================================
# UPDATE CONFIGURATION
# ============================================================================

# ✅ UPDATE THIS when releasing new version
LATEST_VERSION = "1.1.0"
DOWNLOAD_URL = "https://primebooks.sale/downloads/PrimeBooks_v1.1.0.exe"
FILE_SIZE_MB = 45.2
RELEASE_NOTES = """
**What's New in v1.1.0:**

🐛 **Bug Fixes:**
- Fixed sync error when offline
- Resolved product image upload issue
- Fixed invoice generation bug

✨ **Improvements:**
- Faster data sync (50% speed improvement)
- Better offline performance
- Improved error messages

🔒 **Security:**
- Updated dependencies
- Enhanced data encryption
"""

# For critical updates
IS_CRITICAL = False
MAINTENANCE_START = "2026-02-01T02:00:00"  # ISO format


class UpdateCheckView(APIView):
    """
    Check if update is available
    GET /api/desktop/updates/check/?current_version=1.0.0
    """
    authentication_classes = [TenantAwareJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            current_version = request.GET.get('current_version', '0.0.0')

            logger.info(f"Update check: current={current_version}, latest={LATEST_VERSION}")

            # Parse versions
            current = tuple(map(int, current_version.split('.')))
            latest = tuple(map(int, LATEST_VERSION.split('.')))

            update_available = latest > current

            if update_available:
                return Response({
                    'update_available': True,
                    'current_version': current_version,
                    'latest_version': LATEST_VERSION,
                    'download_url': DOWNLOAD_URL,
                    'file_size_mb': FILE_SIZE_MB,
                    'release_notes': RELEASE_NOTES,
                    'is_critical': IS_CRITICAL,
                    'maintenance_start': MAINTENANCE_START if IS_CRITICAL else None,
                })
            else:
                return Response({
                    'update_available': False,
                    'current_version': current_version,
                    'latest_version': LATEST_VERSION,
                })

        except Exception as e:
            logger.error(f"Update check error: {e}")
            return Response({
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class ReleaseNotesView(APIView):
    """
    Get release notes for a version
    GET /api/desktop/updates/release-notes/?version=1.1.0
    """
    permission_classes = [AllowAny]

    def get(self, request):
        version = request.GET.get('version', LATEST_VERSION)

        # In production, fetch from database
        # For now, return current release notes
        return Response({
            'version': version,
            'release_notes': RELEASE_NOTES,
            'release_date': '2026-01-28',
        })


class VersionHistoryView(APIView):
    """
    Get version history
    GET /api/desktop/updates/history/
    """
    permission_classes = [AllowAny]

    def get(self, request):
        # In production, fetch from database
        history = [
            {
                'version': '1.1.0',
                'release_date': '2026-01-28',
                'release_notes': RELEASE_NOTES,
                'is_critical': False,
            },
            {
                'version': '1.0.0',
                'release_date': '2026-01-15',
                'release_notes': 'Initial release',
                'is_critical': False,
            },
        ]

        return Response({
            'versions': history,
            'latest_version': LATEST_VERSION,
        })