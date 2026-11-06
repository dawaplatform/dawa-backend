from django.utils import timezone
from django.core.cache import cache
from feed.service import version as feed_version
from datetime import timedelta
from rest_framework import status
from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes, parser_classes, throttle_classes
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
from .services import check_message_safety, moderate_message
from .image_validation import prepare_listing_images, RejectedImage
from django.utils.text import slugify
from collections import defaultdict
from django.contrib.auth.hashers import check_password
from rest_framework.pagination import LimitOffsetPagination
from django.contrib.postgres.search import TrigramSimilarity
import secrets
from django.db.models import Count, F, Prefetch, Sum, Window
from django.db.models.functions import Coalesce, RowNumber, TruncDate
import logging

from .throttles import AuthEndpointThrottle

# Get the logger
logger = logging.getLogger(__name__)

# Allowed self-service registration roles (never allow Admin via public register)
ALLOWED_REGISTRATION_ROLES = ('Client', 'Vendor')

# Create your views here.
@api_view(['POST'])
@throttle_classes([AuthEndpointThrottle])
def Register(request):
    if request.method == 'POST':
        logger.info("Register endpoint hit with POST method.")

        user_data = {
            "username": request.data.get("email"),
            "email": request.data.get("email"),
            "password": request.data.get("password"),
            "password2": request.data.get("password2"),
            "first_name": request.data.get("firstname"),
            "last_name": request.data.get("lastname"),
        }

        logger.debug(f"User data received: {user_data}")

        user_serializer = UserSerializer(data=user_data)
        
        if user_serializer.is_valid():
            try:
                logger.info("User serializer is valid.")
                email = user_serializer.validated_data['email'].lower()
                username = user_serializer.validated_data['username'].lower()
                firstname = user_serializer.validated_data['first_name']
                lastname = user_serializer.validated_data['last_name']
                password = user_serializer.validated_data['password']
                password2 = user_serializer.validated_data['password2']

                logger.debug(f"Validated data - Email: {email}, Username: {username}")

                if User.objects.filter(email=email).exists():
                    logger.warning(f"Email already registered: {email}")
                    return Response({
                        "message": "Email Already Registered, Please Use A Different Email",
                        "errors": {"email": ["This email is already taken."]},
                    }, status=status.HTTP_400_BAD_REQUEST)

                if User.objects.filter(username=username).exists():
                    logger.warning(f"Username already registered: {username}")
                    return Response({
                        "message": "Username Already Registered, Please Use A Different Username",
                        "errors": {"username": ["This username is already taken."]},
                    }, status=status.HTTP_400_BAD_REQUEST)

                if password != password2:
                    logger.warning("Passwords do not match.")
                    return Response({
                        "message": "Passwords Didn't Match",
                        "errors": {"password": ["Passwords do not match."]},
                    }, status=status.HTTP_400_BAD_REQUEST)

                otp_code = ''.join(random.choices('0123456789', k=6))
                logger.info(f"Generated OTP code: {otp_code}")

                user = User.objects.create_user(username, email, password)
                user.first_name = firstname.upper()
                user.last_name = lastname.upper()
                user.is_active = False
                user.save()
                logger.info(f"User created: {username}")

                req_role = request.data.get("role") or "Client"
                if req_role not in ALLOWED_REGISTRATION_ROLES:
                    req_role = "Client"

                user_profile_data = {
                    "user": user.id,
                    "contact": request.data.get("contact"),
                    "role": req_role,
                    "otp_code": otp_code,
                    "otp_created_at": timezone.now(),
                }

                logger.debug(f"User profile data: {user_profile_data}")

                user_profile_serializer = RegisterUserProfileSerializer(data=user_profile_data)

                if user_profile_serializer.is_valid():
                    contact = user_profile_serializer.validated_data['contact']
                    if UserProfile.objects.filter(contact=contact).exists():
                        logger.warning(f"Contact already registered: {contact}")
                        user.delete()
                        return Response({
                            "message": "Contact/Telephone Number Already Registered, Please Use A Different Contact/Telephone Number",
                            "errors": {"contact": ["This contact is already registered."]},
                        }, status=status.HTTP_400_BAD_REQUEST)

                    user_profile_serializer.save()
                    logger.info(f"UserProfile created for user: {username}")
                else:
                    logger.error(f"UserProfile serializer errors: {user_profile_serializer.errors}")
                    user.delete()
                    return Response({
                        "message": "Failed to create profile.",
                        "errors": user_profile_serializer.errors,
                    }, status=status.HTTP_400_BAD_REQUEST)

                welcome_email = EmailMessage(
                    subject="Activate Your Dawa User Account Now",
                    body=(
                        f"Dear {firstname} {lastname},\n\n"
                        f"Welcome to Dawa!\n\n"
                        f"Please activate your account by entering your email ({email}) and the otp_code ({otp_code}).\n\n"
                        f"For any assistance, our support team is here to help.\n\n"
                        f"Thank you for choosing Dawa.\n\n"
                        f"Warm regards,\n"
                        "Dawa System Admin."
                    ),
                    from_email=settings.EMAIL_HOST_USER,
                    to=[email]
                )
                welcome_email.send(fail_silently=False)
                logger.info(f"Activation email sent to: {email}")

                ActivityLog.objects.create(
                    user=user,
                    action=f"New user registered: {firstname.upper()} {lastname.upper()}.",
                    ip_address=request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0] or request.META.get('REMOTE_ADDR'),
                    user_agent=request.META.get('HTTP_USER_AGENT')
                )
                logger.info(f"Activity log created for user: {username}")

                return Response({
                    "message": f"User Account Created. OTP code sent to {email}.",
                }, status=status.HTTP_201_CREATED)
            except Exception as e:
                logger.exception("An unexpected error occurred during registration.")
                return Response({
                    "message": "Failed To Create User Account.",
                    "errors": {"exception": [str(e)]},
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        logger.error(f"User serializer invalid: {user_serializer.errors}")
        return Response({
            "message": "Invalid data provided.",
            "errors": user_serializer.errors,
        }, status=status.HTTP_400_BAD_REQUEST)

    logger.warning("Register endpoint hit with non-POST method.")
    return Response({
        "message": "Method not allowed",
    }, status=status.HTTP_405_METHOD_NOT_ALLOWED)


@api_view(['POST'])
@throttle_classes([AuthEndpointThrottle])
def GoogleLogin(request):
    try:
        google_token = request.data.get('google_token')
        role = request.data.get('role') or request.data.get('user_role') or 'Client'
        if role not in ALLOWED_REGISTRATION_ROLES:
            role = 'Client'

        if not google_token:
            return Response({"message": "Google token is required."}, status=status.HTTP_400_BAD_REQUEST)

        # Verify Google token
        try:
            id_info = verify_oauth2_token(google_token, Request())
        except ValueError as e:
            return Response({"message": f"Invalid Google token: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)

        if id_info['iss'] not in ['accounts.google.com', 'https://accounts.google.com']:
            return Response({"message": "Invalid Google token issuer."}, status=status.HTTP_400_BAD_REQUEST)

        if id_info['aud'] != settings.GOOGLE_CLIENT_ID:
            return Response({"message": "Invalid audience."}, status=status.HTTP_403_FORBIDDEN)

        # Check token expiration using timezone-aware UTC time
        if id_info['exp'] < timezone.now().timestamp():
            return Response({"message": "Token has expired."}, status=status.HTTP_403_FORBIDDEN)

        # Extract data from Google token
        email = id_info.get('email')
        first_name = id_info.get('given_name', '')
        last_name = id_info.get('family_name', '')
        google_profile_picture = id_info.get('picture', None)
        email_verified = id_info.get('email_verified', False)

        if not email:
            return Response({"message": "Google account email was not provided."}, status=status.HTTP_400_BAD_REQUEST)
        if not email_verified:
            return Response({"message": "Google account email is not verified."}, status=status.HTTP_403_FORBIDDEN)

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
        return Response({"message": "Google Login Successful", "user_data": combined_data}, status=status_code)

    except Exception:
        logger.exception("Google login failed unexpectedly.")
        return Response({"message": "Google Login Failed. Please try again."}, status=status.HTTP_400_BAD_REQUEST)

@api_view(['POST'])
@throttle_classes([AuthEndpointThrottle])
def ActivateAccount(request):
    if request.method == 'POST':
        email = request.data.get("email", "").lower()
        otp_code = request.data.get("otp_code")

        if not email or not otp_code:
            return Response({"message": "Email and otp_code are required."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return Response({"message": "User does not exist."}, status=status.HTTP_404_NOT_FOUND)

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

            return Response({"message": "Account activated successfully. Proceed to login."}, status=status.HTTP_200_OK)

        except UserProfile.DoesNotExist:
            return Response({"message": "Invalid otp_code."}, status=status.HTTP_400_BAD_REQUEST)

    return Response({"message": "Method not allowed"}, status=status.HTTP_405_METHOD_NOT_ALLOWED)

@api_view(['POST'])
@throttle_classes([AuthEndpointThrottle])
def Login(request):
    if request.method == 'POST':
        try:
            # Get email and password from request
            email = (request.data.get('username') or '').strip().lower()
            password = request.data.get('password')

            if not email or not password:
                return Response({"message": "Username/email and password are required."}, status=status.HTTP_400_BAD_REQUEST)

            # Check if user exists
            try:
                user = User.objects.get(email=email)
            except User.DoesNotExist:
                return Response({"message": "Login failed. User does not exist."}, status=status.HTTP_404_NOT_FOUND)

            # Check if password is correct
            if not user.check_password(password):
                if user.has_usable_password() is False:
                    return Response(
                        {"message": "This account uses Google sign-in. Please continue with Google."},
                        status=status.HTTP_401_UNAUTHORIZED
                    )
                return Response({"message": "Invalid password."}, status=status.HTTP_401_UNAUTHORIZED)

            # Check if user is active
            if not user.is_active:
                return Response({"message": "Account is not activated. Please check your email or contact support for assistance."}, status=status.HTTP_403_FORBIDDEN)

            # Proceed with authentication
            serializer = AuthTokenSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            user = serializer.validated_data['user']

            # Update last_login field
            user.last_login = timezone.now()
            user.save()

            _, token = AuthToken.objects.create(user, expiry=None)

            # Get user profile details (self-heal if missing)
            user_profile, _ = UserProfile.objects.get_or_create(user=user, defaults={"role": "Client"})
            role = user_profile.role
            profile_picture = user_profile.profile_picture or None

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

            return Response({"message": "Logged In Successfully", "user_data": combined_data}, status=status.HTTP_200_OK)

        except Exception:
            logger.exception("Login failed unexpectedly.")
            return Response({"message": "Login failed. Please try again."}, status=status.HTTP_400_BAD_REQUEST)

    return Response({"message": "Method not allowed"}, status=status.HTTP_405_METHOD_NOT_ALLOWED)

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
            }
        return Response({'data': response_data}, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({"message": "An error occurred", "details": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['POST'])
def GetMyShopProfile(request):
    """
    Returns the shop profile and items for a given user_id (seller).
    Only the shop owner (authenticated user whose id matches user_id) can access all items.
    If the user_id does not match the authenticated user, return 403 Forbidden.
    Expects: { "user_id": <int> } in POST body.
    """
    try:
        # Ensure user_id is provided in the request data
        seller_id = request.data.get('user_id')
        if not seller_id:
            return Response(
                {"message": "user_id is required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Check if the requesting user is the shop owner
        if not request.user.is_authenticated or int(seller_id) != request.user.id:
            return Response(
                {"message": "You are not authorized to access this shop profile."},
                status=status.HTTP_403_FORBIDDEN
            )

        # Fetch the seller user and profile
        seller = get_object_or_404(User, id=seller_id)
        user_profile = get_object_or_404(UserProfile, user=seller)
        profile_serializer = GetUserProfileSerializer(user_profile)

        # Only the owner can access this endpoint, so show all items
        all_items = Item.objects.filter(seller_id=seller_id)

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
                "approval_status": item.approval_status,
                "rejection_reason": item.rejection_reason,
                # Owner-only: expose the auto-moderation notes so the seller can
                # see the friendly reason and improvement tips in their shop.
                "metadata": item.metadata,
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
        }
        return Response({'data': response_data}, status=status.HTTP_200_OK)
    except Exception as e:
        # If the user is not authenticated, DRF will return 401 automatically.
        # For other errors, return 500.
        return Response(
            {"message": "An error occurred", "details": str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

@api_view(['POST'])
def GetShopProfile(request):
    try:
        # Fetch user profile
        user = get_object_or_404(User, id=request.data.get('user_id'))
        user_profile = get_object_or_404(UserProfile, user=user)
        profile_serializer = GetUserProfileSerializer(user_profile)

        # For public shop profile, only show approved items
        all_items = Item.objects.filter(seller=user, approval_status='Approved')

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
                # Public shop list is already filtered to Approved; include for consistent client UX
                "approval_status": item.approval_status,
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
        }
        return Response({'data': response_data}, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({"message": "An error occurred", "details": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['PATCH'])
@permission_classes([IsAuthenticated])
def UpdateUserProfile(request):
    user = request.user
    try:
        profile = UserProfile.objects.get(user=user)
    except UserProfile.DoesNotExist:
        return Response({"message": "User profile does not exist."}, status=status.HTTP_404_NOT_FOUND)
    
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

    return Response({"message": "User profile updated successfully."}, status=status.HTTP_200_OK)

@api_view(['POST'])
def ReActivateAccount(request):
    if request.method == 'POST':
        email = request.data.get("email").lower()
        otp_code = request.data.get("otp_code")

        if not email or not otp_code:
            return Response({"message": "Email and otp code are required."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return Response({"message": "User does not exist."}, status=status.HTTP_404_NOT_FOUND)

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

                return Response({"message": "Account reactivated successfully. Proceed To Login"}, status=status.HTTP_200_OK)
            else:
                return Response({"message": "Failed to reactivate the user account."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except UserProfile.DoesNotExist:
            return Response({"message": "Invalid otp code."}, status=status.HTTP_400_BAD_REQUEST)
    return Response({"message": "Method not allowed"}, status=status.HTTP_405_METHOD_NOT_ALLOWED)

@api_view(['POST'])
@throttle_classes([AuthEndpointThrottle])
@permission_classes([IsAuthenticated])
def ChangePassword(request):
    user = request.user
    old_password = request.data.get('old_password')
    new_password = request.data.get('new_password')
    confirm_password = request.data.get('confirm_password')

    # Validate required fields
    if not all([old_password, new_password, confirm_password]):
        return Response({"message": "All fields are required."}, status=status.HTTP_400_BAD_REQUEST)

    # Check if old password is correct
    if not check_password(old_password, user.password):
        return Response({"message": "Old password is incorrect."}, status=status.HTTP_400_BAD_REQUEST)

    # Ensure new password matches confirmation
    if new_password != confirm_password:
        return Response({"message": "New password and confirm password do not match."}, status=status.HTTP_400_BAD_REQUEST)

    # Enforce password length policy
    if len(new_password) < 8:
        return Response({"message": "Password must be at least 8 characters long."}, status=status.HTTP_400_BAD_REQUEST)

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

    return Response({"message": "Password changed successfully. Please log in again."}, status=status.HTTP_200_OK)

@api_view(['POST'])
@throttle_classes([AuthEndpointThrottle])
def ForgotPassword(request):
    email = (request.data.get('email') or '').strip().lower()

    if not email:
        return Response({"message": "Email is required."}, status=status.HTTP_400_BAD_REQUEST)

    user = User.objects.filter(email=email).first()
    user_profile = UserProfile.objects.filter(user=user).first() if user else None

    if user and user_profile:
        # Generate OTP and expiry
        otp_code = ''.join(secrets.choice('0123456789') for _ in range(6))
        otp_validity_minutes = 10  # Set OTP validity period

        # Save OTP and expiry to UserProfile
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
    return Response({"message": "If the email is associated with an account, a password reset OTP has been sent."}, status=status.HTTP_200_OK)

@api_view(['POST'])
@throttle_classes([AuthEndpointThrottle])
def ResetPassword(request):
    email = request.data.get('email')
    otp = request.data.get('otp')
    new_password = request.data.get('new_password')
    confirm_password = request.data.get('confirm_password')

    if not all([email, otp, new_password, confirm_password]):
        return Response({"message": "All fields are required."}, status=status.HTTP_400_BAD_REQUEST)

    if new_password != confirm_password:
        return Response({"message": "Passwords do not match."}, status=status.HTTP_400_BAD_REQUEST)

    # Check if user exists
    user = get_object_or_404(User, email=email)

    # Validate OTP
    try:
        user_profile = UserProfile.objects.get(user=user)
    except UserProfile.DoesNotExist:
        return Response({"message": "User profile not found."}, status=status.HTTP_400_BAD_REQUEST)

    if not user_profile.otp_code or not user_profile.otp_created_at:
        return Response({"message": "No OTP found for this user."}, status=status.HTTP_400_BAD_REQUEST)

    otp_age = (timezone.now() - user_profile.otp_created_at).total_seconds()

    if otp != user_profile.otp_code:
        return Response({"message": "Invalid One-Time PIN."}, status=status.HTTP_403_FORBIDDEN)

    if otp_age > 600:  # OTP expires after 10 minutes
        return Response({"message": "One-Time PIN has expired."}, status=status.HTTP_403_FORBIDDEN)

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

    return Response({"message": "Password reset successfully. Please log in with your new password."}, status=status.HTTP_200_OK)

@api_view(['POST'])
@throttle_classes([AuthEndpointThrottle])
def ResendOTP(request):
    try:
        email = (request.data.get('email') or '').strip().lower()
        purpose = request.data.get('purpose')  # 'forgot_password', 'activate', or 'reactivate'

        if not email or not purpose:
            return Response({"message": "Email and purpose are required."}, status=status.HTTP_400_BAD_REQUEST)

        if purpose not in ['forgot_password', 'activate', 'reactivate']:
            return Response({"message": "Invalid purpose. Use 'forgot_password', 'activate', or 'reactivate'."}, status=status.HTTP_400_BAD_REQUEST)

        # Fetch the user and user profile (do not reveal if account exists)
        user = User.objects.filter(email=email).first()
        user_profile = UserProfile.objects.filter(user=user).first() if user else None

        if not user or not user_profile:
            return Response({"message": f"OTP for {purpose} resent successfully."}, status=status.HTTP_200_OK)

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

        return Response({"message": f"OTP for {purpose} resent successfully."}, status=status.HTTP_200_OK)

    except Exception:
        logger.exception("Resend OTP failed unexpectedly.")
        return Response({"message": "Error processing request."}, status=status.HTTP_400_BAD_REQUEST)

#STOPPED HERE FOR ACTIVITY LOGS

COVERS_PER_SUBCATEGORY = 3
COVERS_PER_CATEGORY = 8


def rejected_images_response(rejected: list[RejectedImage]):
    names = "; ".join(f"{r.name}: {r.reason}" for r in rejected)
    return Response(
        {
            "error": "Some photos were rejected",
            "message": names,
            "failed_images": [{"name": r.name, "reason": r.reason} for r in rejected],
        },
        status=status.HTTP_400_BAD_REQUEST,
    )

@api_view(['GET'])
def GetCategoriesWithSubcategories(request):
    try:
        # Counts and covers only change when listings change; the feed bumps this version on item save.
        cache_key = f'categories:v{feed_version()}'
        payload = cache.get(cache_key)
        if payload is not None:
            response = Response(payload)
            response['Cache-Control'] = 'public, max-age=60'
            return response

        approved_item_filter = Q(item__approval_status='Approved')
        subcategories = (
            SubCategory.objects
            .annotate(subcategory_item_count=Count('item', filter=approved_item_filter, distinct=True))
            .order_by('subcategory_name')
        )
        categories = (
            Category.objects
            .annotate(
                category_item_count=Count(
                    'subcategory__item',
                    filter=Q(subcategory__item__approval_status='Approved'),
                    distinct=True,
                )
            )
            .prefetch_related(
                Prefetch('subcategory_set', queryset=subcategories, to_attr='prefetched_subcategories')
            )
            .order_by('category_name')
        )

        # Fallback icons: a few recent photos per subcategory, interleaved so a category's
        # list cycles through different subcategories (clients rotate through it).
        sub_field = 'item__item_subcategory_id'
        cat_field = 'item__item_subcategory__subcategory_category_id'
        ranked_images = (
            ItemImage.objects
            .filter(item__approval_status='Approved', image__isnull=False)
            .exclude(image='')
            .annotate(
                rn=Window(
                    RowNumber(),
                    partition_by=F(sub_field),
                    order_by=[F('item__created_at').desc(nulls_last=True), F('id').asc()],
                )
            )
            .filter(rn__lte=COVERS_PER_SUBCATEGORY)
            .order_by(cat_field, sub_field, 'rn')
            .values_list(cat_field, sub_field, 'image')
        )
        by_sub = defaultdict(list)
        subs_by_cat = defaultdict(list)
        for cat_id, sub_id, url in ranked_images:
            if sub_id not in by_sub:
                subs_by_cat[cat_id].append(sub_id)
            by_sub[sub_id].append(url)
        category_covers = {}
        for cat_id, sub_ids in subs_by_cat.items():
            lists = [by_sub[s] for s in sub_ids]
            category_covers[cat_id] = [
                lst[i] for i in range(COVERS_PER_SUBCATEGORY) for lst in lists if i < len(lst)
            ][:COVERS_PER_CATEGORY]

        result = [
            {
                'id': category.id,
                'category_name': category.category_name,
                'category_item_count': category.category_item_count,
                'image_url': category.image_url,
                'cover_image_url': (category_covers.get(category.id) or [None])[0],
                'cover_image_urls': category_covers.get(category.id, []),
                'subcategories': [
                    {
                        'id': subcategory.id,
                        'subcategory_name': subcategory.subcategory_name,
                        'subcategory_item_count': subcategory.subcategory_item_count,
                        'metadata': subcategory.metadata,
                        'image_url': subcategory.image_url,
                        'cover_image_url': (by_sub.get(subcategory.id) or [None])[0],
                        'cover_image_urls': by_sub.get(subcategory.id, []),
                    }
                    for subcategory in category.prefetched_subcategories
                ],
            }
            for category in categories
        ]

        payload = {"data": result, "status": status.HTTP_200_OK}
        cache.set(cache_key, payload, 60)
        response = Response(payload)
        response['Cache-Control'] = 'public, max-age=60'
        return response

    except Exception as e:
        return Response({"error": str(e), "status": status.HTTP_400_BAD_REQUEST})

@api_view(['POST'])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
def AddItem(request):
    data = request.data
    try:
        # Validate required fields
        required_fields = ['item_name', 'item_price', 'item_location', 'item_subcategory_id', 'item_description']
        missing_fields = [field for field in required_fields if not data.get(field)]
        
        if missing_fields:
            return Response({
                "error": "Missing required fields",
                "missing_fields": missing_fields,
                "message": f"Please provide the following required fields: {', '.join(missing_fields)}",
                "status": status.HTTP_400_BAD_REQUEST
            })
            
        # Validate price is a positive number
        try:
            price = float(data.get('item_price'))
            if price <= 0:
                return Response({
                    "error": "Invalid price",
                    "message": "Price must be a positive number",
                    "status": status.HTTP_400_BAD_REQUEST
                })
        except (ValueError, TypeError):
            return Response({
                "error": "Invalid price format",
                "message": "Price must be a valid number",
                "status": status.HTTP_400_BAD_REQUEST
            })
            
        # Validate subcategory exists
        try:
            subcategory = SubCategory.objects.get(id=data.get('item_subcategory_id'))
        except SubCategory.DoesNotExist:
            return Response({
                "error": "Invalid subcategory",
                "message": "The specified subcategory does not exist",
                "status": status.HTTP_400_BAD_REQUEST
            })

        # Reject bad photos before creating anything, so a failed post leaves no half-made listing.
        prepared_images, rejected_images = prepare_listing_images(request.FILES.getlist('images'))
        if rejected_images:
            return rejected_images_response(rejected_images)

        # Handle metadata (optional field)
        metadata = data.get('metadata', None)
        # If you want to ensure it's a dict, try to parse JSON if it's a string
        import json
        if metadata:
            if isinstance(metadata, str):
                try:
                    metadata = json.loads(metadata)
                except Exception:
                    # If not valid JSON, just store as string
                    pass

        # Generate unique slug
        base_slug = slugify(data.get('item_name'))
        unique_slug = base_slug
        counter = 1
        while Item.objects.filter(slug=unique_slug).exists():
            unique_slug = f"{base_slug}-{counter}"
            counter += 1

        # Create the item, now with metadata
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
            metadata=metadata if metadata else None,
        )

        # Process images
        if not prepared_images:
            # Item created successfully but no images were provided
            user_fullname = f"{request.user.first_name} {request.user.last_name}".strip() or request.user.username
            
            ActivityLog.objects.create(
                user=request.user,
                action=f"Added new item without images: {item.item_name} by {user_fullname}",
                ip_address=request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0] or request.META.get('REMOTE_ADDR'),
                user_agent=request.META.get('HTTP_USER_AGENT')
            )
            
            return Response({
                "message": "Item created successfully, but no images were provided. Adding images is recommended.",
                "item_id": item.id,
                "status": status.HTTP_201_CREATED
            })
        
        failed_images = []
        successful_images = 0

        for image_file in prepared_images:
            try:
                ItemImage.objects.create(item=item, image=image_file)
                successful_images += 1
            except Exception as img_error:
                failed_images.append({
                    "name": image_file.name,
                    "reason": f"Error processing image: {str(img_error)}"
                })

        # Get the user's full name
        user_fullname = f"{request.user.first_name} {request.user.last_name}".strip() or request.user.username

        # Log activity after the item is created
        ActivityLog.objects.create(
            user=request.user,
            action=f"Added new item: {item.item_name} by {user_fullname} with {successful_images} images",
            ip_address=request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0] or request.META.get('REMOTE_ADDR'),
            user_agent=request.META.get('HTTP_USER_AGENT')
        )

        # Prepare response with details about uploaded images
        response_data = {
            "message": "Item added successfully.",
            "item_id": item.id,
            "images_uploaded": successful_images,
            "status": status.HTTP_201_CREATED
        }
        
        if failed_images:
            response_data["failed_images"] = failed_images
            response_data["message"] = f"Item added with {successful_images} image(s). {len(failed_images)} image(s) failed to upload."
        
        return Response(response_data)

    except UserProfile.DoesNotExist:
        return Response({
            "error": "User profile not found",
            "message": "Please complete your profile before posting items for sale.",
            "status": status.HTTP_404_NOT_FOUND
        })
    except Exception as e:
        # If the item was created but images failed, make sure to delete the item
        try:
            if 'item' in locals():
                item.delete()
        except:
            pass
            
        return Response({
            "error": "Failed to create item",
            "message": f"An error occurred: {str(e)}",
            "details": str(e),
            "status": status.HTTP_400_BAD_REQUEST
        })

    
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

        # Validate new photos up front so a rejected photo doesn't leave a half-applied edit.
        new_images, rejected_images = prepare_listing_images(request.FILES.getlist('images'))
        if rejected_images:
            return rejected_images_response(rejected_images)

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
            allowed_statuses = {choice[0] for choice in Item.STATUS_CHOICES}
            if data.get('item_status') not in allowed_statuses:
                return Response({
                    "error": "Invalid item_status.",
                    "allowed_statuses": sorted(allowed_statuses),
                    "status": status.HTTP_400_BAD_REQUEST,
                }, status=status.HTTP_400_BAD_REQUEST)
            item.item_status = data.get('item_status')
            updated_fields.append("status")

        if 'item_description' in data and data.get('item_description') != item.item_description:
            item.item_description = data.get('item_description')
            updated_fields.append("description")

        if 'item_subcategory_id' in data and data.get('item_subcategory_id') != item.item_subcategory_id:
            item.item_subcategory_id = data.get('item_subcategory_id')
            updated_fields.append("subcategory")

        # Content-relevant edits on a Rejected listing => resubmit for auto review.
        # Also re-arm the pipeline on a Pending listing that already reached a
        # terminal moderation state (needs_review / failed) so the seller's fix
        # is actually re-checked instead of parking behind stale metadata.
        _CONTENT_FIELDS = {"name", "description", "subcategory", "images"}
        content_touched = bool(_CONTENT_FIELDS.intersection(updated_fields)) or bool(new_images)
        md = dict(item.metadata) if isinstance(item.metadata, dict) else {}
        stale_moderation = md.get("moderation_state") in {"rejected", "failed", "needs_review"} or md.get("needs_review") is True
        if content_touched and (item.approval_status == "Rejected" or stale_moderation):
            item.approval_status = "Pending"
            item.rejection_reason = None
            for key in (
                "needs_review",
                "moderation_state",
                "moderation_reason",
                "moderation_error",
                "moderation_scores",
                "moderation_decided_at",
            ):
                md.pop(key, None)
            item.metadata = md or None
            updated_fields.append("resubmitted for review")

        # Save updated item
        item.save()

        # Process new images if provided
        if new_images:
            for image_file in new_images:
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
        items = Item.objects.filter(item_status='Available', approval_status='Approved').select_related(
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
        item = get_object_or_404(Item, id=item_id, approval_status='Approved')
        if not (request.user.is_authenticated and request.user.id == item.seller_id):
            # update() skips post_save, so views don't invalidate the feed cache.
            Item.objects.filter(pk=item.pk).update(views_count=Coalesce(F('views_count'), 0) + 1)

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
            item_subcategory=subcategory, approval_status='Approved'
        ).exclude(id=item.id)[:5]

        if not similar_items.exists():
            similar_items = Item.objects.filter(
                item_subcategory__subcategory_category=category, approval_status='Approved'
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
                "metadata": similar_item.metadata if hasattr(similar_item, 'metadata') else None,
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
            "metadata": item.metadata if hasattr(item, 'metadata') else None,  # Add metadata field
        }

        return Response({"data": item_data, "status": status.HTTP_200_OK})
    except Exception as e:
        return Response({"error": str(e), "status": status.HTTP_400_BAD_REQUEST})

@api_view(['GET'])
def GetItemsPromoted(request):
    try:
        # Fetch promoted items for the authenticated seller
        items = Item.objects.filter(item_promoted=True, approval_status='Approved')
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
        item = get_object_or_404(Item, id=item_id, approval_status='Approved')

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
        items = [entry.item for entry in wishlist_entries if entry.item.approval_status == 'Approved']
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

        # Layered moderation: local prescreen (instant) + Gemini AI check.
        # Fails CLOSED — if we can't verify, the message is rejected, never saved.
        message_text = data.get('message', '')
        safety_result = moderate_message(message_text, use_ai=True)
        if not safety_result["is_safe"]:
            return Response({
                "error": "Your message was flagged as unsafe and could not be sent.",
                "reason": safety_result["reason"],
                "layer": safety_result.get("layer", "unknown"),
                "status": status.HTTP_400_BAD_REQUEST
            }, status=status.HTTP_400_BAD_REQUEST)

        # Create the message
        message_instance = Message.objects.create(
            chat=chat,
            sender=user,
            receiver=receiver,
            message=message_text
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
def MarkChatRead(request):
    """Mark all messages in the chat as read for the current user (receiver)."""
    try:
        chat_id = request.data.get('chat_id')
        if chat_id is None:
            return Response({"error": "chat_id is required."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            chat_id = int(chat_id)
        except (TypeError, ValueError):
            return Response({"error": "chat_id must be a number."}, status=status.HTTP_400_BAD_REQUEST)

        chat = get_object_or_404(Chat, id=chat_id)
        if request.user not in chat.participants.all():
            return Response({"error": "You are not a participant in this chat."}, status=status.HTTP_403_FORBIDDEN)

        # Mark all messages where current user is the receiver as read
        updated = Message.objects.filter(chat=chat, receiver=request.user).update(message_read=True)
        return Response({"message": "Chat marked as read.", "updated_count": updated}, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def DeleteAccount(request):
    """Permanently delete the current user's account and all associated data; invalidate auth token."""
    try:
        user = request.user
        # Invalidate all Knox tokens for this user so the client is logged out
        AuthToken.objects.filter(user=user).delete()
        user.delete()  # CASCADE will remove UserProfile and other related data
        return Response({"message": "Account deleted successfully."}, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def DeleteMyData(request):
    """GDPR-style: delete or anonymize the current user's personal data and invalidate session (logout)."""
    try:
        user = request.user
        # Anonymize User
        user.email = f"deleted_{user.id}@deleted.local"
        user.username = f"deleted_{user.id}"
        user.first_name = ""
        user.last_name = ""
        user.set_unusable_password()
        user.save()

        # Anonymize UserProfile if exists
        if hasattr(user, 'userprofile'):
            profile = user.userprofile
            profile.contact = ""
            profile.address = ""
            profile.profile_picture = ""
            profile.national_id_or_passport_number = ""
            profile.national_id_or_passport_document = ""
            profile.save()

        # Invalidate all tokens (logout)
        AuthToken.objects.filter(user=user).delete()

        return Response({"message": "Your data has been deleted successfully."}, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def DeleteItem(request):
    """Permanently delete the listing with the given item_id if it belongs to the current user."""
    try:
        item_id = request.data.get('item_id')
        if item_id is None:
            return Response({"error": "item_id is required."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            item_id = int(item_id)
        except (TypeError, ValueError):
            return Response({"error": "item_id must be a number."}, status=status.HTTP_400_BAD_REQUEST)

        item = get_object_or_404(Item, id=item_id)
        if item.seller != request.user:
            return Response({"error": "You are not the owner of this listing."}, status=status.HTTP_403_FORBIDDEN)

        item_name = item.item_name
        item.delete()
        return Response({"message": f"Item '{item_name}' deleted successfully."}, status=status.HTTP_200_OK)
    except Exception as e:
        if hasattr(e, 'status_code'):
            raise
        return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)


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
        ).filter((q_objects | Q(similarity_name__gt=0.3) | Q(similarity_desc__gt=0.3)) & Q(approval_status='Approved')).distinct()
    else:
        items = Item.objects.filter(approval_status='Approved')

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

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def UpdateItemApprovalStatus(request):
    """
    Admin-only endpoint to approve or reject an item. Requires item_id, approval_status, and (if rejected) rejection_reason.
    """
    user = request.user
    if not hasattr(user, 'userprofile') or user.userprofile.role != 'Admin':
        return Response({"message": "You do not have permission to perform this action."}, status=403)

    item_id = request.data.get('item_id')
    approval_status = request.data.get('approval_status')  # 'Approved' or 'Rejected'
    rejection_reason = request.data.get('rejection_reason', None)

    if not item_id or approval_status not in ['Approved', 'Rejected']:
        return Response({"message": "item_id and valid approval_status ('Approved' or 'Rejected') are required."}, status=400)

    from .models import Item
    try:
        item = Item.objects.get(id=item_id)
    except Item.DoesNotExist:
        return Response({"message": "Item not found."}, status=404)

    item.approval_status = approval_status
    item.approved_by = user
    if approval_status == 'Rejected':
        if not rejection_reason:
            return Response({"message": "rejection_reason is required when rejecting an item."}, status=400)
        item.rejection_reason = rejection_reason
    else:
        item.rejection_reason = None
    item.save()

    # Log the action
    from .models import ActivityLog
    log_action = f"Item '{item.item_name}' set to {approval_status} by {user.get_full_name() or user.username}."
    if approval_status == 'Rejected':
        log_action += f" Reason: {rejection_reason}"
    ActivityLog.objects.create(
        user=user,
        action=log_action,
        ip_address=request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0] or request.META.get('REMOTE_ADDR'),
        user_agent=request.META.get('HTTP_USER_AGENT')
    )

    return Response({"message": f"Item approval status updated to {approval_status}.", "status": 200})

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def GetAllItemsAdmin(request):
    user = request.user
    if not hasattr(user, 'userprofile') or user.userprofile.role != 'Admin':
        return Response({"message": "You do not have permission to perform this action."}, status=403)
    items = Item.objects.all().select_related('seller', 'item_subcategory__subcategory_category', 'approved_by').prefetch_related('images')
    # Use ItemSerializer or create a new serializer if you want more fields
    serializer = ItemAdminSerializer(items, many=True)
    return Response({"data": serializer.data, "status": 200})

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def GetItemDetailsAdmin(request):
    user = request.user
    if not hasattr(user, 'userprofile') or user.userprofile.role != 'Admin':
        return Response({"message": "You do not have permission to perform this action."}, status=403)
    item_id = request.query_params.get('item_id') or request.data.get('item_id')
    if not item_id:
        return Response({"message": "item_id is required."}, status=400)
    try:
        item = Item.objects.select_related('seller', 'item_subcategory__subcategory_category', 'approved_by').prefetch_related('images').get(id=item_id)
    except Item.DoesNotExist:
        return Response({"message": "Item not found."}, status=404)
    serializer = ItemAdminSerializer(item)
    # Add metadata field to the response
    data = serializer.data
    data['metadata'] = item.metadata if hasattr(item, 'metadata') else None
    return Response({"data": data, "status": 200})

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def GetAllUsersAdmin(request):
    user = request.user
    if not hasattr(user, 'userprofile') or user.userprofile.role != 'Admin':
        return Response({"message": "You do not have permission to perform this action."}, status=403)
    users = User.objects.all().select_related('userprofile')
    data = []
    for u in users:
        profile = getattr(u, 'userprofile', None)
        data.append({
            'id': u.id,
            'username': u.username,
            'email': u.email,
            'first_name': u.first_name,
            'last_name': u.last_name,
            'is_active': u.is_active,
            'date_joined': u.date_joined,
            'role': profile.role if profile else None,
            'contact': profile.contact if profile else None,
            'address': profile.address if profile else None,
            'profile_picture': profile.profile_picture if profile else None,
        })
    return Response({"data": data, "status": 200})

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def ChangeUserRoleAdmin(request):
    user = request.user
    if not hasattr(user, 'userprofile') or user.userprofile.role != 'Admin':
        return Response({"message": "You do not have permission to perform this action."}, status=403)
    user_id = request.data.get('user_id')
    new_role = request.data.get('role')
    if not user_id or new_role not in ['Client', 'Vendor', 'Admin']:
        return Response({"message": "user_id and valid role are required."}, status=400)
    try:
        target_user = User.objects.get(id=user_id)
        profile = target_user.userprofile
        profile.role = new_role
        profile.save()
        return Response({"message": f"User role updated to {new_role}.", "status": 200})
    except User.DoesNotExist:
        return Response({"message": "User not found."}, status=404)
    except UserProfile.DoesNotExist:
        return Response({"message": "User profile not found."}, status=404)

@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def DeleteUserAdmin(request):
    user = request.user
    if not hasattr(user, 'userprofile') or user.userprofile.role != 'Admin':
        return Response({"message": "You do not have permission to perform this action."}, status=403)
    user_id = request.data.get('user_id')
    if not user_id:
        return Response({"message": "user_id is required."}, status=400)
    try:
        target_user = User.objects.get(id=user_id)
        target_user.delete()
        return Response({"message": "User deleted successfully.", "status": 200})
    except User.DoesNotExist:
        return Response({"message": "User not found."}, status=404)

@api_view(['PATCH'])
@permission_classes([IsAuthenticated])
def UpdateUserAdmin(request):
    user = request.user
    if not hasattr(user, 'userprofile') or user.userprofile.role != 'Admin':
        return Response({"message": "You do not have permission to perform this action."}, status=403)
    user_id = request.data.get('user_id')
    if not user_id:
        return Response({"message": "user_id is required."}, status=400)
    try:
        target_user = User.objects.get(id=user_id)
        profile = target_user.userprofile
        # Update user fields
        for field in ['username', 'email', 'first_name', 'last_name', 'is_active']:
            if field in request.data:
                setattr(target_user, field, request.data[field])
        target_user.save()
        # Update profile fields
        for field in ['contact', 'address', 'profile_picture']:
            if field in request.data:
                setattr(profile, field, request.data[field])
        profile.save()
        return Response({"message": "User and profile updated successfully.", "status": 200})
    except User.DoesNotExist:
        return Response({"message": "User not found."}, status=404)
    except UserProfile.DoesNotExist:
        return Response({"message": "User profile not found."}, status=404)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def AdminDashboardStats(request):
    user = request.user
    if not hasattr(user, 'userprofile') or user.userprofile.role != 'Admin':
        return Response({"message": "You do not have permission to perform this action."}, status=403)

    # User roles
    total_users = User.objects.count()
    total_clients = UserProfile.objects.filter(role='Client').count()
    total_vendors = UserProfile.objects.filter(role='Vendor').count()
    total_admins = UserProfile.objects.filter(role='Admin').count()

    # Items
    total_items = Item.objects.count()
    total_approved_items = Item.objects.filter(approval_status='Approved').count()
    total_likes = Item.objects.aggregate(total=Sum('likes_count'))['total'] or 0
    total_views = Item.objects.aggregate(total=Sum('views_count'))['total'] or 0
    total_shares = Item.objects.aggregate(total=Sum('shares_count'))['total'] or 0

    # Wishlist actions
    total_wishlist_actions = Wishlist.objects.count()

    # Reports
    total_reports = ReportAbuse.objects.count()

    # Subscribers
    total_subscribers = NewsLetterSubcribers.objects.count()

    return Response({
        "total_users": total_users,
        "total_admins": total_admins,
        "total_vendors": total_vendors,
        "total_clients": total_clients,
        "total_items": total_items,
        "total_approved_items": total_approved_items,
        "total_likes": total_likes,
        "total_views": total_views,
        "total_shares": total_shares,
        "total_wishlist_actions": total_wishlist_actions,
        "total_reports": total_reports,
        "total_subscribers": total_subscribers,
        "status": 200
    })

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def AdminAnalytics(request):
    user = request.user
    if not hasattr(user, 'userprofile') or user.userprofile.role != 'Admin':
        return Response({"message": "You do not have permission to perform this action."}, status=403)

    try:
        days = int(request.query_params.get('days', 30))
    except (TypeError, ValueError):
        days = 30
    days = min(max(days, 7), 90)
    start_date = timezone.now().date() - timedelta(days=days - 1)

    def daily_counts(model, date_field, queryset=None):
        qs = queryset if queryset is not None else model.objects.all()
        qs = qs.filter(**{f"{date_field}__date__gte": start_date})
        rows = (
            qs.annotate(day=TruncDate(date_field))
            .values('day')
            .annotate(count=Count('id'))
            .order_by('day')
        )
        counts = {row['day']: row['count'] for row in rows}
        return [
            {
                "date": (start_date + timedelta(days=offset)).isoformat(),
                "count": counts.get(start_date + timedelta(days=offset), 0),
            }
            for offset in range(days)
        ]

    user_registrations = daily_counts(User, 'date_joined')
    product_posts = daily_counts(Item, 'created_at')
    chats_created = daily_counts(Chat, 'created_at')
    messages_sent = daily_counts(Message, 'created_at')

    approval_distribution = list(
        Item.objects.values('approval_status')
        .annotate(count=Count('id'))
        .order_by('approval_status')
    )
    status_distribution = list(
        Item.objects.values('item_status')
        .annotate(count=Count('id'))
        .order_by('item_status')
    )

    category_performance = list(
        Category.objects.annotate(
            total_items=Count('subcategory__item', distinct=True),
            approved_items=Count(
                'subcategory__item',
                filter=Q(subcategory__item__approval_status='Approved'),
                distinct=True,
            ),
            sold_items=Count(
                'subcategory__item',
                filter=Q(subcategory__item__item_status='Sold'),
                distinct=True,
            ),
            out_of_stock_items=Count(
                'subcategory__item',
                filter=Q(subcategory__item__item_status='Out of Stock'),
                distinct=True,
            ),
            cancelled_items=Count(
                'subcategory__item',
                filter=Q(subcategory__item__item_status='Cancelled'),
                distinct=True,
            ),
        )
        .values(
            'id',
            'category_name',
            'total_items',
            'approved_items',
            'sold_items',
            'out_of_stock_items',
            'cancelled_items',
        )
        .order_by('-total_items')[:10]
    )

    top_chatted_products = list(
        Item.objects.annotate(
            chat_count=Count('chat', distinct=True),
            message_count=Count('chat__messages', distinct=True),
        )
        .filter(chat_count__gt=0)
        .values('id', 'item_name', 'chat_count', 'message_count')
        .order_by('-message_count', '-chat_count')[:10]
    )

    pending_items = Item.objects.filter(approval_status='Pending').count()
    reports_pending = ReportAbuse.objects.filter(status__in=['Pending', 'In Review']).count()
    unread_messages = Message.objects.filter(message_read=False).count()

    return Response({
        "summary": {
            "total_chats": Chat.objects.count(),
            "total_messages": Message.objects.count(),
            "unread_messages": unread_messages,
            "pending_items": pending_items,
            "reports_pending": reports_pending,
        },
        "trends": {
            "user_registrations": user_registrations,
            "product_posts": product_posts,
            "chats_created": chats_created,
            "messages_sent": messages_sent,
        },
        "distributions": {
            "approval_status": approval_distribution,
            "item_status": status_distribution,
        },
        "category_performance": category_performance,
        "top_chatted_products": top_chatted_products,
        "status": 200,
    }, status=status.HTTP_200_OK)

# Category and Subcategory Admin Views
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def AddCategory(request):
    user = request.user
    if not hasattr(user, 'userprofile') or user.userprofile.role != 'Admin':
        return Response({"message": "You do not have permission to perform this action."}, status=status.HTTP_403_FORBIDDEN)
    
    category_name = request.data.get('category_name')
    image_url = request.data.get('image_url')  # New field for image_url

    if not category_name:
        return Response({"message": "Category name is required."}, status=status.HTTP_400_BAD_REQUEST)
    
    # Check if category already exists
    if Category.objects.filter(category_name__iexact=category_name).exists():
        return Response({"message": "Category with this name already exists."}, status=status.HTTP_400_BAD_REQUEST)
    
    try:
        category = Category.objects.create(
            category_name=category_name,
            image_url=image_url  # Save image_url if provided
        )
        
        # Log activity
        ActivityLog.objects.create(
            user=user,
            action=f"Created new category: {category_name}",
            ip_address=request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0] or request.META.get('REMOTE_ADDR'),
            user_agent=request.META.get('HTTP_USER_AGENT')
        )
        
        return Response({
            "message": "Category created successfully.",
            "category": {
                "id": category.id,
                "category_name": category.category_name,
                "image_url": category.image_url,  # Include image_url in response
                "created_at": category.created_at
            },
            "status": status.HTTP_201_CREATED
        })
    except Exception as e:
        return Response({"message": f"Error creating category: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def GetAllCategories(request):
    user = request.user
    if not hasattr(user, 'userprofile') or user.userprofile.role != 'Admin':
        return Response({"message": "You do not have permission to perform this action."}, status=status.HTTP_403_FORBIDDEN)
    
    categories = Category.objects.all().order_by('category_name')
    categories_data = []
    
    for category in categories:
        subcategory_count = SubCategory.objects.filter(subcategory_category=category).count()
        item_count = Item.objects.filter(item_subcategory__subcategory_category=category).count()
        
        categories_data.append({
            "id": category.id,
            "category_name": category.category_name,
            "image_url": category.image_url,  # Added image_url field
            "subcategory_count": subcategory_count,
            "item_count": item_count,
            "created_at": category.created_at,
            "updated_at": category.updated_at
        })
    
    return Response({"data": categories_data, "status": status.HTTP_200_OK})

@api_view(['PUT'])
@permission_classes([IsAuthenticated])
def UpdateCategory(request):
    user = request.user
    if not hasattr(user, 'userprofile') or user.userprofile.role != 'Admin':
        return Response({"message": "You do not have permission to perform this action."}, status=status.HTTP_403_FORBIDDEN)
    
    category_id = request.data.get('category_id')
    category_name = request.data.get('category_name')
    image_url = request.data.get('image_url', None)  # Add image_url field (optional)
    
    if not category_id or not category_name:
        return Response({"message": "Category ID and name are required."}, status=status.HTTP_400_BAD_REQUEST)
    
    try:
        category = Category.objects.get(id=category_id)
        
        # Check if another category with the same name exists
        if Category.objects.filter(category_name__iexact=category_name).exclude(id=category_id).exists():
            return Response({"message": "Another category with this name already exists."}, status=status.HTTP_400_BAD_REQUEST)
        
        old_name = category.category_name
        category.category_name = category_name
        if image_url is not None:
            category.image_url = image_url  # Update image_url if provided
        category.save()
        
        # Log activity
        ActivityLog.objects.create(
            user=user,
            action=f"Updated category from '{old_name}' to '{category_name}'",
            ip_address=request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0] or request.META.get('REMOTE_ADDR'),
            user_agent=request.META.get('HTTP_USER_AGENT')
        )
        
        return Response({
            "message": "Category updated successfully.",
            "category": {
                "id": category.id,
                "category_name": category.category_name,
                "image_url": category.image_url,  # Include image_url in response
                "updated_at": category.updated_at
            },
            "status": status.HTTP_200_OK
        })
    except Category.DoesNotExist:
        return Response({"message": "Category not found."}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({"message": f"Error updating category: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)

@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def DeleteCategory(request):
    user = request.user
    if not hasattr(user, 'userprofile') or user.userprofile.role != 'Admin':
        return Response({"message": "You do not have permission to perform this action."}, status=status.HTTP_403_FORBIDDEN)
    
    category_id = request.data.get('category_id')
    if not category_id:
        return Response({"message": "Category ID is required."}, status=status.HTTP_400_BAD_REQUEST)
    
    try:
        category = Category.objects.get(id=category_id)
        
        # Check if there are items associated with this category
        items_count = Item.objects.filter(item_subcategory__subcategory_category=category).count()
        if items_count > 0:
            return Response({
                "message": f"Cannot delete category. It has {items_count} items associated with it.",
                "status": status.HTTP_400_BAD_REQUEST
            })
        
        category_name = category.category_name
        category.delete()
        
        # Log activity
        ActivityLog.objects.create(
            user=user,
            action=f"Deleted category: {category_name}",
            ip_address=request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0] or request.META.get('REMOTE_ADDR'),
            user_agent=request.META.get('HTTP_USER_AGENT')
        )
        
        return Response({"message": "Category deleted successfully.", "status": status.HTTP_200_OK})
    except Category.DoesNotExist:
        return Response({"message": "Category not found."}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({"message": f"Error deleting category: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def AddSubcategory(request):
    user = request.user
    if not hasattr(user, 'userprofile') or user.userprofile.role != 'Admin':
        return Response({"message": "You do not have permission to perform this action."}, status=status.HTTP_403_FORBIDDEN)
    
    subcategory_name = request.data.get('subcategory_name')
    category_id = request.data.get('category_id')
    image_url = request.data.get('image_url', None)  # Optional image_url field
    metadata = request.data.get('metadata', None)  # Optional metadata field
    
    if not subcategory_name or not category_id:
        return Response({"message": "Subcategory name and category ID are required."}, status=status.HTTP_400_BAD_REQUEST)
    
    # Check if subcategory already exists
    if SubCategory.objects.filter(subcategory_name__iexact=subcategory_name).exists():
        return Response({"message": "Subcategory with this name already exists."}, status=status.HTTP_400_BAD_REQUEST)
    
    try:
        category = Category.objects.get(id=category_id)
        subcategory = SubCategory.objects.create(
            subcategory_name=subcategory_name,
            subcategory_category=category,
            image_url=image_url if image_url is not None else None,
            metadata=metadata if metadata is not None else None
        )
        
        # Log activity
        ActivityLog.objects.create(
            user=user,
            action=f"Created new subcategory: {subcategory_name} under category: {category.category_name}",
            ip_address=request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0] or request.META.get('REMOTE_ADDR'),
            user_agent=request.META.get('HTTP_USER_AGENT')
        )
        
        return Response({
            "message": "Subcategory created successfully.",
            "subcategory": {
                "id": subcategory.id,
                "subcategory_name": subcategory.subcategory_name,
                "category_name": category.category_name,
                "image_url": subcategory.image_url,  # Include image_url in response
                "metadata": subcategory.metadata,
                "created_at": subcategory.created_at
            },
            "status": status.HTTP_201_CREATED
        })
    except Category.DoesNotExist:
        return Response({"message": "Category not found."}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({"message": f"Error creating subcategory: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def GetAllSubcategories(request):
    user = request.user
    if not hasattr(user, 'userprofile') or user.userprofile.role != 'Admin':
        return Response({"message": "You do not have permission to perform this action."}, status=status.HTTP_403_FORBIDDEN)
    
    category_id = request.query_params.get('category_id')
    
    subcategories_query = SubCategory.objects.all()
    if category_id:
        subcategories_query = subcategories_query.filter(subcategory_category_id=category_id)
    
    subcategories = subcategories_query.select_related('subcategory_category').order_by('subcategory_name')
    subcategories_data = []
    
    for subcategory in subcategories:
        item_count = Item.objects.filter(item_subcategory=subcategory).count()
        
        subcategories_data.append({
            "id": subcategory.id,
            "subcategory_name": subcategory.subcategory_name,
            "category": {
                "id": subcategory.subcategory_category.id,
                "category_name": subcategory.subcategory_category.category_name
            },
            "image_url": subcategory.image_url,  # Add image_url to the response
            "metadata": subcategory.metadata,  # Add metadata to the response
            "item_count": item_count,
            "created_at": subcategory.created_at,
            "updated_at": subcategory.updated_at
        })
    
    return Response({"data": subcategories_data, "status": status.HTTP_200_OK})

@api_view(['PUT'])
@permission_classes([IsAuthenticated])
def UpdateSubcategory(request):
    user = request.user
    if not hasattr(user, 'userprofile') or user.userprofile.role != 'Admin':
        return Response({"message": "You do not have permission to perform this action."}, status=status.HTTP_403_FORBIDDEN)
    
    subcategory_id = request.data.get('subcategory_id')
    subcategory_name = request.data.get('subcategory_name')
    category_id = request.data.get('category_id')
    metadata = request.data.get('metadata')  # New: get metadata from request
    image_url = request.data.get('image_url')  # New: get image_url from request

    if not subcategory_id or not subcategory_name:
        return Response({"message": "Subcategory ID and name are required."}, status=status.HTTP_400_BAD_REQUEST)
    
    try:
        subcategory = SubCategory.objects.get(id=subcategory_id)
        old_name = subcategory.subcategory_name
        old_category = subcategory.subcategory_category
        old_metadata = subcategory.metadata
        old_image_url = subcategory.image_url

        # Check if another subcategory with the same name exists
        if SubCategory.objects.filter(subcategory_name__iexact=subcategory_name).exclude(id=subcategory_id).exists():
            return Response({"message": "Another subcategory with this name already exists."}, status=status.HTTP_400_BAD_REQUEST)
        
        subcategory.subcategory_name = subcategory_name
        
        # Update category if provided
        if category_id:
            try:
                category = Category.objects.get(id=category_id)
                subcategory.subcategory_category = category
            except Category.DoesNotExist:
                return Response({"message": "Category not found."}, status=status.HTTP_404_NOT_FOUND)
        
        # Update metadata if provided
        if metadata is not None:
            subcategory.metadata = metadata

        # Update image_url if provided
        if image_url is not None:
            subcategory.image_url = image_url

        subcategory.save()
        
        # Log activity
        change_log = []
        if old_name != subcategory_name:
            change_log.append(f"name from '{old_name}' to '{subcategory_name}'")
        
        if category_id and old_category.id != int(category_id):
            change_log.append(f"category from '{old_category.category_name}' to '{subcategory.subcategory_category.category_name}'")
        
        if metadata is not None and old_metadata != metadata:
            change_log.append(f"metadata from '{old_metadata}' to '{metadata}'")

        if image_url is not None and old_image_url != image_url:
            change_log.append(f"image_url from '{old_image_url}' to '{image_url}'")
        
        changes = ", ".join(change_log) if change_log else "no changes"
        ActivityLog.objects.create(
            user=user,
            action=f"Updated subcategory: changed {changes}",
            ip_address=request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0] or request.META.get('REMOTE_ADDR'),
            user_agent=request.META.get('HTTP_USER_AGENT')
        )
        
        return Response({
            "message": "Subcategory updated successfully.",
            "subcategory": {
                "id": subcategory.id,
                "subcategory_name": subcategory.subcategory_name,
                "category": {
                    "id": subcategory.subcategory_category.id,
                    "category_name": subcategory.subcategory_category.category_name
                },
                "image_url": subcategory.image_url,  # Include image_url in response
                "metadata": subcategory.metadata,  # Include metadata in response
                "updated_at": subcategory.updated_at
            },
            "status": status.HTTP_200_OK
        })
    except SubCategory.DoesNotExist:
        return Response({"message": "Subcategory not found."}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({"message": f"Error updating subcategory: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)

@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def DeleteSubcategory(request):
    user = request.user
    if not hasattr(user, 'userprofile') or user.userprofile.role != 'Admin':
        return Response({"message": "You do not have permission to perform this action."}, status=status.HTTP_403_FORBIDDEN)
    
    subcategory_id = request.data.get('subcategory_id')
    if not subcategory_id:
        return Response({"message": "Subcategory ID is required."}, status=status.HTTP_400_BAD_REQUEST)
    
    try:
        subcategory = SubCategory.objects.get(id=subcategory_id)
        
        # Check if there are items associated with this subcategory
        items_count = Item.objects.filter(item_subcategory=subcategory).count()
        if items_count > 0:
            return Response({
                "message": f"Cannot delete subcategory. It has {items_count} items associated with it.",
                "status": status.HTTP_400_BAD_REQUEST
            })
        
        subcategory_name = subcategory.subcategory_name
        category_name = subcategory.subcategory_category.category_name
        subcategory.delete()
        
        # Log activity
        ActivityLog.objects.create(
            user=user,
            action=f"Deleted subcategory: {subcategory_name} from category: {category_name}",
            ip_address=request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0] or request.META.get('REMOTE_ADDR'),
            user_agent=request.META.get('HTTP_USER_AGENT')
        )
        
        return Response({"message": "Subcategory deleted successfully.", "status": status.HTTP_200_OK})
    except SubCategory.DoesNotExist:
        return Response({"message": "Subcategory not found."}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({"message": f"Error deleting subcategory: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def UpdateItemPromotedStatus(request):
    """
    Admin-only endpoint to update the promoted status of an item.
    Requires item_id and promoted_status (boolean).
    """
    user = request.user
    if not hasattr(user, 'userprofile') or user.userprofile.role != 'Admin':
        return Response({"message": "You do not have permission to perform this action."}, status=status.HTTP_403_FORBIDDEN)

    item_id = request.data.get('item_id')
    promoted_status = request.data.get('promoted_status')
    
    # Validate required parameters
    if item_id is None:
        return Response({"message": "item_id is required."}, status=status.HTTP_400_BAD_REQUEST)
    
    if promoted_status is None:
        return Response({"message": "promoted_status is required."}, status=status.HTTP_400_BAD_REQUEST)
    
    # Convert promoted_status to boolean if it's a string
    if isinstance(promoted_status, str):
        promoted_status = promoted_status.lower() == 'true'
    
    try:
        item = Item.objects.get(id=item_id)
        
        # Update the promoted status
        old_status = item.item_promoted
        item.item_promoted = promoted_status
        item.save()
        
        # Log the action
        status_change = "promoted" if promoted_status else "unpromoted"
        ActivityLog.objects.create(
            user=user,
            action=f"Admin {status_change} item: {item.item_name} (ID: {item.id})",
            ip_address=request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0] or request.META.get('REMOTE_ADDR'),
            user_agent=request.META.get('HTTP_USER_AGENT')
        )
        
        return Response({
            "message": f"Item promotion status updated to {promoted_status}.",
            "item": {
                "id": item.id,
                "name": item.item_name,
                "promoted": item.item_promoted
            },
            "status": status.HTTP_200_OK
        })
        
    except Item.DoesNotExist:
        return Response({"message": "Item not found."}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({"message": f"Error updating item promotion status: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)

@api_view(['GET'])
def getPremiumSection(request):
    """
    Returns a paginated list of approved items on the Elite Plan subscription.
    """
    try:
        items = Item.objects.filter(
            approval_status='Approved',
            subscription_package='Elite Plan'
        ).select_related(
            'item_subcategory__subcategory_category'
        ).prefetch_related('images')

        # Log for debugging
        print(f"Found {items.count()} premium items")
        
        # Apply pagination
        paginator = CustomPagination()
        paginated_items = paginator.paginate_queryset(items, request)

        # Serialize paginated items
        serialized_items = ItemSerializer(paginated_items, many=True).data

        return paginator.get_paginated_response({
            "data": serialized_items, 
            "message": "Premium Section Items Fetched Successfully.",
            "count": items.count()
        })

    except Exception as e:
        print(f"Error in getPremiumSection: {str(e)}")
        return Response({"error": str(e), "message": "Error fetching premium section items."}, status=status.HTTP_400_BAD_REQUEST)

@api_view(['GET'])
def getTrendingProducts(request):
    """
    Returns a paginated list of approved items with Boost 7, Boost 30, Essential Plan, or Growth Plan subscriptions.
    """
    try:
        # Define the list of trending subscription packages
        trending_packages = [
            'Boost 7',
            'Boost 30',
            'Essential Plan',
            'Growth Plan',
            'Elite Plan',
        ]

        items = Item.objects.filter(
            approval_status='Approved',
            subscription_package__in=trending_packages
        ).select_related(
            'item_subcategory__subcategory_category'
        ).prefetch_related('images')

        # Log for debugging
        print(f"Found {items.count()} trending items")
        
        # Apply pagination
        paginator = CustomPagination()
        paginated_items = paginator.paginate_queryset(items, request)

        # Serialize paginated items
        serialized_items = ItemSerializer(paginated_items, many=True).data

        return paginator.get_paginated_response({
            "data": serialized_items, 
            "message": "Trending Products Fetched Successfully.",
            "count": items.count()
        })

    except Exception as e:
        print(f"Error in getTrendingProducts: {str(e)}")
        return Response({"error": str(e), "message": "Error fetching trending products."}, status=status.HTTP_400_BAD_REQUEST)

@api_view(['GET'])
def getProductListing(request):
    """
    Returns a paginated list of all approved items.
    """
    try:
        items = Item.objects.filter(
            approval_status='Approved'
        ).select_related(
            'item_subcategory__subcategory_category'
        ).prefetch_related('images')

        # Log for debugging
        print(f"Found {items.count()} items in product listing")
        
        # Apply pagination
        paginator = CustomPagination()
        paginated_items = paginator.paginate_queryset(items, request)

        # Serialize paginated items
        serialized_items = ItemSerializer(paginated_items, many=True).data

        return paginator.get_paginated_response({
            "data": serialized_items, 
            "message": "Product Listing Fetched Successfully.",
            "count": items.count()
        })

    except Exception as e:
        print(f"Error in getProductListing: {str(e)}")
        return Response({"error": str(e), "message": "Error fetching product listing."}, status=status.HTTP_400_BAD_REQUEST)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def updateItemSubscription(request):
    """
    Admin-only endpoint to update subscription package for an item or multiple items.
    """
    user = request.user
    if not hasattr(user, 'userprofile') or user.userprofile.role != 'Admin':
        return Response({"message": "You do not have permission to perform this action."}, status=status.HTTP_403_FORBIDDEN)

    item_id = request.data.get('item_id')
    subscription_package = request.data.get('subscription_package')
    update_all = request.data.get('update_all', False)
    
    # Validate input
    if not subscription_package:
        return Response({"message": "subscription_package is required."}, status=status.HTTP_400_BAD_REQUEST)
    
    # Validate package name
    valid_packages = [
        'Starter Package',
        'Boost 7',
        'Boost 30',
        'Essential Plan',
        'Growth Plan',
        'Elite Plan',
    ]
    
    if subscription_package not in valid_packages:
        return Response({
            "message": f"Invalid subscription package. Valid options are: {', '.join(valid_packages)}"
        }, status=status.HTTP_400_BAD_REQUEST)
    
    try:
        if update_all:
            # Update multiple items based on query params
            category_id = request.data.get('category_id')
            subcategory_id = request.data.get('subcategory_id')
            min_price = request.data.get('min_price')
            max_price = request.data.get('max_price')
            
            # Start with all items
            items_query = Item.objects.all()
            
            # Apply filters if provided
            if category_id:
                items_query = items_query.filter(item_subcategory__subcategory_category_id=category_id)
            if subcategory_id:
                items_query = items_query.filter(item_subcategory_id=subcategory_id)
            if min_price:
                items_query = items_query.filter(item_price__gte=min_price)
            if max_price:
                items_query = items_query.filter(item_price__lte=max_price)
            
            # Update the subscription package for all matching items
            count = items_query.update(subscription_package=subscription_package)
            
            return Response({
                "message": f"Updated subscription package to '{subscription_package}' for {count} items.",
                "count": count,
                "status": status.HTTP_200_OK
            })
        else:
            # Update a single item
            if not item_id:
                return Response({"message": "item_id is required when not using update_all."}, status=status.HTTP_400_BAD_REQUEST)
            
            item = Item.objects.get(id=item_id)
            old_package = item.subscription_package
            item.subscription_package = subscription_package
            item.save()
            
            return Response({
                "message": f"Updated subscription package from '{old_package or 'None'}' to '{subscription_package}' for item: {item.item_name}",
                "item": {
                    "id": item.id,
                    "name": item.item_name,
                    "subscription_package": item.subscription_package
                },
                "status": status.HTTP_200_OK
            })
    except Item.DoesNotExist:
        return Response({"message": "Item not found."}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({"message": f"Error updating subscription package: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def getSubscriptionStats(request):
    """
    Returns statistics about items and their subscription packages.
    """
    try:
        from django.db.models import Count, Q
        
        total_items = Item.objects.count()
        approved_items = Item.objects.filter(approval_status='Approved').count()
        
        # Count items by subscription package
        subscription_counts = {}
        
        # First add all possible packages with zero counts
        valid_packages = [
            'Starter Package',
            'Boost 7',
            'Boost 30',
            'Essential Plan',
            'Growth Plan',
            'Elite Plan',
        ]
        
        for package in valid_packages:
            subscription_counts[package] = 0
        
        # Add null/empty package
        subscription_counts['No Package'] = 0
        
        # Now get actual counts
        package_stats = Item.objects.values('subscription_package').annotate(
            count=Count('id')
        )
        
        for stat in package_stats:
            package = stat['subscription_package'] or 'No Package'
            subscription_counts[package] = stat['count']
        
        # Count items with no subscription package
        null_package_count = Item.objects.filter(
            subscription_package__isnull=True
        ).count()
        
        empty_package_count = Item.objects.filter(
            subscription_package=''
        ).count()
        
        # Add to "No Package" count
        subscription_counts['No Package'] += null_package_count + empty_package_count
        
        # Get the first 5 items for each package for sample viewing
        sample_items = {}
        for package in valid_packages + ['No Package']:
            if package == 'No Package':
                items = Item.objects.filter(
                    Q(subscription_package__isnull=True) | Q(subscription_package='')
                )[:5]
            else:
                items = Item.objects.filter(subscription_package=package)[:5]
            
            sample_items[package] = [
                {
                    'id': item.id,
                    'name': item.item_name,
                    'approval_status': item.approval_status,
                    'subscription_package': item.subscription_package
                }
                for item in items
            ]
        
        return Response({
            "total_items": total_items,
            "approved_items": approved_items,
            "subscription_counts": subscription_counts,
            "sample_items": sample_items,
            "null_package_count": null_package_count,
            "empty_package_count": empty_package_count,
            "status": status.HTTP_200_OK
        })
        
    except Exception as e:
        print(f"Error in getSubscriptionStats: {str(e)}")
        return Response({"error": str(e), "message": "Error fetching subscription statistics."}, status=status.HTTP_400_BAD_REQUEST)


# ---------------------------------------------------------------------------
# Admin: purge unsafe messages
# ---------------------------------------------------------------------------
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def PurgeUnsafeMessages(request):
    """
    Admin-only endpoint that scans all existing chat messages with Gemini
    and deletes any that are flagged as unsafe.

    POST body (all optional):
      {
        "dry_run": true,          // default true — set false to actually delete
        "batch_size": 15,         // messages per Gemini call
        "cleanup_empty_chats": false
      }

    Returns a summary of what was (or would be) deleted.
    """
    from .services import check_messages_batch, local_prescreen
    from django.db.models import Count as DjCount

    user = request.user
    if not hasattr(user, 'userprofile') or user.userprofile.role != 'Admin':
        return Response({"error": "Admin access required."}, status=status.HTTP_403_FORBIDDEN)

    dry_run = request.data.get("dry_run", True)
    batch_size = int(request.data.get("batch_size", 15))
    cleanup_empty_chats = bool(request.data.get("cleanup_empty_chats", False))
    strict = bool(request.data.get("strict", False))

    try:
        all_messages = list(
            Message.objects.only("id", "message", "chat_id", "sender_id", "receiver_id")
            .order_by("-created_at")
        )
        total = len(all_messages)

        unsafe_ids = []
        safe_count = 0
        skipped_count = 0
        api_error_count = 0
        results_log = []

        batches = [all_messages[i:i + batch_size] for i in range(0, total, batch_size)]

        for batch in batches:
            # Layer 1 — local prescreen (offline, instant).
            results_map = {}
            api_payload = []
            for m in batch:
                text = (m.message or "").strip()
                local = local_prescreen(text)
                if local["matched"]:
                    results_map[m.id] = {
                        "id": m.id,
                        "is_safe": local["is_safe"],
                        "reason": local["reason"],
                    }
                else:
                    api_payload.append({"id": m.id, "text": text})

            if api_payload:
                batch_results = check_messages_batch(api_payload)
                for r in batch_results:
                    results_map[r["id"]] = r

            for msg in batch:
                r = results_map.get(msg.id, {"is_safe": True, "reason": "No result."})
                is_safe = r.get("is_safe", True)
                reason = r.get("reason", "")
                api_error = reason.startswith("API_ERROR:")
                ai_inconclusive = (
                    not api_error and (
                        reason.lower().startswith("skipped")
                        or "parse error" in reason.lower()
                    )
                )

                if api_error:
                    api_error_count += 1
                    skipped_count += 1
                elif ai_inconclusive and strict:
                    unsafe_ids.append(msg.id)
                    results_log.append({
                        "id": msg.id,
                        "chat_id": msg.chat_id,
                        "reason": f"[strict] {reason}",
                        "preview": (msg.message or "")[:80],
                    })
                elif ai_inconclusive:
                    skipped_count += 1
                elif is_safe:
                    safe_count += 1
                else:
                    unsafe_ids.append(msg.id)
                    results_log.append({
                        "id": msg.id,
                        "chat_id": msg.chat_id,
                        "reason": reason,
                        "preview": (msg.message or "")[:80],
                    })

        deleted_count = 0
        deleted_chats = []

        # Safety guard: never delete when the AI never actually ran.
        api_wipeout = api_error_count > 0 and safe_count == 0 and (
            len(unsafe_ids) == api_error_count if strict else False
        )

        if not dry_run and unsafe_ids and not api_wipeout:
            deleted_count, _ = Message.objects.filter(id__in=unsafe_ids).delete()

            if cleanup_empty_chats:
                empty_chats = Chat.objects.annotate(mc=DjCount("messages")).filter(mc=0)
                deleted_chats = list(empty_chats.values_list("id", flat=True))
                if deleted_chats:
                    Chat.objects.filter(id__in=deleted_chats).delete()

        return Response({
            "dry_run": dry_run,
            "strict": strict,
            "total_scanned": total,
            "safe": safe_count,
            "unsafe": len(unsafe_ids),
            "skipped": skipped_count,
            "api_errors": api_error_count,
            "api_wipeout_aborted": bool(not dry_run and unsafe_ids and api_wipeout),
            "deleted_messages": deleted_count,
            "deleted_chats": deleted_chats,
            "unsafe_messages": results_log,
        }, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

