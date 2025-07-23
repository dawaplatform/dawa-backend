from django.db import models
from django.contrib.auth.models import User
import cloudinary.uploader
from django.utils.text import slugify

# Create your models here.
class UserProfile(models.Model):
    Client = 'Client'
    Vendor = 'Vendor'
    Admin = 'Admin'

    ROLE_CHOICES = [
        (Client, 'Client'),
        (Vendor, 'Vendor'),
        (Admin, 'Admin'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE)
    contact = models.CharField(max_length=255, null=True, blank=True)
    address = models.CharField(max_length=255, null=True, blank=True)
    profile_picture = models.URLField(max_length=500, null=True, blank=True)
    national_id_or_passport_number = models.CharField(max_length=50, unique=True, null=True, blank=True)
    national_id_or_passport_document = models.URLField(max_length=500, null=True, blank=True)
    otp_code = models.PositiveBigIntegerField(null=True, blank=True)
    otp_created_at = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default=Client)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        # Custom folder structure
        folder_path = f"Dawa/{self.user.first_name}_{self.user.last_name}"

        # Upload user profile picture
        
        if hasattr(self, 'profile_picture') and self.profile_picture:
            upload_result = cloudinary.uploader.upload(
                self.profile_picture,
                folder=folder_path,
                resource_type="image"
            )
            self.profile_picture = upload_result.get('secure_url')

        # Upload scanned document
        if hasattr(self, 'national_id_or_passport_document') and self.national_id_or_passport_document:
            upload_result = cloudinary.uploader.upload(
                self.national_id_or_passport_document,
                folder=folder_path,
                resource_type="auto"
            )
            self.national_id_or_passport_document = upload_result.get('secure_url')

        super().save(*args, **kwargs)

    def __str__(self):
        return str(self.user.email)

class Category(models.Model):
    category_name = models.CharField(max_length=50, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.category_name
    
class SubCategory(models.Model):
    subcategory_name = models.CharField(max_length=50, unique=True)
    subcategory_category = models.ForeignKey(Category, on_delete=models.CASCADE)
    metadata = models.JSONField(null=True, blank=True)  # Optional metadata field
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.subcategory_name
        
class Item(models.Model):
    STATUS_CHOICES = [
        ('Available', 'Available'),
        ('Sold', 'Sold'),
    ]

    APPROVAL_CHOICES = [
        ('Pending', 'Pending'),
        ('Approved', 'Approved'),
        ('Rejected', 'Rejected'),
    ]

    # Define choices for subscription packages
    SUBSCRIPTION_CHOICES = [
        ('Starter Package', 'Starter Package'),
        ('Boost 7', 'Boost 7'),
        ('Boost 30', 'Boost 30'),
        ('Essential Plan', 'Essential Plan'),
        ('Growth Plan', 'Growth Plan'),
        ('Elite Plan', 'Elite Plan'),
    ]

    seller = models.ForeignKey(User, on_delete=models.CASCADE)
    item_name = models.CharField(max_length=255)
    item_price = models.DecimalField(max_digits=10, decimal_places=0)
    item_location = models.CharField(max_length=255)
    item_negotiable = models.BooleanField(default=False)
    item_promoted = models.BooleanField(default=False)
    slug = models.SlugField(unique=True, blank=True)
    item_subcategory = models.ForeignKey('SubCategory', on_delete=models.CASCADE)
    item_status = models.CharField(max_length=50, choices=STATUS_CHOICES, default='Available')
    item_description = models.TextField()

    # New Fields
    approval_status = models.CharField(max_length=20, choices=APPROVAL_CHOICES, default='Pending', null=True, blank=True)
    approved_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='approved_items')
    rejection_reason = models.TextField(null=True, blank=True)
    views_count = models.PositiveIntegerField(default=0, null=True, blank=True)
    likes_count = models.PositiveIntegerField(default=0, null=True, blank=True)
    shares_count = models.PositiveIntegerField(default=0, null=True, blank=True)
    # Add the new subscription package field
    subscription_package = models.CharField(
        max_length=50,
        choices=SUBSCRIPTION_CHOICES,
        null=True,
        blank=True
    )

    # Optional metadata field
    metadata = models.JSONField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True)

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.item_name)
            unique_slug = base_slug
            num = 1
            while Item.objects.filter(slug=unique_slug).exists():
                unique_slug = f"{base_slug}-{num}"
                num += 1
            self.slug = unique_slug
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.item_name} by {self.seller.username}"

class ItemImage(models.Model):
    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name='images')
    image = models.URLField(max_length=500, null=True, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        # Custom folder structure
        folder_path = f"Dawa/{self.item.seller.first_name}_{self.item.seller.last_name}"

        # Upload user profile picture
        if hasattr(self, 'image') and self.image:
            upload_result = cloudinary.uploader.upload(
                self.image,
                folder=folder_path,
                resource_type="image"
            )
            self.image = upload_result.get('secure_url')

        super().save(*args, **kwargs)

    def __str__(self):
        return f"Image for {self.item.item_name}"
    
class Wishlist(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    item = models.ForeignKey(Item, on_delete=models.CASCADE)  # Link to the item
    is_wished = models.BooleanField(default=True)  # To distinguish favorites
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.username} - {self.item.item_name}"

class Review(models.Model):
    reviewer = models.ForeignKey(User, on_delete=models.CASCADE)
    item = models.ForeignKey(Item, on_delete=models.CASCADE)
    review = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.review

class Chat(models.Model):
    participants = models.ManyToManyField(User, related_name="chats")
    item = models.ForeignKey(Item, on_delete=models.CASCADE, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Chat {self.id} with participants {[user.id for user in self.participants.all()]}"

class Message(models.Model):
    chat = models.ForeignKey(Chat, on_delete=models.CASCADE, related_name="messages")
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name="sent_messages")
    receiver = models.ForeignKey(User, on_delete=models.CASCADE, related_name="received_messages")
    message = models.TextField()
    message_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Message {self.id} in Chat {self.chat.id}"

class ReportAbuse(models.Model):
    ABUSE_REASONS = [
        ('Fake', 'Fake'),
        ('Damaged', 'Damaged'),
        ('Fraudulent', 'Fraudulent'),
        ('Illegal', 'Illegal'),
        ('Other', 'Other'),
    ]

    STATUS_CHOICES = [
        ('Pending', 'Pending'),
        ('In Review', 'In Review'),
        ('Resolved', 'Resolved'),
        ('Dismissed', 'Dismissed'),
        ('Actioned', 'Actioned'),
    ]
    
    reporter = models.ForeignKey(User, on_delete=models.CASCADE)  # User reporting the abuse
    item = models.ForeignKey(Item, on_delete=models.CASCADE)  # The reported item
    reason = models.CharField(max_length=50, choices=ABUSE_REASONS)  # Reason for abuse report
    description = models.TextField(null=True, blank=True)  # Optional detailed description of the abuse
    created_at = models.DateTimeField(auto_now_add=True)  # Timestamp of when the report was made
    updated_at = models.DateTimeField(auto_now=True)  # Timestamp of when the report was last updated
    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default='Pending')  # Report status

    def __str__(self):
        return f"Report by {self.reporter.username} on {self.item.item_name} - {self.reason}"

class Contact(models.Model):
    name = models.CharField(max_length=255)
    email = models.EmailField()
    phone_number = models.CharField(max_length=20, blank=True, null=True)
    subject = models.CharField(max_length=255)
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} - {self.subject}"

class NewsLetterSubcribers(models.Model):
    name = models.CharField(max_length=255)
    email = models.EmailField(unique=True)
    subscribed_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.email

class FAQ(models.Model):
    CATEGORY_CHOICES = [
        ("Popular", "Popular"),
        ("General Information", "General Information"),
        ("For Sellers", "For Sellers"),
        ("Posting Ad", "Posting Ad"),
        ("Managing Ads", "Managing Ads"),
        ("Pro Sales", "Pro Sales"),
        ("Premium Services", "Premium Services"),
        ("For Buyers", "For Buyers"),
        ("Feedback", "Feedback"),
        ("Jobs And Services", "Jos And Services"),
    ]

    category = models.CharField(max_length=50, choices=CATEGORY_CHOICES, default="General")
    question = models.CharField(max_length=500, unique=True)
    answer = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"[{self.get_category_display()}] {self.question}"

class ActivityLog(models.Model):
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    action = models.TextField()
    ip_address = models.GenericIPAddressField(null=True, blank=True)  # Stores IP
    user_agent = models.TextField(null=True, blank=True)  # Stores Device Info
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} - {self.action} - {self.timestamp}"