from django import template
from django.conf import settings
from django.utils.safestring import mark_safe

register = template.Library()


@register.simple_tag
def analytics_script():
    """
    Include analytics tracking script.
    Usage: {% load analytics_tags %}{% analytics_script %}
    """

    script = """
    <script>
    (function() {
        // Track custom events
        window.trackEvent = function(category, action, label, value) {
            fetch('/analytics/event/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    category: category,
                    action: action,
                    label: label || '',
                    value: value || null,
                    url_path: window.location.pathname,
                    page_title: document.title
                })
            }).catch(function(error) {
                console.error('Analytics error:', error);
            });
        };

        // Auto-track outbound links
        document.addEventListener('click', function(e) {
            var link = e.target.closest('a');
            if (link && link.hostname !== window.location.hostname) {
                trackEvent('CLICK', 'outbound_link', link.href);
            }
        });

        // Track time on page
        var startTime = Date.now();
        window.addEventListener('beforeunload', function() {
            var timeOnPage = Math.round((Date.now() - startTime) / 1000);
            navigator.sendBeacon('/analytics/event/', JSON.stringify({
                category: 'ENGAGEMENT',
                action: 'time_on_page',
                value: timeOnPage,
                url_path: window.location.pathname
            }));
        });

        // Track scroll depth
        var maxScroll = 0;
        var scrollTracked = false;
        window.addEventListener('scroll', function() {
            var scrollPercent = Math.round(
                (window.scrollY / (document.body.scrollHeight - window.innerHeight)) * 100
            );
            maxScroll = Math.max(maxScroll, scrollPercent);

            // Track when user reaches 75% scroll
            if (maxScroll >= 75 && !scrollTracked) {
                trackEvent('SCROLL', 'scroll_depth_75');
                scrollTracked = true;
            }
        });
    })();
    </script>
    """

    return mark_safe(script)


@register.inclusion_tag('public_analytics/conversion_pixel.html')
def conversion_pixel(conversion_type, conversion_value=None):
    """
    Track conversion.
    Usage: {% conversion_pixel 'SIGNUP_COMPLETED' %}
    """
    return {
        'conversion_type': conversion_type,
        'conversion_value': conversion_value
    }