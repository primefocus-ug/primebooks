from django.views import View
from django.http import HttpResponse
from .models import RobotsTxt


class RobotsTxtView(View):
    """
    Serve robots.txt dynamically.
    """

    def get(self, request):
        try:
            robots = RobotsTxt.objects.get(is_active=True)
            content = robots.content
        except RobotsTxt.DoesNotExist:
            content = "User-agent: *\nAllow: /"

        return HttpResponse(content, content_type='text/plain')