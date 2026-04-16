from rest_framework import serializers
from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.utils.translation import gettext_lazy as _
from .models import CustomUser, UserSignature, Role, RoleHistory, APIToken, UserSession



class UserRegistrationSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, validators=[validate_password])
    password_confirm = serializers.CharField(write_only=True)

    class Meta:
        model = CustomUser
        fields = [
            'email', 'username', 'first_name', 'last_name',
            'phone_number', 'password', 'password_confirm'
        ]
        extra_kwargs = {
            'email': {'required': True},
            'username': {'required': True},
        }

    def validate(self, attrs):
        if attrs['password'] != attrs['password_confirm']:
            raise serializers.ValidationError("Passwords don't match.")
        return attrs

    def create(self, validated_data):
        validated_data.pop('password_confirm')
        password = validated_data.pop('password')
        return CustomUser.objects.create_user(password=password, **validated_data)


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField()

    def validate(self, attrs):
        email = attrs.get('email')
        password = attrs.get('password')

        if email and password:
            user = authenticate(
                request=self.context.get('request'),
                username=email,
                password=password
            )
            if not user:
                raise serializers.ValidationError('Unable to log in with provided credentials.')
            if not user.is_active:
                raise serializers.ValidationError('User account is disabled.')
        else:
            raise serializers.ValidationError('Must include email and password.')

        attrs['user'] = user
        return attrs


class PasswordChangeSerializer(serializers.Serializer):
    old_password = serializers.CharField(required=True)
    new_password = serializers.CharField(required=True, validators=[validate_password])
    confirm_password = serializers.CharField(required=True)

    def validate_old_password(self, value):
        user = self.context['request'].user
        if not user.check_password(value):
            raise serializers.ValidationError("Old password is incorrect.")
        return value

    def validate(self, attrs):
        if attrs['new_password'] != attrs['confirm_password']:
            raise serializers.ValidationError("New passwords don't match.")
        return attrs

    def save(self, **kwargs):
        user = self.context['request'].user
        user.set_password(self.validated_data['new_password'])
        user.save()
        return user



class UserSerializer(serializers.ModelSerializer):
    primary_role = serializers.SerializerMethodField()
    roles = serializers.SerializerMethodField()
    role_display = serializers.CharField(source='display_role', read_only=True)

    def get_primary_role(self, obj):
        if not obj.primary_role:
            return None
        return {
            'id': obj.primary_role.id,
            'name': obj.primary_role.group.name,
            'priority': obj.primary_role.priority,
            'color': obj.primary_role.color_code
        }

    def get_roles(self, obj):
        return [
            {
                'id': role.id,
                'name': role.group.name,
                'priority': role.priority,
                'color': role.color_code
            }
            for role in obj.all_roles
        ]

    class Meta:
        model = CustomUser
        fields = ['id', 'email', 'primary_role', 'roles', 'role_display']

class UserUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomUser
        fields = [
            'first_name', 'last_name', 'phone_number', 'is_active'
        ]



class UserSignatureSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source='user.get_full_name', read_only=True)

    class Meta:
        model = UserSignature
        fields = [
            'id', 'user', 'user_name', 'signature_image', 'signature_data',
            'is_verified', 'verified_at', 'created_at'
        ]
        read_only_fields = ['id', 'created_at', 'is_verified', 'verified_at']

    def create(self, validated_data):
        # Auto-set user from request if not provided
        request = self.context.get('request')
        if request and hasattr(request, 'user') and 'user' not in validated_data:
            validated_data['user'] = request.user
        return super().create(validated_data)


class UserProfileSerializer(serializers.ModelSerializer):
    """Serializer for user's own profile"""
    full_name = serializers.CharField(source='get_full_name', read_only=True)
    signature = UserSignatureSerializer(read_only=True)

    # ── Role / RBAC fields ────────────────────────────────────────────────────
    primary_role = serializers.SerializerMethodField()
    roles = serializers.SerializerMethodField()
    permissions = serializers.SerializerMethodField()

    # ── Tenant / sync fields ──────────────────────────────────────────────────
    # These two fields are consumed by the mobile sync layer (roleBasedSync.ts /
    # newRecordDefaults) to stamp company_id and branch_id onto every new record.
    # Without them the auth store has no subdomain/current_branch, causing every
    # pushed record to arrive at the server with blank tenant fields.
    subdomain = serializers.SerializerMethodField()
    current_branch = serializers.SerializerMethodField()

    def get_subdomain(self, obj):
        """
        Return the tenant subdomain string used as company_id on synced records.

        Tries the most common patterns in order:
          1. obj.company.subdomain   — user has a FK to a Company/Tenant model
          2. obj.subdomain           — subdomain stored directly on CustomUser
          3. obj.tenant.subdomain    — user has a FK named 'tenant'

        If none match your schema, adjust the accessor below to match your model.
        Run `python manage.py shell -c "from accounts.models import CustomUser;
        u = CustomUser.objects.first(); print(dir(u))"` to inspect available
        attributes.
        """
        # Pattern 1: user.company.subdomain (most common multi-tenant setup)
        try:
            company = getattr(obj, 'company', None)
            if company is not None:
                return getattr(company, 'subdomain', None)
        except Exception:
            pass

        # Pattern 2: subdomain stored directly on CustomUser
        subdomain = getattr(obj, 'subdomain', None)
        if subdomain:
            return subdomain

        # Pattern 3: user.tenant.subdomain
        try:
            tenant = getattr(obj, 'tenant', None)
            if tenant is not None:
                return getattr(tenant, 'subdomain', None)
        except Exception:
            pass

        return None

    def get_current_branch(self, obj):
        """
        Return the user's active branch identifier (UUID string or slug).

        Tries the most common patterns in order:
          1. obj.current_branch_id   — FK field (Django appends _id automatically)
          2. obj.current_branch      — plain string / slug field on CustomUser
          3. obj.branch_id           — alternative FK name
          4. obj.branch.id           — related object with its own id

        Adjust to match your model if none of these apply.
        """
        # Pattern 1: current_branch is a FK — Django stores it as current_branch_id
        branch_id = getattr(obj, 'current_branch_id', None)
        if branch_id:
            return str(branch_id)

        # Pattern 2: plain string field
        current_branch = getattr(obj, 'current_branch', None)
        if current_branch and not hasattr(current_branch, 'pk'):
            # It's a plain value, not a related object
            return str(current_branch)

        # Pattern 3: alternative FK name
        alt_branch_id = getattr(obj, 'branch_id', None)
        if alt_branch_id:
            return str(alt_branch_id)

        # Pattern 4: related object — return its pk
        if current_branch and hasattr(current_branch, 'pk'):
            return str(current_branch.pk)

        return None

    def get_primary_role(self, obj):
        role = obj.effective_primary_role
        if not role:
            return None
        return {
            'id': role.id,
            'name': role.group.name,
            'priority': role.priority,
            'color': role.color_code,
        }

    def get_roles(self, obj):
        return [
            {
                'id': role.id,
                'name': role.group.name,
                'priority': role.priority,
                'color': role.color_code,
            }
            for role in obj.all_roles
        ]

    def get_permissions(self, obj):
        """
        Returns a flat list of permission codenames the user holds
        (via their role groups), e.g. ["can_view_reports", "can_export_data"].
        The mobile app can check membership in this list for RBAC gating.
        """
        # Collect all permissions from the user's role groups
        perms = set()
        for group in obj.groups.all():
            for perm in group.permissions.all():
                perms.add(perm.codename)
        # Also include any direct user-level permissions
        for perm in obj.user_permissions.all():
            perms.add(perm.codename)
        return sorted(perms)

    class Meta:
        model = CustomUser
        fields = [
            'id', 'email', 'username', 'first_name', 'last_name',
            'full_name', 'phone_number', 'date_joined', 'signature',
            # role / RBAC
            'primary_role', 'roles', 'permissions',
            # tenant / sync — required by mobile sync layer to stamp
            # company_id and branch_id on every locally-created record
            'subdomain', 'current_branch',
        ]
        read_only_fields = [
            'id', 'email', 'date_joined',
        ]


class UserListSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(source='get_full_name', read_only=True)

    class Meta:
        model = CustomUser
        fields = [
            'id', 'email', 'username', 'full_name',
            'is_active', 'date_joined'
        ]
        read_only_fields = fields


class RoleSerializer(serializers.ModelSerializer):
    name = serializers.CharField(source='group.name', read_only=True)

    class Meta:
        model = Role
        fields = ['id', 'name', 'description', 'color_code', 'priority', 'is_active', 'is_system_role']
        read_only_fields = fields


class APITokenSerializer(serializers.ModelSerializer):
    """Serializer for APIToken — token value only shown on creation."""

    is_expired = serializers.BooleanField(read_only=True)
    is_valid = serializers.BooleanField(read_only=True)

    class Meta:
        model = APIToken
        fields = [
            'id', 'name', 'token', 'token_type',
            'is_active', 'expires_at', 'last_used_at', 'last_used_ip',
            'created_at', 'is_expired', 'is_valid',
        ]
        read_only_fields = ['id', 'token', 'last_used_at', 'last_used_ip', 'created_at', 'is_expired', 'is_valid']
        extra_kwargs = {
            # Only expose the raw token value immediately after creation
            'token': {'write_only': False},
        }

    def to_representation(self, instance):
        data = super().to_representation(instance)
        # Hide the raw token in list/retrieve responses; only show it on creation
        request = self.context.get('request')
        if request and request.method != 'POST':
            data['token'] = f"{instance.token[:8]}{'*' * 24}"
        return data


class APITokenCreateSerializer(serializers.ModelSerializer):
    """Used only for creation — returns full token once."""

    class Meta:
        model = APIToken
        fields = ['id', 'name', 'token_type', 'expires_at', 'token', 'created_at']
        read_only_fields = ['id', 'token', 'created_at']

    def create(self, validated_data):
        request = self.context.get('request')
        if request and hasattr(request, 'user'):
            validated_data['user'] = request.user
        return super().create(validated_data)


class UserSessionSerializer(serializers.ModelSerializer):
    """Serializer for UserSession."""

    is_expired = serializers.BooleanField(read_only=True)
    session_duration = serializers.SerializerMethodField()

    class Meta:
        model = UserSession
        fields = [
            'id', 'session_key', 'ip_address', 'user_agent',
            'browser', 'os', 'device_type', 'location',
            'is_active', 'created_at', 'last_activity', 'expires_at',
            'is_expired', 'session_duration',
        ]
        read_only_fields = fields

    def get_session_duration(self, obj):
        if obj.last_activity and obj.created_at:
            delta = obj.last_activity - obj.created_at
            total_seconds = int(delta.total_seconds())
            hours, remainder = divmod(total_seconds, 3600)
            minutes, _ = divmod(remainder, 60)
            return f"{hours}h {minutes}m"
        return None