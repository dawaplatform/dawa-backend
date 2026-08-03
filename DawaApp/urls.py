from django.urls import path
from . import views

urlpatterns = [
    #AUTH
    path('register/', views.Register),
    path('activateaccount/', views.ActivateAccount),
    path('login/', views.Login),
    path('googlelogin/', views.GoogleLogin),
    path('getuserprofile/', views.GetUserProfile),
    path('updateuserprofile/', views.UpdateUserProfile),
    path('getcategories/', views.GetCategoriesWithSubcategories),
    path('additem/', views.AddItem),
    path('updateitem/', views.UpdateItem),
    path('deleteitemimage/', views.DeleteItemImage),
    path('getitems/', views.GetItems),
    path('getitemdetails/', views.GetItemDetails),
    path('getitemspromoted/', views.GetItemsPromoted),
    path('wishunwish/', views.WishUnWish),
    path('getuserwishlist/', views.GetUserWishlist),
    path('sendmessage/', views.SendMessage),
    path('getchatswithmessages/', views.GetChatsWithMessages),
    path('markchatread/', views.MarkChatRead),

    path('deleteaccount/', views.DeleteAccount),
    path('deletemydata/', views.DeleteMyData),
    path('deleteitem/', views.DeleteItem),

    path('changepassword/', views.ChangePassword),
    path('forgotpassword/', views.ForgotPassword),
    path('resetpassword/', views.ResetPassword),
    path('resendotp/', views.ResendOTP),

    path('submitreview/', views.SubmitReview),
    path('makereportofabuse/', views.MakeReportOfAbuse),

    path('getmyshopprofile/', views.GetMyShopProfile),
    path('getshopprofile/', views.GetShopProfile),

    path('contactus/', views.ContactUs),

    path('subscribe/', views.AddNewsLetterSubcriber),

    path('getfaqs/', views.GetFAQs),

    path('searchitems/', views.SearchItems),

    path('getallitemsadmin/', views.GetAllItemsAdmin),
    path('getitemdetailsadmin/', views.GetItemDetailsAdmin),
    path('updateitemapprovalstatus/', views.UpdateItemApprovalStatus),
    path('getallusersadmin/', views.GetAllUsersAdmin),
    path('changeuserroleadmin/', views.ChangeUserRoleAdmin),
    path('deleteuseradmin/', views.DeleteUserAdmin),
    path('updateuseradmin/', views.UpdateUserAdmin),
    path('admindashboardstats/', views.AdminDashboardStats),
    path('adminanalytics/', views.AdminAnalytics),
    
    # Category and Subcategory Admin URLs
    path('categoryAdminAdd/', views.AddCategory),
    path('categoryAdminGetAll/', views.GetAllCategories),
    path('categoryAdminUpdate/', views.UpdateCategory),
    path('categoryAdminDelete/', views.DeleteCategory),
    path('subcategoryAdminAdd/', views.AddSubcategory),
    path('subcategoryAdminGetAll/', views.GetAllSubcategories),
    path('subcategoryAdminUpdate/', views.UpdateSubcategory),
    path('subcategoryAdminDelete/', views.DeleteSubcategory),
    
    # Item Promotion Admin URL
    path('updateItemPromotedStatus/', views.UpdateItemPromotedStatus),

    # New Item Listing Views
    path('premiumitems/', views.getPremiumSection),
    path('trendingitems/', views.getTrendingProducts),
    path('productlisting/', views.getProductListing),
    
    # Subscription management
    path('updateitemsubscription/', views.updateItemSubscription),
    path('subscriptionstats/', views.getSubscriptionStats),

    # Admin: message safety purge
    path('admin/purge-unsafe-messages/', views.PurgeUnsafeMessages),
]