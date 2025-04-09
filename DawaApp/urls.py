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
]