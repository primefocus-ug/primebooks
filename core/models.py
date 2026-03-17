from django.db import models
from django.conf import settings


class TenantWorkspaceDefault(models.Model):
    """
    Tenant-wide default workspace layout.
    Set by a tenant admin — all users inherit this unless they override it.
    Stored once per tenant (schema).
    """
    # On django-tenants, you typically don't need a tenant FK because
    # each tenant has its own schema. If you use a shared schema approach,
    # add: tenant = models.OneToOneField('tenants.Client', ...)
    nav_mode      = models.CharField(max_length=20, default='sidebar')   # sidebar|topnav|tabs
    header_order  = models.JSONField(default=list,  blank=True)          # ['theme','language',...]
    sidebar_order = models.JSONField(default=list,  blank=True)          # ['Sales','Inventory',...]
    extra_config  = models.JSONField(default=dict, blank=True,
                      help_text="Tenant-wide theme/accessibility defaults "
                                "(accentColor, fontSize, density, highContrast, etc.)")
    updated_at    = models.DateTimeField(auto_now=True)
    updated_by    = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='+'
    )

    class Meta:
        verbose_name = "Tenant Workspace Default"

    def __str__(self):
        return f"TenantDefault(nav={self.nav_mode})"

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def to_dict(self):
        return {
            'navMode':      self.nav_mode,
            'headerOrder':  self.header_order,
            'sidebarOrder': self.sidebar_order,
            # Theme / accessibility defaults (stored in extra_config JSON if present)
            'accentColor':  getattr(self, 'accent_color',   None) or (self.extra_config or {}).get('accentColor'),
            'fontSize':     getattr(self, 'font_size',      None) or (self.extra_config or {}).get('fontSize'),
            'density':      getattr(self, 'density',        None) or (self.extra_config or {}).get('density'),
            'highContrast': (self.extra_config or {}).get('highContrast', False),
            'reduceMotion': (self.extra_config or {}).get('reduceMotion', False),
            'focusRings':   (self.extra_config or {}).get('focusRings',   False),
            'rtl':          (self.extra_config or {}).get('rtl',          False),
        }


class UserNavigationPreference(models.Model):
    """
    Per-user layout overrides.  Merges on top of TenantWorkspaceDefault.

    hidden_items:     JSON list of dot-key nav items the user has hidden.
    workspace_layout: JSON object with the user's personal layout overrides:
                        navMode      – "sidebar" | "topnav" | "tabs"  (or null = use tenant default)
                        headerOrder  – list of header element IDs      (or [] = use tenant default)
                        sidebarOrder – list of top-level nav keys      (or [] = use tenant default)
    """
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='nav_preference'
    )
    hidden_items     = models.JSONField(default=list, blank=True)
    workspace_layout = models.JSONField(default=dict, blank=True)   # ← NEW
    updated_at       = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = "User Navigation Preference"
        verbose_name_plural = "User Navigation Preferences"

    def __str__(self):
        return f"NavPref({self.user})"

    # ── hidden items helpers ──────────────────────────────────────────────
    def is_hidden(self, key: str) -> bool:
        return key in self.hidden_items

    def set_hidden(self, key: str, hidden: bool):
        items = set(self.hidden_items)
        if hidden:
            items.add(key)
        else:
            items.discard(key)
        self.hidden_items = list(items)

    # ── workspace layout helpers ─────────────────────────────────────────
    def effective_layout(self) -> dict:
        """
        Returns the resolved layout: tenant default merged with user overrides.
        User values take precedence when set (non-null / non-empty).

        Covers all fields written by the workspace engine:
          core layout   : navMode, headerOrder, sidebarOrder
          visibility    : hiddenItems
          theme         : accentColor, fontSize, density
          accessibility : highContrast, reduceMotion, focusRings, rtl
        """
        tenant = TenantWorkspaceDefault.get().to_dict()
        user   = self.workspace_layout or {}
        return {
            # ── Core layout ──────────────────────────────────────────────
            'navMode':      user.get('navMode')      or tenant.get('navMode')      or 'sidebar',
            'headerOrder':  user.get('headerOrder')  or tenant.get('headerOrder')  or [],
            'sidebarOrder': user.get('sidebarOrder') or tenant.get('sidebarOrder') or [],
            # ── Visibility toggles ───────────────────────────────────────
            'hiddenItems':  user.get('hiddenItems')  or [],
            # ── Theme ────────────────────────────────────────────────────
            'accentColor':  user.get('accentColor')  or tenant.get('accentColor')  or None,
            'fontSize':     user.get('fontSize')     or tenant.get('fontSize')     or None,
            'density':      user.get('density')      or tenant.get('density')      or None,
            # ── Accessibility (booleans — explicit key check so False is kept) ──
            'highContrast': user['highContrast'] if 'highContrast' in user else tenant.get('highContrast', False),
            'reduceMotion': user['reduceMotion'] if 'reduceMotion' in user else tenant.get('reduceMotion', False),
            'focusRings':   user['focusRings']   if 'focusRings'   in user else tenant.get('focusRings',   False),
            'rtl':          user['rtl']          if 'rtl'          in user else tenant.get('rtl',          False),
        }

    @classmethod
    def get_for_user(cls, user):
        obj, _ = cls.objects.get_or_create(user=user)
        return obj