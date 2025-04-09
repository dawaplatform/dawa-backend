from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes, parser_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.authtoken.serializers import AuthTokenSerializer
from django.contrib.auth.models import User
from .models import *
from .serializers import *
from django.contrib.auth import authenticate, login
from django.shortcuts import redirect, get_object_or_404
from knox.models import AuthToken
from knox.auth import TokenAuthentication
import json
from django.core.mail import EmailMessage
import random
from DawaProject import settings
from rest_framework.exceptions import AuthenticationFailed, ValidationError
from django.db.models import Q
from allauth.socialaccount.models import SocialAccount
from google.oauth2.id_token import verify_oauth2_token
from google.auth.transport.requests import Request
from cloudinary.utils import cloudinary_url
from rest_framework.parsers import MultiPartParser, FormParser
from django.utils.text import slugify
from collections import defaultdict
from django.contrib.auth.hashers import check_password
from rest_framework.pagination import LimitOffsetPagination
from django.contrib.postgres.search import TrigramSimilarity
import secrets

# Create your views here.
@api_view(['POST'])
def Register(request):
    if request.method == 'POST':
        user_data = {
            "username": request.data.get("email"),
            "email": request.data.get("email"),
            "password": request.data.get("password"),
            "password2": request.data.get("password2"),
            "first_name": request.data.get("firstname"),
            "last_name": request.data.get("lastname"),
        }

        user_serializer = UserSerializer(data=user_data)
        
        if user_serializer.is_valid():
            try:
                email = user_serializer.validated_data['email'].lower()
                username = user_serializer.validated_data['username'].lower()
                firstname = user_serializer.validated_data['first_name']
                lastname = user_serializer.validated_data['last_name']
                password = user_serializer.validated_data['password']
                password2 = user_serializer.validated_data['password2']

                if User.objects.filter(email=email).exists():
                    return Response({
                        "message": "Email Already Registered, Please Use A Different Email",
                        "errors": {"email": ["This email is already taken."]},
                        "status": status.HTTP_400_BAD_REQUEST
                    })

                if User.objects.filter(username=username).exists():
                    return Response({
                        "message": "Username Already Registered, Please Use A Different Username",
                        "errors": {"username": ["This username is already taken."]},
                        "status": status.HTTP_400_BAD_REQUEST
                    })

                if password != password2:
                    return Response({
                        "message": "Passwords Didn't Match",
                        "errors": {"password": ["Passwords do not match."]},
                        "status": status.HTTP_400_BAD_REQUEST
                    })

                # Generate a random 6-digit activation code
                otp_code = ''.join(random.choices('0123456789', k=6))

                user = User.objects.create_user(username, email, password)
                user.first_name = firstname.upper()
                user.last_name = lastname.upper()
                user.is_active = False
                user.save()

                # Create the profile for the user
                user_profile_data = {
                    "user": user.id,
                    "contact": request.data.get("contact"),
                    "role": request.data.get("role"),
                    "otp_code": otp_code,  # Save the activation code
                    "otp_created_at": timezone.now(),
                }
                user_profile_serializer = RegisterUserProfileSerializer(data=user_profile_data)

                if user_profile_serializer.is_valid():
                    contact = user_profile_serializer.validated_data['contact']
                    if UserProfile.objects.filter(contact=contact).exists():
                        user.delete()
                        return Response({
                            "message": "Contact/Telephone Number Already Registered, Please Use A Different Contact/Telephone Number",
                            "errors": {"contact": ["This contact is already registered."]},
                            "status": status.HTTP_400_BAD_REQUEST
                        })
                    
                    user_profile_serializer.save()
                else:
                    # Rollback the user creation if profile creation fails
                    user.delete()
                    return Response({
                        "message": "Failed to create profile.",
                        "errors": user_profile_serializer.errors,
                        "status": status.HTTP_400_BAD_REQUEST
                    })

                # Construct email messages
                welcome_message = (
                    f"Dear {firstname} {lastname},\n\n"
                    f"Welcome to Dawa!\n\n"
                    f"Please activate your account by entering your email ({email}) and the otp_code ({otp_code}).\n\n"
                    f"For any assistance, our support team is here to help.\n\n"
                    f"Thank you for choosing Dawa.\n\n"
                    f"Warm regards,\n"
                    "Dawa System Admin."
                )

                # Create EmailMessage instances
                welcome_email = EmailMessage(
                    subject="Activate Your Dawa User Account Now",
                    body=welcome_message,
                    from_email=settings.EMAIL_HOST_USER,
                    to=[email]
                )
                welcome_email.send(fail_silently=False)

                # Log the user registration
                ActivityLog.objects.create(
                    user=user,
                    action=f"New user registered: {firstname.upper()} {lastname.upper()}.",
                    ip_address = request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0] or request.META.get('REMOTE_ADDR'),
                    user_agent=request.META.get('HTTP_USER_AGENT')
                )

                return Response({
                    "message": f"User Account Created. OTP code sent to {email}.",
                    "status": status.HTTP_201_CREATED
                })
            except Exception as e:
                return Response({
                    "message": "Failed To Create User Account.",
                    "errors": {"exception": [str(e)]},
                    "status": status.HTTP_500_INTERNAL_SERVER_ERROR
                })
        
        # Return detailed validation errors
        return Response({
            "message": "Invalid data provided.",
            "errors": user_serializer.errors,
            "status": status.HTTP_400_BAD_REQUEST
        })

    return Response({
        "message": "Method not allowed",
        "status": status.HTTP_405_METHOD_NOT_ALLOWED
    })

@api_view(['POST'])
def GoogleLogin(request):
    try:
        google_token = request.data.get('google_token')
        role = request.data.get('role', 'Client')

        if not google_token:
            return Response({"message": "Google token is required.", "status": status.HTTP_400_BAD_REQUEST})

        # Verify Google token
        try:
            id_info = verify_oauth2_token(google_token, Request())
        except ValueError as e:
            return Response({"message": f"Invalid Google token: {str(e)}", "status": status.HTTP_400_BAD_REQUEST})

        if id_info['iss'] not in ['accounts.google.com', 'https://accounts.google.com']:
            return Response({"message": "Invalid Google token issuer.", "status": status.HTTP_400_BAD_REQUEST})

        if id_info['aud'] != settings.GOOGLE_CLIENT_ID:
            return Response({"message": "Invalid audience.", "status": status.HTTP_403_FORBIDDEN})

        # Check token expiration using timezone-aware UTC time
        if id_info['exp'] < timezone.now().timestamp():
            return Response({"message": "Token has expired.", "status": status.HTTP_403_FORBIDDEN})

        # Extract data from Google token
        email = id_info.get('email')
        first_name = id_info.get('given_name', '')
        last_name = id_info.get('family_name', '')
        google_profile_picture = id_info.get('picture', None)

        # Validate user role
        if role not in ['Client', 'Vendor']:
            return Response({"message": "Invalid user role. Must be 'Client' or 'Vendor'.", "status": status.HTTP_400_BAD_REQUEST})

        # Check if user exists or create new user
        user, created = User.objects.get_or_create(email=email, defaults={
            'username': email,
            'first_name': first_name,
            'last_name': last_name,
            'is_active': True
        })

        # Set a password-less login for new users
        if created:
            user.set_unusable_password()
            user.save()

        # Create or update user profile
        profile, _ = UserProfile.objects.get_or_create(user=user, defaults={
            'role': role,
            'profile_picture': google_profile_picture,
        })

        # Update profile picture if it exists
        if not profile.profile_picture and google_profile_picture:
            profile.profile_picture = google_profile_picture
            profile.save()

        # Send an email for newly created accounts
        if created:
            google_welcome_message = (
                f"Dear {first_name},\n\n"
                f"Welcome to Dawa!\n\n"
                f"Your account has been successfully created using Google Login. Welcome aboard!\n\n"
                f"For any assistance, our support team is here to help.\n\n"
                f"Thank you for choosing Dawa.\n\n"
                f"Warm regards,\n"
                "Dawa System Admin."
            )

            google_welcome_email = EmailMessage(
                subject="Welcome to Our Dawa Platform",
                body=google_welcome_message,
                from_email=settings.EMAIL_HOST_USER,
                to=[email]
            )
            google_welcome_email.send(fail_silently=False)

        # Generate Knox token
        _, token = AuthToken.objects.create(user, expiry=None)

        # Prepare response
        user_profile = getattr(user, 'userprofile', None)
        combined_data = {
            'user_data': {
                'id': user.pk,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'email': user.email,
                'role': getattr(user_profile, 'role', 'Client') if user_profile else 'Client',
                'profile_picture': getattr(user_profile, 'profile_picture', None) if user_profile else None,
            },
            'token': token
        }

        # Log the user registration and login
        action_message = (
            f"New google user registered and logged in: {first_name.upper()} {last_name.upper()}"
            if created else 
            f"Google user logged in: {first_name.upper()} {last_name.upper()}"
        )

        ActivityLog.objects.create(
            user=user,
            action=action_message,
            ip_address=request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0] or request.META.get('REMOTE_ADDR'),
            user_agent=request.META.get('HTTP_USER_AGENT')
        )

        # Return appropriate status code
        status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return Response({"message": "Google Login Successful", "user_data": combined_data, "status": status_code})

    except Exception as e:
        return Response({"message": f"Google Login Failed: {str(e)}", "status": status.HTTP_400_BAD_REQUEST})

@api_view(['POST'])
def ActivateAccount(request):
    if request.method == 'POST':
        email = request.data.get("email", "").lower()
        otp_code = request.data.get("otp_code")

        if not email or not otp_code:
            return Response({"message": "Email and otp_code are required.", "status": status.HTTP_400_BAD_REQUEST})

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return Response({"message": "User does not exist.", "status": status.HTTP_404_NOT_FOUND})

        try:
            profile = UserProfile.objects.get(user=user, otp_code=otp_code)
            
            # Activate the user
            user.is_active = True
            user.save()

            # Clear the OTP code after activation
            profile.otp_code = None
            profile.save()

            # Log account activation
            ActivityLog.objects.create(
                user=user,
                action=f"User activated account: {user.first_name.upper()} {user.last_name.upper()}",
                ip_address=request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0] or request.META.get('REMOTE_ADDR'),
                user_agent=request.META.get('HTTP_USER_AGENT')
            )

            return Response({"message": "Account activated successfully. Proceed to login.", "status": status.HTTP_200_OK})

        except UserProfile.DoesNotExist:
            return Response({"message": "Invalid otp_code.", "status": status.HTTP_400_BAD_REQUEST})

    return Response({"message": "Method not allowed", "status": status.HTTP_405_METHOD_NOT_ALLOWED})

@api_view(['POST'])
def Login(request):
    if request.method == 'POST':
        try:
            # Get email and password from request
            email = request.data.get('username')
            password = request.data.get('password')

            # Check if user exists
            try:
                user = User.objects.get(email=email)
            except User.DoesNotExist:
                return Response({"message": "Login failed. User does not exist.", "status": status.HTTP_404_NOT_FOUND})

            # Check if password is correct
            if not user.check_password(password):
                return Response({"message": "Invalid password.", "status": status.HTTP_401_UNAUTHORIZED})
            
            # Check if user is active
            if not user.is_active:
                return Response({"message": "Account is not activated. Please check your email or contact support for assistance.", "status": status.HTTP_403_FORBIDDEN})

            # Proceed with authentication
            serializer = AuthTokenSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            user = serializer.validated_data['user']

            # Update last_login field
            user.last_login = timezone.now()
            user.save()

            _, token = AuthToken.objects.create(user, expiry=None)

            # Get user profile details
            role = user.userprofile.role
            profile_picture = user.userprofile.profile_picture or None

            # Prepare response data
            combined_data = {
                'user_data': {
                    'id': user.pk,
                    'profile_picture': profile_picture,
                    'first_name': user.first_name,
                    'last_name': user.last_name,
                    'email': user.email,
                    'role': role
                },
                'token': token
            }

            # Log the login event
            ActivityLog.objects.create(
                user=user,
                action=f"User logged in: {user.first_name.upper()} {user.last_name.upper()}",
                ip_address=request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0] or request.META.get('REMOTE_ADDR'),
                user_agent=request.META.get('HTTP_USER_AGENT')
            )

            return Response({"message": "Logged In Successfully", "user_data": combined_data, "status": status.HTTP_202_ACCEPTED})
        
        except Exception as e:
            return Response({"message": f"Login failed: {str(e)}", "status": status.HTTP_400_BAD_REQUEST})

    return Response({"message": "Method not allowed", "status": status.HTTP_405_METHOD_NOT_ALLOWED})

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def GetUserProfile(request):
    try:
        # Fetch user profile
        user_profile = get_object_or_404(UserProfile, user=request.user)
        profile_serializer = GetUserProfileSerializer(user_profile)

        # Fetch all items for counting purposes before slicing
        all_items = Item.objects.filter(seller=request.user)

        # Fetch only the most recent 12 items
        latest_items = all_items.order_by('-created_at')[:6]

        # Get item counts from the full queryset (not the sliced one)
        total_items = all_items.count()
        available_items = all_items.filter(item_status="Available").count()
        sold_items = all_items.filter(item_status="Sold").count()

        item_data_list = []
        for item in latest_items:
            # Fetch related subcategory and category
            subcategory = item.item_subcategory
            category = subcategory.subcategory_category

            # Fetch images for the item
            images = [
                {"image_id": image.id, "image_url": image.image} for image in item.images.all()
            ]

            # Construct response for the item
            item_data = {
                "id": item.id,
                "name": item.item_name,
                "price": item.item_price,
                "location": item.item_location,
                "item_negotiable": item.item_negotiable,
                "status": item.item_status,
                "description": item.item_description,
                "subcategory": subcategory.subcategory_name,
                "category": category.category_name,
                "images": images,
                "created_at": item.created_at,
                "updated_at": item.updated_at,
            }

            # Append item data to the list
            item_data_list.append(item_data)

        # Combine profile and item data
        response_data = {
            "user_profile": profile_serializer.data,
            "items": {
                "total_items": total_items,
                "available_items": available_items,
                "sold_items": sold_items,
                "item_details": item_data_list,
            },
            "status": status.HTTP_200_OK,
        }
        return Response({'data': response_data, 'status': status.HTTP_200_OK})
    except Exception as e:
        return Response({"message": "An error occurred", "details": str(e), "status": status.HTTP_500_INTERNAL_SERVER_ERROR})

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def GetMyShopProfile(request):
    try:
        # Fetch user profile
        user_profile = get_object_or_404(UserProfile, user=request.user)
        profile_serializer = GetUserProfileSerializer(user_profile)

        # Fetch all items for counting purposes before slicing
        all_items = Item.objects.filter(seller=request.user)

        # Get item counts from the full queryset (not the sliced one)
        total_items = all_items.count()
        available_items = all_items.filter(item_status="Available").count()
        sold_items = all_items.filter(item_status="Sold").count()

        item_data_list = []
        for item in all_items:
            # Fetch related subcategory and category
            subcategory = item.item_subcategory
            category = subcategory.subcategory_category

            # Fetch images for the item
            images = [
                {"image_id": image.id, "image_url": image.image} for image in item.images.all()
            ]

            # Construct response for the item
            item_data = {
                "id": item.id,
                "name": item.item_name,
                "price": item.item_price,
                "location": item.item_location,
                "item_negotiable": item.item_negotiable,
                "status": item.item_status,
                "description": item.item_description,
                "subcategory": subcategory.subcategory_name,
                "category": category.category_name,
                "images": images,
                "created_at": item.created_at,
                "updated_at": item.updated_at,
            }

            # Append item data to the list
            item_data_list.append(item_data)

        # Combine profile and item data
        response_data = {
            "user_profile": profile_serializer.data,
            "items": {
                "total_items": total_items,
                "available_items": available_items,
                "sold_items": sold_items,
                "item_details": item_data_list,
            },
            "status": status.HTTP_200_OK,
        }
        return Response({'data': response_data, 'status': status.HTTP_200_OK})
    except Exception as e:
        return Response({"message": "An error occurred", "details": str(e), "status": status.HTTP_500_INTERNAL_SERVER_ERROR})

@api_view(['POST'])
def GetShopProfile(request):
    try:
        # Fetch user profile
        user = get_object_or_404(User, id=request.data.get('user_id'))
        user_profile = get_object_or_404(UserProfile, user=user)
        profile_serializer = GetUserProfileSerializer(user_profile)

        # Fetch all items for counting purposes before slicing
        all_items = Item.objects.filter(seller=user)

        # Get item counts from the full queryset (not the sliced one)
        total_items = all_items.count()
        available_items = all_items.filter(item_status="Available").count()
        sold_items = all_items.filter(item_status="Sold").count()

        item_data_list = []
        for item in all_items:
            # Fetch related subcategory and category
            subcategory = item.item_subcategory
            category = subcategory.subcategory_category

            # Fetch images for the item
            images = [
                {"image_id": image.id, "image_url": image.image} for image in item.images.all()
            ]

            # Construct response for the item
            item_data = {
                "id": item.id,
                "name": item.item_name,
                "price": item.item_price,
                "location": item.item_location,
                "item_negotiable": item.item_negotiable,
                "status": item.item_status,
                "description": item.item_description,
                "subcategory": subcategory.subcategory_name,
                "category": category.category_name,
                "images": images,
                "created_at": item.created_at,
                "updated_at": item.updated_at,
            }

            # Append item data to the list
            item_data_list.append(item_data)

        # Combine profile and item data
        response_data = {
            "user_profile": profile_serializer.data,
            "items": {
                "total_items": total_items,
                "available_items": available_items,
                "sold_items": sold_items,
                "item_details": item_data_list,
            },
            "status": status.HTTP_200_OK,
        }
        return Response({'data': response_data, 'status': status.HTTP_200_OK})
    except Exception as e:
        return Response({"message": "An error occurred", "details": str(e), "status": status.HTTP_500_INTERNAL_SERVER_ERROR})

@api_view(['PATCH'])
@permission_classes([IsAuthenticated])
def UpdateUserProfile(request):
    user = request.user
    try:
        profile = UserProfile.objects.get(user=user)
    except UserProfile.DoesNotExist:
        return Response({"message": "User profile does not exist.", "status": status.HTTP_404_NOT_FOUND})
    
    change_log = []  # Store changes for logging

    # Track user field changes
    user_fields = {
        "email": request.data.get("email"),
        "first_name": request.data.get("firstname"),
        "last_name": request.data.get("lastname"),
    }
    
    for field, new_value in user_fields.items():
        if new_value and getattr(user, field) != new_value:
            change_log.append(f"{field} changed from '{getattr(user, field)}' to '{new_value}'")
            setattr(user, field, new_value)

    # Handle email change separately (Deactivation & OTP)
    if 'email' in request.data:
        new_email = request.data['email'].lower()
        if new_email != user.email:
            # Deactivate account
            user.is_active = False

            # Generate new OTP code
            otp_code = ''.join(random.choices('0123456789', k=6))
            profile.otp_code = otp_code

            # Send reactivation email
            reactivation_message = (
                f"Dear {user.first_name} {user.last_name},\n\n"
                f"You have requested to change your email address to {new_email}.\n\n"
                f"To complete this process, please activate your account using this OTP: {otp_code}\n\n"
                f"If you did not request this change, please contact our support team immediately.\n\n"
                f"Best regards,\n\n"
                "Dawa System Admin."
            )

            reactivation_email = EmailMessage(
                subject="Reactivate Your Account",
                body=reactivation_message,
                from_email=settings.EMAIL_HOST_USER,
                to=[new_email]
            )
            reactivation_email.send(fail_silently=False)

            change_log.append(f"Email changed from '{user.email}' to '{new_email}'")
            user.email = new_email  # Update email field

            # Save user changes
            user.save()
            profile.save()

    # Track profile field changes
    profile_fields = {
        "contact": request.data.get("contact"),
        "address": request.data.get("address"),
        "profile_picture": request.FILES.get("profile_picture"),
        "national_id_or_passport_number": request.data.get("national_id_or_passport_number"),
        "national_id_or_passport_document": request.FILES.get("national_id_or_passport_document"),
    }

    for field, new_value in profile_fields.items():
        old_value = getattr(profile, field)
        if new_value and old_value != new_value:
            change_log.append(f"{field} changed from '{old_value}' to '{new_value}'")
            setattr(profile, field, new_value)

    # Save updated fields
    user.save()
    profile.save()

    # Log the changes
    if change_log:
        ActivityLog.objects.create(
            user=user,
            action=f"User profile updated: {', '.join(change_log)}",
            ip_address=request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0] or request.META.get('REMOTE_ADDR'),
            user_agent=request.META.get('HTTP_USER_AGENT')
        )

    return Response({"message": "User profile updated successfully.", "status": status.HTTP_200_OK})

@api_view(['POST'])
def ReActivateAccount(request):
    if request.method == 'POST':
        email = request.data.get("email").lower()
        otp_code = request.data.get("otp_code")

        if not email or not otp_code:
            return Response({"message": "Email and otp code are required.", "status":status.HTTP_400_BAD_REQUEST})

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return Response({"message": "User does not exist.", "status":status.HTTP_404_NOT_FOUND})

        try:
            profile = UserProfile.objects.get(user=user, otp_code=otp_code)
            if profile:
                # Reactivate the user
                user.is_active = True
                user.save()

                # Set the activation code to None
                profile.otp_code = None
                profile.save()

                # Log account activation
                ActivityLog.objects.create(
                    user=user,
                    action=f"User re-activated account: {user.first_name.upper()} {user.last_name.upper()}",
                    ip_address=request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0] or request.META.get('REMOTE_ADDR'),
                    user_agent=request.META.get('HTTP_USER_AGENT')
                )

                return Response({"message": "Account reactivated successfully. Proceed To Login", "status":status.HTTP_200_OK})
            else:
                return Response({"message": "Failed to reactivate the user account.", "status":status.HTTP_500_INTERNAL_SERVER_ERROR})
        except UserProfile.DoesNotExist:
            return Response({"message": "Invalid otp code.", "status":status.HTTP_400_BAD_REQUEST})
    return Response({"message": "Method not allowed", "status":status.HTTP_405_METHOD_NOT_ALLOWED})

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def ChangePassword(request):
    user = request.user
    old_password = request.data.get('old_password')
    new_password = request.data.get('new_password')
    confirm_password = request.data.get('confirm_password')

    # Validate required fields
    if not all([old_password, new_password, confirm_password]):
        return Response({"message": "All fields are required.", "status": status.HTTP_400_BAD_REQUEST})

    # Check if old password is correct
    if not check_password(old_password, user.password):
        return Response({"message": "Old password is incorrect.", "status": status.HTTP_400_BAD_REQUEST})

    # Ensure new password matches confirmation
    if new_password != confirm_password:
        return Response({"message": "New password and confirm password do not match.", "status": status.HTTP_400_BAD_REQUEST})

    # Enforce password length policy
    if len(new_password) < 8:
        return Response({"message": "Password must be at least 8 characters long.", "status": status.HTTP_400_BAD_REQUEST})

    # Update the user's password
    user.set_password(new_password)
    user.save()

    # Log password change event
    ActivityLog.objects.create(
        user=user,
        action="User changed password",
        ip_address=request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0] or request.META.get('REMOTE_ADDR'),
        user_agent=request.META.get('HTTP_USER_AGENT')
    )

    return Response({"message": "Password changed successfully. Please log in again.", "status": status.HTTP_200_OK})

@api_view(['POST'])
def ForgotPassword(request):
    email = request.data.get('email')

    if not email:
        return Response({"message": "Email is required.", "status": status.HTTP_400_BAD_REQUEST})

    # Check if user exists
    user = get_object_or_404(User, email=email)

    # Generate OTP and expiry
    otp_code = ''.join(secrets.choice('0123456789') for _ in range(6))
    otp_validity_minutes = 10  # Set OTP validity period

    # Save OTP and expiry to UserProfile
    user_profile = UserProfile.objects.get(user=user)
    user_profile.otp_code = otp_code
    user_profile.otp_created_at = timezone.now()
    user_profile.save()

    # Send OTP via email
    otp_message = (
        f"Dear {user.first_name} {user.last_name},\n\n"
        f"We received a request to reset your password for your Dawa account. "
        f"Please use the following One-Time PIN (OTP) to proceed with resetting your password:\n\n"
        f"OTP: {otp_code}\n\n"
        f"This OTP is valid for {otp_validity_minutes} minutes. If you did not request a password reset, "
        f"please ignore this email or contact our support team immediately at support@dawa.com.\n\n"
        f"Thank you for using Dawa.\n\n"
        f"Best regards,\n"
        f"Dawa Support Team\n"
    )

    otp_email = EmailMessage(
        subject="Your Dawa Password Reset OTP",
        body=otp_message,
        from_email=settings.EMAIL_HOST_USER,
        to=[email]
    )
    otp_email.send(fail_silently=False)

    # Log password reset request
    ActivityLog.objects.create(
        user=user,
        action="User requested password reset OTP",
        ip_address=request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0] or request.META.get('REMOTE_ADDR'),
        user_agent=request.META.get('HTTP_USER_AGENT')
    )

    # Generic response to avoid exposing whether an email exists
    return Response({"message": "If the email is associated with an account, a password reset OTP has been sent.", "status": status.HTTP_200_OK})

@api_view(['POST'])
def ResetPassword(request):
    email = request.data.get('email')
    otp = request.data.get('otp')
    new_password = request.data.get('new_password')
    confirm_password = request.data.get('confirm_password')

    if not all([email, otp, new_password, confirm_password]):
        return Response({"message": "All fields are required.", "status": status.HTTP_400_BAD_REQUEST})

    if new_password != confirm_password:
        return Response({"message": "Passwords do not match.", "status": status.HTTP_400_BAD_REQUEST})

    # Check if user exists
    user = get_object_or_404(User, email=email)

    # Validate OTP
    try:
        user_profile = UserProfile.objects.get(user=user)
    except UserProfile.DoesNotExist:
        return Response({"message": "User profile not found.", "status": status.HTTP_400_BAD_REQUEST})

    if not user_profile.otp_code or not user_profile.otp_created_at:
        return Response({"message": "No OTP found for this user.", "status": status.HTTP_400_BAD_REQUEST})

    otp_age = (timezone.now() - user_profile.otp_created_at).total_seconds()

    if otp != user_profile.otp_code:
        return Response({"message": "Invalid One-Time PIN.", "status": status.HTTP_403_FORBIDDEN})

    if otp_age > 600:  # OTP expires after 10 minutes
        return Response({"message": "One-Time PIN has expired.", "status": status.HTTP_403_FORBIDDEN})

    # Update password
    user.set_password(new_password)
    user.save()

    # Clear OTP after use
    user_profile.otp_code = None
    user_profile.otp_created_at = None
    user_profile.save()

    # Log password reset
    ActivityLog.objects.create(
        user=user,
        action="User successfully reset password",
        ip_address=request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0] or request.META.get('REMOTE_ADDR'),
        user_agent=request.META.get('HTTP_USER_AGENT')
    )

    return Response({"message": "Password reset successfully. Please log in with your new password.", "status": status.HTTP_200_OK})

@api_view(['POST'])
def ResendOTP(request):
    try:
        email = request.data.get('email')
        purpose = request.data.get('purpose')  # 'forgot_password', 'activate', or 'reactivate'

        if not email or not purpose:
            return Response({"message": "Email and purpose are required.", "status": status.HTTP_400_BAD_REQUEST})

        if purpose not in ['forgot_password', 'activate', 'reactivate']:
            return Response({"message": "Invalid purpose. Use 'forgot_password', 'activate', or 'reactivate'.", "status": status.HTTP_400_BAD_REQUEST})

        # Fetch the user and user profile
        user = get_object_or_404(User, email=email)
        user_profile = get_object_or_404(UserProfile, user=user)

        # Generate a new OTP
        otp_code = ''.join(random.choices('0123456789', k=6))
        otp_validity_minutes = 10  # OTP is valid for 10 minutes

        # Save OTP details
        user_profile.otp_code = otp_code
        user_profile.otp_created_at = timezone.now()
        user_profile.save()

        # Email message templates
        email_subjects = {
            'forgot_password': "Resend OTP: Your Dawa One-Time PIN (OTP) for Forgot Password",
            'activate': "Resend OTP: Your Dawa One-Time PIN (OTP) for Account Activation",
            'reactivate': "Resend OTP: Your Dawa One-Time PIN (OTP) for Account Re-Activation",
        }

        otp_message = (
            f"Hello {user.first_name} {user.last_name},\n\n"
            f"Your One-Time PIN (OTP) for {purpose.replace('_', ' ')} is:\n\n"
            f"OTP: {otp_code}\n\n"
            f"This OTP is valid for {otp_validity_minutes} minutes.\n\n"
            f"If you did not request this, please contact support at support@Dawa.com.\n\n"
            f"Best regards,\n"
            f"Dawa Support Team"
        )

        # Send email
        otp_email = EmailMessage(
            subject=email_subjects[purpose],
            body=otp_message,
            from_email=settings.EMAIL_HOST_USER,
            to=[email]
        )
        otp_email.send(fail_silently=False)

        # Log the OTP resend action
        ActivityLog.objects.create(
            user=user,
            action=f"Resent OTP for purpose: {purpose}",
            ip_address=request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0] or request.META.get('REMOTE_ADDR'),
            user_agent=request.META.get('HTTP_USER_AGENT')
        )

        return Response({"message": f"OTP for {purpose} resent successfully.", "status": status.HTTP_200_OK})

    except Exception as e:
        return Response({"message": f"Error processing request: {str(e)}", "status": status.HTTP_400_BAD_REQUEST})

#STOPPED HERE FOR ACTIVITY LOGS

@api_view(['GET'])
def GetCategoriesWithSubcategories(request):
    try:
        categories = Category.objects.all()
        result = []

        for category in categories:
            # Get the count of items in the category
            category_item_count = Item.objects.filter(item_subcategory__subcategory_category=category).count()

            subcategories = SubCategory.objects.filter(subcategory_category=category)
            subcategory_data = []

            for subcategory in subcategories:
                # Get the count of items in the subcategory
                subcategory_item_count = Item.objects.filter(item_subcategory=subcategory).count()

                subcategory_data.append({
                    'id': subcategory.id,
                    'subcategory_name': subcategory.subcategory_name,
                    'subcategory_item_count': subcategory_item_count
                })

            result.append({
                'id': category.id,
                'category_name': category.category_name,
                'category_item_count': category_item_count,
                'subcategories': subcategory_data
            })

        return Response({"data": result, "status": status.HTTP_200_OK})

    except Exception as e:
        return Response({"error": str(e), "status": status.HTTP_400_BAD_REQUEST})

@api_view(['POST'])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
def AddItem(request):
    data = request.data
    try:
        # Generate unique slug
        base_slug = slugify(data.get('item_name'))
        unique_slug = base_slug
        counter = 1
        while Item.objects.filter(slug=unique_slug).exists():
            unique_slug = f"{base_slug}-{counter}"
            counter += 1

        # Create the item
        item = Item.objects.create(
            seller=request.user,
            item_name=data.get('item_name'),
            item_price=data.get('item_price'),
            item_location=data.get('item_location'),
            item_negotiable=data.get('item_negotiable', False),
            slug=unique_slug,
            item_subcategory_id=data.get('item_subcategory_id'),
            item_status=data.get('item_status', 'Available'),
            item_description=data.get('item_description'),
        )

        # Process images
        images = request.FILES.getlist('images')
        if images:
            for image_file in images:
                ItemImage.objects.create(item=item, image=image_file)

        # Get the user's full name
        user_fullname = f"{request.user.first_name} {request.user.last_name}".strip()
        if not user_fullname:
            user_fullname = request.user.username  # Fallback to username if full name is missing

        # Log activity after the item is created
        ActivityLog.objects.create(
            user=request.user,
            action=f"Added new item: {item.item_name} by {user_fullname}",
            ip_address=request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0] or request.META.get('REMOTE_ADDR'),
            user_agent=request.META.get('HTTP_USER_AGENT')
        )

        return Response({"message": "Item and images added successfully.", "status": status.HTTP_201_CREATED})

    except UserProfile.DoesNotExist:
        return Response({"error": "User profile not found. Please complete your profile.", "status": status.HTTP_404_NOT_FOUND})
    except Exception as e:
        return Response({"error": str(e), "status": status.HTTP_400_BAD_REQUEST})

    
@api_view(['PATCH'])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
def UpdateItem(request):
    try:
        data = request.data

        # Fetch the item
        item = get_object_or_404(Item, id=data.get('item_id'))

        # Check if the logged-in user is the owner of the item
        if item.seller != request.user:
            return Response({"error": "You are not authorized to update this item.", "status": status.HTTP_403_FORBIDDEN})

        # Track changes
        updated_fields = []

        # Partial update: Update only the provided fields
        if 'item_name' in data and data.get('item_name') != item.item_name:
            item.item_name = data.get('item_name')
            updated_fields.append("name")

            # Update the slug if the item name changes
            base_slug = slugify(item.item_name)
            unique_slug = base_slug
            counter = 1
            while Item.objects.filter(slug=unique_slug).exclude(id=item.id).exists():
                unique_slug = f"{base_slug}-{counter}"
                counter += 1
            item.slug = unique_slug

        if 'item_price' in data and data.get('item_price') != item.item_price:
            item.item_price = data.get('item_price')
            updated_fields.append("price")

        if 'item_location' in data and data.get('item_location') != item.item_location:
            item.item_location = data.get('item_location')
            updated_fields.append("location")

        if 'item_negotiable' in data and str(data.get('item_negotiable')) != str(item.item_negotiable):
            item.item_negotiable = data.get('item_negotiable')
            updated_fields.append("negotiable status")

        if 'item_status' in data and data.get('item_status') != item.item_status:
            item.item_status = data.get('item_status')
            updated_fields.append("status")

        if 'item_description' in data and data.get('item_description') != item.item_description:
            item.item_description = data.get('item_description')
            updated_fields.append("description")

        if 'item_subcategory_id' in data and data.get('item_subcategory_id') != item.item_subcategory_id:
            item.item_subcategory_id = data.get('item_subcategory_id')
            updated_fields.append("subcategory")

        # Save updated item
        item.save()

        # Process new images if provided
        images = request.FILES.getlist('images')
        if images:
            for image_file in images:
                ItemImage.objects.create(item=item, image=image_file)
            updated_fields.append("images")

        # Construct log message
        user_fullname = f"{request.user.first_name} {request.user.last_name}".strip() or request.user.username
        updated_fields_str = ", ".join(updated_fields) if updated_fields else "no changes"

        # Log activity
        ActivityLog.objects.create(
            user=request.user,
            action=f"Updated item: {item.item_name} ({updated_fields_str}) by {user_fullname}",
            ip_address=request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0] or request.META.get('REMOTE_ADDR'),
            user_agent=request.META.get('HTTP_USER_AGENT')
        )

        return Response({"message": "Item updated successfully.", "status": status.HTTP_200_OK})

    except Item.DoesNotExist:
        return Response({"error": "Item not found.", "status": status.HTTP_404_NOT_FOUND})
    except Exception as e:
        return Response({"error": str(e), "status": status.HTTP_400_BAD_REQUEST})

@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def DeleteItemImage(request):
    try:
        # Get the image ID from the request data
        image_id = request.data.get('image_id')
        if not image_id:
            return Response({"error": "Image ID is required.", "status": status.HTTP_400_BAD_REQUEST})

        # Fetch the item image
        item_image = get_object_or_404(ItemImage, id=image_id)

        # Check if the logged-in user is the seller of the item associated with the image
        if item_image.item.seller != request.user:
            return Response({"error": "You are not authorized to delete this image. Only the seller can delete images.", "status": status.HTTP_403_FORBIDDEN})

        # Store item name before deletion
        item_name = item_image.item.item_name  

        # Delete the item image
        item_image.delete()

        # Get user full name or username for logging
        user_fullname = f"{request.user.first_name} {request.user.last_name}".strip() or request.user.username

        # Log the deletion action
        ActivityLog.objects.create(
            user=request.user,
            action=f"Deleted image from {item_name} by {user_fullname}",
            ip_address=request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0] or request.META.get('REMOTE_ADDR'),
            user_agent=request.META.get('HTTP_USER_AGENT')
        )

        return Response({"message": "Image deleted successfully.", "status": status.HTTP_200_OK})

    except Exception as e:
        return Response({"error": str(e), "status": status.HTTP_400_BAD_REQUEST})

class CustomPagination(LimitOffsetPagination):
    default_limit = 16  # Number of items per page
    max_limit = 80  # Prevent very large fetches

@api_view(['POST'])
def GetItems(request):
    try:
        category_id = request.data.get('category_id', None)
        subcategory_id = request.data.get('subcategory_id', None)

        # Base queryset optimized with select_related & prefetch_related
        items = Item.objects.filter(item_status='Available').select_related(
            'item_subcategory__subcategory_category'
        ).prefetch_related('images')

        if category_id:
            items = items.filter(item_subcategory__subcategory_category__id=category_id)

        if subcategory_id:
            items = items.filter(item_subcategory__id=subcategory_id)

        # Apply pagination
        paginator = CustomPagination()
        paginated_items = paginator.paginate_queryset(items, request)

        # Serialize paginated items
        serialized_items = ItemSerializer(paginated_items, many=True).data

        return paginator.get_paginated_response({"data": serialized_items})
    
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

@api_view(['POST'])
def GetItemDetails(request):
    try:
        # Fetch the specific item
        item_id = request.data.get('item_id')
        item = get_object_or_404(Item, id=item_id)

        # Fetch related subcategory and category
        subcategory = item.item_subcategory
        category = subcategory.subcategory_category

        # Fetch seller details
        seller_profile = UserProfile.objects.filter(user=item.seller).first()
        seller_details = {
            "seller_id": item.seller.id,
            "seller_name": item.seller.get_full_name(),
            "seller_profile_picture": seller_profile.profile_picture if seller_profile else None,
            "seller_email": item.seller.email,
            "seller_contact": seller_profile.contact if seller_profile else None,
            "seller_address": seller_profile.address if seller_profile else None,
        }

        # Fetch reviews for the item, sorted by creation date (descending)
        reviews = Review.objects.filter(item=item).order_by('-created_at')
        reviews_data = [
            {
                "reviewer_name": review.reviewer.get_full_name(),
                "reviewer_profile_picture": UserProfile.objects.filter(user=review.reviewer).first().profile_picture if UserProfile.objects.filter(user=review.reviewer).exists() else None,
                "review": review.review,
                "created_at": review.created_at,
            }
            for review in reviews
        ]

        # Fetch images for the item and include both ID and URL
        images = [
            {"image_id": image.id, "image_url": image.image} for image in item.images.all()
        ]

        # Fetch similar items
        similar_items = Item.objects.filter(
            item_subcategory=subcategory
        ).exclude(id=item.id)[:5]  # Exclude the current item and limit to 5 items

        if not similar_items.exists():
            # If no items found in the same subcategory, fetch from the same category
            similar_items = Item.objects.filter(
                item_subcategory__subcategory_category=category
            ).exclude(id=item.id)[:5]

        similar_items_data = [
            {
                "id": similar_item.id,
                "name": similar_item.item_name,
                "price": similar_item.item_price,
                "location": similar_item.item_location,
                "item_negotiable": similar_item.item_negotiable,
                "status": similar_item.item_status,
                "description": similar_item.item_description,
                "subcategory": similar_item.item_subcategory.subcategory_name,
                "category": category.category_name,
                "image": similar_item.images.first().image if similar_item.images.exists() else None,
                "created_at": similar_item.created_at,
                "updated_at": similar_item.updated_at,
            }
            for similar_item in similar_items
        ]

        # Construct response for the item
        item_data = {
            "id": item.id,
            "name": item.item_name,
            "price": item.item_price,
            "location": item.item_location,
            "item_negotiable": item.item_negotiable,
            "status": item.item_status,
            "description": item.item_description,
            "subcategory": subcategory.subcategory_name,
            "category": category.category_name,
            "images": images,  # List of image dictionaries with ID and URL
            "created_at": item.created_at,
            "updated_at": item.updated_at,
            "seller": seller_details,  # Include seller details
            "reviews": reviews_data,  # Include all reviews for the item
            "similar_items": similar_items_data,  # Include similar items
        }

        return Response({"data": item_data, "status": status.HTTP_200_OK})
    except Exception as e:
        return Response({"error": str(e), "status": status.HTTP_400_BAD_REQUEST})

@api_view(['GET'])
def GetItemsPromoted(request):
    try:
        # Fetch promoted items for the authenticated seller
        items = Item.objects.filter(item_promoted=True)
        item_data_list = []  # Initialize an empty list to hold item details

        for item in items:
            # Fetch related subcategory and category
            subcategory = item.item_subcategory
            category = subcategory.subcategory_category

            # Fetch images for the item and include both ID and URL
            images = [
                {"image_id": image.id, "image_url": image.image} for image in item.images.all()
            ]

            # Construct response for the item
            item_data = {
                "id": item.id,
                "name": item.item_name,
                "price": item.item_price,
                "location": item.item_location,
                "item_negotiable": item.item_negotiable,
                "status": item.item_status,
                "description": item.item_description,
                "subcategory": subcategory.subcategory_name,
                "category": category.category_name,
                "images": images,  # List of image dictionaries with ID and URL
                "created_at": item.created_at,
                "updated_at": item.updated_at,
            }

            # Append item data to the list
            item_data_list.append(item_data)

        # Return the list of promoted items
        return Response({"data": item_data_list, "status": status.HTTP_200_OK})
    except Exception as e:
        return Response({"error": str(e), "status": status.HTTP_400_BAD_REQUEST})

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def WishUnWish(request):
    try:
        # Ensure `item_id` is provided in the request
        item_id = request.data.get('item_id')
        if not item_id:
            return Response({"error": "Item ID is required.", "status": status.HTTP_400_BAD_REQUEST})

        # Check if the item exists in the database
        item = get_object_or_404(Item, id=item_id)

        # Get user full name or fallback to username
        user_fullname = f"{request.user.first_name} {request.user.last_name}".strip() or request.user.username

        # Check if the item is already in the wishlist
        wishlist_entry = Wishlist.objects.filter(user=request.user, item=item).first()

        if wishlist_entry:
            if wishlist_entry.is_wished:
                # Unwish the item
                wishlist_entry.is_wished = False
                wishlist_entry.save()
                
                # Log the removal from wishlist
                ActivityLog.objects.create(
                    user=request.user,
                    action=f"{user_fullname} removed {item.item_name} from wishlist",
                    ip_address=request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0] or request.META.get('REMOTE_ADDR'),
                    user_agent=request.META.get('HTTP_USER_AGENT')
                )

                return Response({"message": "Item removed from wishlist.", "status": status.HTTP_200_OK})
            else:
                # Wish the item again
                wishlist_entry.is_wished = True
                wishlist_entry.save()

                # Log the addition to wishlist
                ActivityLog.objects.create(
                    user=request.user,
                    action=f"{user_fullname} added {item.item_name} to wishlist",
                    ip_address=request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0] or request.META.get('REMOTE_ADDR'),
                    user_agent=request.META.get('HTTP_USER_AGENT')
                )

                return Response({"message": "Item added to wishlist.", "status": status.HTTP_200_OK})
        else:
            # Create a new wishlist entry
            Wishlist.objects.create(user=request.user, item=item, is_wished=True)

            # Log new wishlist creation
            ActivityLog.objects.create(
                user=request.user,
                action=f"{user_fullname} created a wishlist and added {item.item_name}",
                ip_address=request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0] or request.META.get('REMOTE_ADDR'),
                user_agent=request.META.get('HTTP_USER_AGENT')
            )

            return Response({"message": "Item added to wishlist.", "status": status.HTTP_201_CREATED})

    except Exception as e:
        return Response({"error": str(e), "status": status.HTTP_400_BAD_REQUEST})

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def GetUserWishlist(request):
    try:
        # Retrieve all items in the wishlist for the authenticated user where is_wished is True
        wishlist_entries = Wishlist.objects.filter(user=request.user, is_wished=True).select_related('item')
        
        # Serialize the items to return as a response
        items = [entry.item for entry in wishlist_entries]
        serializer = WishlistSerializer(items, many=True)

        return Response({"wishlist": serializer.data, "status": status.HTTP_200_OK})
    except Exception as e:
        return Response({"error": str(e), "status": status.HTTP_400_BAD_REQUEST})

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def SendMessage(request):
    user=request.user
    data = request.data
    try:
        # Validate receiver exists
        receiver = get_object_or_404(User, id=data.get('receiver_id'))

        # Validate item exists
        item = get_object_or_404(Item, id=data.get('item_id'))

        # Ensure the sender and receiver are distinct users
        if user == receiver:
            return Response({"error": "You cannot send a message to yourself.", "status": status.HTTP_400_BAD_REQUEST})

        # Check if a chat already exists between these two users for the same item
        chat = Chat.objects.filter(
            item=item,
            participants=user
        ).filter(participants=receiver).distinct().first()

        if not chat:
            # Create a new chat if it does not exist
            chat = Chat.objects.create(item=item)
            chat.participants.add(user, receiver)

        # Create the message
        message_instance = Message.objects.create(
            chat=chat,
            sender=user,
            receiver=receiver,
            message=data.get('message')
        )

        # Send email notification to receiver
        email_subject = f"New Message About '{item.item_name}'"
        email_body = (
            f"Hello {receiver.first_name},\n\n"
            f"You have received a new message from {user.first_name} regarding the item '{item.item_name}'.\n\n"
            f"Message: {message_instance.message}\n\n"
            f"Please log in to your account to reply."
        )

        email_to_receiver = EmailMessage(
            subject=email_subject,
            body=email_body,
            from_email=settings.EMAIL_HOST_USER,  # Configured sender email
            to=[receiver.email],
        )
        email_to_receiver.send(fail_silently=False)

        # Log the message activity
        sender_fullname = f"{user.first_name} {user.last_name}".strip() or user.username
        receiver_fullname = f"{receiver.first_name} {receiver.last_name}".strip() or receiver.username

        ActivityLog.objects.create(
            user=user,
            action=f"{sender_fullname} sent a message to {receiver_fullname} about '{item.item_name}'",
            ip_address=request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0] or request.META.get('REMOTE_ADDR'),
            user_agent=request.META.get('HTTP_USER_AGENT')
        )

        return Response({"message": "Message sent successfully.", "status": status.HTTP_201_CREATED})

    except Exception as e:
        return Response({"error": str(e), "status": status.HTTP_400_BAD_REQUEST})

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def GetChatsWithMessages(request):
    try:
        # Fetch chats for the authenticated user
        chats = Chat.objects.filter(participants=request.user)

        # Prepare response data
        chat_data_list = []

        for chat in chats:
            # Fetch messages only between the two participants of the chat
            messages = chat.messages.filter(
                sender__in=chat.participants.all(),
                receiver__in=chat.participants.all()
            ).order_by('created_at')

            # Serialize messages
            message_data = [
                {
                    "id": message.id,
                    "senderId": message.sender.id,
                    "receiverId": message.receiver.id,
                    "message": message.message,
                    "created_at": message.created_at,
                    "read": message.message_read,
                }
                for message in messages
            ]

            # Fetch participants with full name and profile picture
            participants_data = []
            for user in chat.participants.all():
                user_profile = UserProfile.objects.filter(user=user).first()
                participants_data.append({
                    "id": user.id,
                    "full_name": f"{user.first_name} {user.last_name}",
                    "profile_picture": user_profile.profile_picture if user_profile else None
                })

            # Add chat data
            chat_data = {
                "id": chat.id,
                "subject": {
                    "item_id": chat.item.id if chat.item else None,
                    "item_name": chat.item.item_name if chat.item else None,
                },
                "participants": participants_data,
                "messages": message_data,
            }
            chat_data_list.append(chat_data)

        return Response({'data': chat_data_list, 'status': status.HTTP_200_OK})
    except Exception as e:
        return Response({"message": "An error occurred", "details": str(e), "status": status.HTTP_500_INTERNAL_SERVER_ERROR})

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def SubmitReview(request):
    # Ensure the user is authenticated
    user = request.user

    # Extract request data
    item_id = request.data.get('item_id')
    review_text = request.data.get('review')

    # Validate required fields
    if not item_id or not review_text:
        return Response({'error': 'Item ID and review text are required.', 'status': status.HTTP_400_BAD_REQUEST})

    # Check if the item exists
    item = get_object_or_404(Item, id=item_id)

    # Check if the user has already reviewed the item
    if Review.objects.filter(reviewer=user, item=item).exists():
        return Response({'error': 'You have already reviewed this item.', 'status': status.HTTP_400_BAD_REQUEST})

    # Serialize and save the review
    review_data = {
        'reviewer': user.id,
        'item': item.id,
        'review': review_text,
    }
    serializer = ReviewSerializer(data=review_data)
    if serializer.is_valid():
        serializer.save()

        # Prepare user and item details for the log
        user_fullname = f"{user.first_name} {user.last_name}".strip() or user.username
        item_name = item.item_name

        # Log the review activity
        ActivityLog.objects.create(
            user=user,
            action=f"{user_fullname} submitted a review for '{item_name}'",
            ip_address=request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0] or request.META.get('REMOTE_ADDR'),
            user_agent=request.META.get('HTTP_USER_AGENT')
        )

        return Response({'message': 'Review submitted successfully.', 'status': status.HTTP_201_CREATED})

    return Response({'error': serializer.errors, 'status': status.HTTP_400_BAD_REQUEST})

@api_view(['POST'])
@permission_classes([IsAuthenticated])  # Ensure the user is authenticated
def MakeReportOfAbuse(request):
    # Get the logged-in user
    user = request.user

    # Extract request data
    item_id = request.data.get('item_id')
    reason = request.data.get('reason')
    description = request.data.get('description')

    # Validate required fields
    if not item_id or not reason or not description:
        return Response(
            {"error": "item_id, reason, and description are required."},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        # Fetch the item using the provided item_id
        item = get_object_or_404(Item, id=item_id)

        # Create the abuse report
        report = ReportAbuse.objects.create(
            reporter=user,
            item=item,
            reason=reason,
            description=description,
            status='Pending'  # Default status is 'Pending'
        )

        # Serialize the report details before returning as response
        serializer = ReportAbuseSerializer(report)

        # Send an email to the reporter
        email_subject_reporter = 'Abuse Report Submitted Successfully'
        email_body_reporter = (
            f'Hello {user.username},\n\n'
            f'Your abuse report for the item "{item.item_name}" has been successfully submitted and is under review.'
        )
        email_to_reporter = EmailMessage(
            subject=email_subject_reporter,
            body=email_body_reporter,
            from_email=settings.EMAIL_HOST_USER,
            to=[user.email],
        )
        email_to_reporter.send(fail_silently=False)

        # Send an email to the admin (if ADMIN_EMAIL is set in settings)
        admin_email = getattr(settings, "ADMIN_EMAIL", None)
        if admin_email:
            email_subject_admin = 'New Abuse Report Submitted'
            email_body_admin = (
                f'A new abuse report has been submitted for the item "{item.item_name}" by {user.username}.\n\n'
                f'Reason: {reason}\nDescription: {description}'
            )
            email_to_admin = EmailMessage(
                subject=email_subject_admin,
                body=email_body_admin,
                from_email=settings.EMAIL_HOST_USER,
                to=[admin_email],
            )
            email_to_admin.send(fail_silently=False)

        # Log the abuse report action
        user_fullname = f"{user.first_name} {user.last_name}".strip() or user.username
        ActivityLog.objects.create(
            user=user,
            action=f"{user_fullname} reported abuse for '{item.item_name}' - Reason: {reason}",
            ip_address=request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0] or request.META.get('REMOTE_ADDR'),
            user_agent=request.META.get('HTTP_USER_AGENT')
        )

        # Return a successful response
        return Response(
            {"message": "Abuse report submitted successfully", "status": status.HTTP_201_CREATED}
        )

    except Exception as e:
        return Response({"error": str(e), "status": status.HTTP_400_BAD_REQUEST})

@api_view(['POST'])
def ContactUs(request):
    serializer = ContactSerializer(data=request.data)
    
    if serializer.is_valid():
        contact = serializer.save()

        # Email details
        subject = f"New Contact Us Message: {contact.subject}"
        
        # Email to Admin
        admin_message = f"""
        You have received a new contact request:
        
        Name: {contact.name}
        Email: {contact.email}
        Phone: {contact.phone_number}
        Subject: {contact.subject}
        Message:
        {contact.message}
        """
        admin_email = EmailMessage(
            subject=subject,
            body=admin_message,
            from_email=settings.EMAIL_HOST_USER,
            to=[settings.ADMIN_EMAIL]  # Send to the admin's email
        )
        admin_email.send(fail_silently=False)

        # Auto-reply to sender
        sender_message = f"""
        Hi {contact.name},

        Thank you for reaching out to us. We have received your message and will get back to you as soon as possible.

        Subject: {contact.subject}
        Message:
        {contact.message}

        Regards,
        Dawa Team
        """
        sender_email = EmailMessage(
            subject=subject,
            body=sender_message,
            from_email=settings.EMAIL_HOST_USER,
            to=[contact.email]  # Send to the admin's email
        )
        sender_email.send(fail_silently=False)

        # Determine the user for logging
        user = request.user if request.user.is_authenticated else None

        # Log the submission
        ActivityLog.objects.create(
            user=user or None,  # Set to None if anonymous
            action=f"Contact Us submission from {contact.name} ({contact.email})",
            ip_address=request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0] or request.META.get('REMOTE_ADDR'),
            user_agent=request.META.get('HTTP_USER_AGENT')
        )

        return Response({"message": "Your message has been sent successfully!", "status":status.HTTP_201_CREATED})
    
    return Response({"message":serializer.errors, "status":status.HTTP_400_BAD_REQUEST})

@api_view(['POST'])
def AddNewsLetterSubcriber(request):
    serializer = NewsLetterSubcribersSerializer(data=request.data)
    
    if serializer.is_valid():
        visitor = serializer.save()

        # Send confirmation email
        subject = "Newsletter Subscription Confirmation"
        message = f"""
        Hi {visitor.name},

        Thank you for subscribing to Dawa's newsletter! 🎉  
        You'll now receive updates, news, and exclusive content directly in your inbox.

        If you ever wish to unsubscribe, please contact us.

        Best regards,  
        Dawa Team
        """
        subscriber_email = EmailMessage(
            subject=subject,
            body=message,
            from_email=settings.EMAIL_HOST_USER,
            to=[visitor.email]
        )
        subscriber_email.send(fail_silently=False)

        # Determine the user for logging
        user = request.user if request.user.is_authenticated else None

        # Log the subscription
        ActivityLog.objects.create(
            user=user,  # Set to None if anonymous
            action=f"Newsletter subscription by {visitor.email}",
            ip_address=request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0] or request.META.get('REMOTE_ADDR'),
            user_agent=request.META.get('HTTP_USER_AGENT')
        )

        return Response({"message": "Thank you for subscribing!", "status": status.HTTP_201_CREATED})
    
    return Response({"message": serializer.errors, "status": status.HTTP_400_BAD_REQUEST})

@api_view(['GET'])
def GetFAQs(request):
    faqs = FAQ.objects.all()
    serializer = FAQSerializer(faqs, many=True)
    return Response({"data": serializer.data, "status": status.HTTP_200_OK})

@api_view(['POST'])
def SearchItems(request):
    # Get the search query from the request data
    query = request.data.get('search_query', '').strip().lower()
    search_query = f"Search Results For '{query}'." if query else "Showing all items."

    if query:
        # Tokenize the query to search for individual words
        words = query.split()

        # Use Q objects for flexible matching
        q_objects = Q()
        for word in words:
            q_objects |= Q(item_name__icontains=word)
            q_objects |= Q(item_location__icontains=word)
            q_objects |= Q(item_subcategory__subcategory_name__icontains=word)
            q_objects |= Q(item_status__icontains=word)
            q_objects |= Q(item_description__icontains=word)

        # Use TrigramSimilarity for approximate matching
        items = Item.objects.annotate(
            similarity_name=TrigramSimilarity('item_name', query),
            similarity_desc=TrigramSimilarity('item_description', query)
        ).filter(q_objects | Q(similarity_name__gt=0.3) | Q(similarity_desc__gt=0.3)).distinct()
    else:
        items = Item.objects.all()

    # Prepare the item data
    item_data_list = []
    for item in items:
        subcategory = getattr(item.item_subcategory, "subcategory_name", "Unknown Subcategory")
        category = getattr(item.item_subcategory.subcategory_category, "category_name", "Unknown Category") if item.item_subcategory else "Unknown Category"
        images = [{"image_id": image.id, "image_url": image.image} for image in item.images.all()]

        item_data_list.append({
            "id": item.id,
            "name": item.item_name,
            "price": item.item_price,
            "location": item.item_location,
            "item_negotiable": item.item_negotiable,
            "status": item.item_status,
            "description": item.item_description,
            "subcategory": subcategory,
            "category": category,
            "images": images,
            "created_at": item.created_at,
            "updated_at": item.updated_at,
        })

    # Determine the user for logging
    user = request.user if request.user.is_authenticated else None

    # Log the search activity
    ActivityLog.objects.create(
        user=user,  # Set to None if anonymous
        action=f"Search query: {query}",
        ip_address=request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0] or request.META.get('REMOTE_ADDR'),
        user_agent=request.META.get('HTTP_USER_AGENT')
    )

    return Response({"search_query": search_query, "data": item_data_list, "status": status.HTTP_200_OK})





