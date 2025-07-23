from django.contrib import admin
from .models import *

# Register your models here.
admin.site.register(UserProfile)

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('category_name', 'created_at', 'updated_at')
    search_fields = ('category_name',)
    ordering = ('category_name',)

@admin.register(SubCategory)
class SubCategoryAdmin(admin.ModelAdmin):
    list_display = ('subcategory_name', 'subcategory_category', 'created_at', 'updated_at','metadata')
    list_filter = ('subcategory_category',)  # Enables filtering by Category
    search_fields = ('subcategory_name', 'subcategory_category__category_name')  # Allows searching by subcategory and category name
    ordering = ('subcategory_category', 'subcategory_name')  # Sort by Category, then SubCategory

class ItemImageInline(admin.TabularInline):  # or admin.StackedInline
    model = ItemImage
    extra = 1  # Number of blank image fields to show in the admin panel

@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    inlines = [ItemImageInline]
    list_display = ['item_name', 'item_price', 'item_status', 'created_at', 'updated_at','metadata']
    list_filter = ['item_status']  # Add filter options for statuses
    search_fields = ['item_name', 'item_description']

admin.site.register(ItemImage)
admin.site.register(Wishlist)
admin.site.register(Review)

@admin.register(Chat)
class ChatAdmin(admin.ModelAdmin):
    list_display = ('id', 'get_participants', 'item', 'created_at', 'updated_at')
    search_fields = ('participants__username', 'item__item_name')
    list_filter = ('created_at',)

    def get_participants(self, obj):
        # Display participants as a comma-separated list
        return ", ".join([user.username for user in obj.participants.all()])
    get_participants.short_description = "Participants"

@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ('id', 'chat', 'sender', 'receiver', 'message', 'message_read', 'created_at')
    search_fields = ('sender__username', 'receiver__username', 'message')
    list_filter = ('message_read', 'created_at', 'updated_at')

    def chat(self, obj):
        # Display the chat ID for better context
        return f"Chat {obj.chat.id}"
    chat.short_description = "Chat ID"

class ReportAbuseAdmin(admin.ModelAdmin):
    list_display = ('id', 'reporter', 'item', 'reason', 'status', 'created_at', 'updated_at')
    list_filter = ('status', 'reason', 'created_at')  # Filtering options for admins
    search_fields = ('reporter__username', 'item__item_name', 'description')  # Searchable fields in the admin
    list_editable = ('status',)  # Allow editing status directly from the list view
    ordering = ('-created_at',)  # Sort by creation date (newest first)
    
    fieldsets = (
        (None, {
            'fields': ('reporter', 'item', 'reason', 'description', 'status')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

# Register the ReportAbuse model with the custom admin interface
admin.site.register(ReportAbuse, ReportAbuseAdmin)
admin.site.register(Contact)
admin.site.register(NewsLetterSubcribers)
admin.site.register(FAQ)
admin.site.register(ActivityLog)