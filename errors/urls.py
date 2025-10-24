# from functools import wraps
# from django.http import HttpResponseForbidden
#
#
# def maintenance_mode_exempt(view_func):
#     """
#     Decorator to exempt specific views from maintenance mode
#     """
#
#     @wraps(view_func)
#     def _wrapped_view(request, *args, **kwargs):
#         return view_func(request, *args, **kwargs)
#
#     _wrapped_view.maintenance_exempt = True
#     return _wrapped_view
#
#
# def api_error_handler_decorator(view_func):
#     """
#     Decorator to automatically handle API errors with JSON responses
#     """
#
#     @wraps(view_func)
#     def _wrapped_view(request, *args, **kwargs):
#         try:
#             return view_func(request, *args, **kwargs)
#         except Exception as e:
#             if request.content_type == 'application/json' or 'api/' in request.path:
#                 from .views import api_error_handler
#                 return api_error_handler(request, 500, str(e))
#             else:
#                 raise
#
#     return _wrapped_view