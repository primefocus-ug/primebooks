from rest_framework import serializers
from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.utils.translation import gettext_lazy as _
from .models import CustomUser, UserSignature



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
    full_name = serializers.CharField(source='get_full_name', read_only=True)

    class Meta:
        model = CustomUser
        fields = [
            'id', 'email', 'username', 'first_name', 'last_name',
            'full_name', 'user_type', 'phone_number', 'is_active',
            'is_staff', 'company_admin', 'is_device_operator',
            'date_joined', 'last_login_ip'
        ]
        read_only_fields = [
            'id', 'date_joined', 'last_login_ip', 'is_staff', 'company_admin'
        ]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        # Hide sensitive fields for non-admin users
        request = self.context.get('request')
        if request and hasattr(request, 'user'):
            user = request.user
            if not (user.is_superuser or user.company_admin or user == instance):
                data.pop('last_login_ip', None)
                data.pop('is_staff', None)
        return data


class UserUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomUser
        fields = [
            'first_name', 'last_name', 'phone_number', 'user_type', 'is_active'
        ]
    
    def validate_user_type(self, value):
        request = self.context.get('request')
        if request and hasattr(request, 'user'):
            user = request.user
            # Only company admins and superusers can change user types
            if not (user.is_superuser or user.company_admin):
                if self.instance and self.instance.user_type != value:
                    raise serializers.ValidationError(
                        "You don't have permission to change user types."
                    )
        return value


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
    
    class Meta:
        model = CustomUser
        fields = [
            'id', 'email', 'username', 'first_name', 'last_name',
            'full_name', 'user_type', 'phone_number',
            'date_joined', 'signature'
        ]
        read_only_fields = [
            'id', 'email', 'user_type', 'date_joined'
        ]


class UserListSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(source='get_full_name', read_only=True)
    
    class Meta:
        model = CustomUser
        fields = [
            'id', 'email', 'username', 'full_name', 'user_type',
            'is_active', 'date_joined'
        ]
        read_only_fields = fields
