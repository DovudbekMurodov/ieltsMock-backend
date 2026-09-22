from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = (
            "id",
            "email",
            "first_name",
            "last_name",
            "target_band",
            "exam_date",
            "country",
            "timezone",
            "locale",
            "is_staff",
            "date_joined",
        )
        read_only_fields = ("id", "email", "is_staff", "date_joined")


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, validators=[validate_password])

    class Meta:
        model = User
        fields = ("email", "password", "first_name", "last_name", "target_band")

    def create(self, validated_data):
        password = validated_data.pop("password")
        return User.objects.create_user(password=password, **validated_data)


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        user = authenticate(
            request=self.context.get("request"),
            username=attrs["email"],
            password=attrs["password"],
        )
        # One message for both a wrong password and an unknown address, so the
        # endpoint cannot be used to enumerate registered emails.
        if user is None:
            raise serializers.ValidationError("Incorrect email or password.")
        if not user.is_active:
            raise serializers.ValidationError("This account is disabled.")
        attrs["user"] = user
        return attrs


class AuthSessionSerializer(serializers.Serializer):
    """What a successful register / login / refresh returns.

    The refresh token is deliberately absent: it travels in an httpOnly cookie
    and never reaches JavaScript.
    """

    access = serializers.CharField()
    # camelCase on purpose: this is the JSON key the SPA reads.
    expiresIn = serializers.IntegerField()
    user = UserSerializer()


class DetailSerializer(serializers.Serializer):
    detail = serializers.CharField()


class TokenValiditySerializer(serializers.Serializer):
    valid = serializers.BooleanField()


class RevokedCountSerializer(serializers.Serializer):
    revoked = serializers.IntegerField()


class VerifyRequestSerializer(serializers.Serializer):
    token = serializers.CharField()
