from rest_framework import serializers
from django.contrib.auth.models import User
from .models import *
from cloudinary.utils import cloudinary_url

# Create your serializers here.
class UserSerializer(serializers.ModelSerializer):
    password2 = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = ['username', 'email', 'password', 'password2', 'first_name', 'last_name']

    def validate(self, data):
        # Check if the passwords match
        if data['password'] != data['password2']:
            raise serializers.ValidationError("Passwords must match.")
        return data

    def create(self, validated_data):
        # Remove 'password2' from the validated data before creating the user
        validated_data.pop('password2', None)
        return super(UserSerializer, self).create(validated_data)

class RegisterUserProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserProfile
        fields = ['user', 'contact', 'role', 'otp_code']

class UserDataSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id','email', 'first_name', 'last_name']

class UserProfileDataSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserProfile
        fields = ['contact','profile_picture', 'national_id_or_passport_number', 'national_id_or_passport_document']

class GetUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'first_name', 'last_name', 'email', 'is_active', 'date_joined', 'last_login']

class GetUserProfileSerializer(serializers.ModelSerializer):
    user = GetUserSerializer()  # Nest the UserSerializer here

    class Meta:
        model = UserProfile
        fields = ['id', 'user', 'contact', 'address', 'profile_picture', 'national_id_or_passport_number', 'national_id_or_passport_document']

class UpdateUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['username', 'first_name', 'last_name', 'email' ]

class UpdateUserProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserProfile
        fields = [
            'contact',
            'profile_picture',
            'national_id_or_passport_number',
            'national_id_or_passport_document',
        ]

class ItemImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ItemImage
        fields = ['id', 'image']

class WishlistSerializer(serializers.ModelSerializer):
    images = ItemImageSerializer(many=True, read_only=True)

    class Meta:
        model = Item
        fields = ['id', 'item_name', 'item_price', 'item_description', 'created_at', 'images']
  # Include fields relevant to your use case

class ReviewSerializer(serializers.ModelSerializer):
    class Meta:
        model = Review
        fields = ['id', 'reviewer', 'item', 'review', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']

class ReportAbuseSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReportAbuse
        fields = ['id', 'reporter', 'item', 'reason', 'description', 'status', 'created_at', 'updated_at']

class ContactSerializer(serializers.ModelSerializer):
    class Meta:
        model = Contact
        fields = '__all__'

class NewsLetterSubcribersSerializer(serializers.ModelSerializer):
    class Meta:
        model = NewsLetterSubcribers
        fields = '__all__'

class FAQSerializer(serializers.ModelSerializer):
    class Meta:
        model = FAQ
        fields = '__all__'

class ImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ItemImage
        fields = ['id', 'image']

class ItemSerializer(serializers.ModelSerializer):
    subcategory = serializers.CharField(source="item_subcategory.subcategory_name")
    category = serializers.CharField(source="item_subcategory.subcategory_category.category_name")
    images = ImageSerializer(many=True, read_only=True)

    class Meta:
        model = Item
        fields = [
            "id", "item_name", "item_price", "item_location", "item_negotiable",
            "item_status", "item_description", "subcategory", "category", "images",
            "created_at", "updated_at"
        ]
