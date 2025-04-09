# Dawa-Backend
Dawa Backend

# Views Documentation

## Register

**URL:** `/register/`  
**Method:** `POST`  
**Description:** Registers a new user and sends an OTP for account activation.  
**Request Body:**

- `email`: User's email
- `password`: User's password
- `password2`: Confirmation of the password
- `firstname`: User's first name
- `lastname`: User's last name
- `contact`: User's contact number
- `user_role`: Role of the user

**Response:**

- `201 Created`: User account created and OTP sent.
- `400 Bad Request`: Validation errors or user already exists.
- `500 Internal Server Error`: Failed to create user account.

## GoogleLogin

**URL:** `/google-login/`  
**Method:** `POST`  
**Description:** Logs in a user using Google OAuth2 token.  
**Request Body:**

- `google_token`: Google OAuth2 token
- `user_role`: Role of the user (optional, default is 'Client')

**Response:**

- `200 OK`: Google login successful.
- `201 Created`: New user created using Google login.
- `400 Bad Request`: Invalid Google token or other errors.
- `403 Forbidden`: Invalid token issuer or audience.

## ActivateAccount

**URL:** `/activate-account/`  
**Method:** `POST`  
**Description:** Activates a user account using email and OTP code.  
**Request Body:**

- `email`: User's email
- `otp_code`: OTP code sent to the user's email

**Response:**

- `200 OK`: Account activated successfully.
- `400 Bad Request`: Invalid OTP code.
- `404 Not Found`: User does not exist.
- `500 Internal Server Error`: Failed to activate the user account.

## Login

**URL:** `/login/`  
**Method:** `POST`  
**Description:** Logs in a user using email and password.  
**Request Body:**

- `username`: User's email
- `password`: User's password

**Response:**

- `202 Accepted`: Logged in successfully.
- `400 Bad Request`: Invalid request data.
- `401 Unauthorized`: Invalid password.
- `403 Forbidden`: Account not activated.
- `404 Not Found`: User does not exist.

## GetUserProfile

**URL:** `/get-user-profile/`  
**Method:** `GET`  
**Description:** Retrieves the profile of the authenticated user.  
**Response:**

- `200 OK`: User profile and items data.
- `500 Internal Server Error`: An error occurred.

## GetMyShopProfile

**URL:** `/get-my-shop-profile/`  
**Method:** `GET`  
**Description:** Retrieves the shop profile of the authenticated user.  
**Response:**

- `200 OK`: User profile and items data.
- `500 Internal Server Error`: An error occurred.

## GetShopProfile

**URL:** `/get-shop-profile/`  
**Method:** `POST`  
**Description:** Retrieves the shop profile of a specified user.  
**Request Body:**

- `user_id`: ID of the user

**Response:**

- `200 OK`: User profile and items data.
- `500 Internal Server Error`: An error occurred.

## UpdateUserProfile

**URL:** `/update-user-profile/`  
**Method:** `PATCH`  
**Description:** Updates the profile of the authenticated user.  
**Request Body:**

- `email`: New email (optional)
- `firstname`: New first name (optional)
- `lastname`: New last name (optional)
- `contact`: New contact number (optional)
- `address`: New address (optional)
- `user_profile_picture`: New profile picture (optional)
- `user_national_id_or_passport`: New national ID or passport (optional)
- `scanned_national_id_or_passport_document`: New scanned document (optional)

**Response:**

- `200 OK`: User profile updated successfully.
- `400 Bad Request`: Invalid request data.
- `404 Not Found`: User profile does not exist.

## ReActivateAccount

**URL:** `/reactivate-account/`  
**Method:** `POST`  
**Description:** Reactivates a user account using email and OTP code.  
**Request Body:**

- `email`: User's email
- `otp_code`: OTP code sent to the user's email

**Response:**

- `200 OK`: Account reactivated successfully.
- `400 Bad Request`: Invalid OTP code.
- `404 Not Found`: User does not exist.
- `500 Internal Server Error`: Failed to reactivate the user account.

## ChangePassword

**URL:** `/change-password/`  
**Method:** `POST`  
**Description:** Changes the password of the authenticated user.  
**Request Body:**

- `old_password`: Current password
- `new_password`: New password
- `confirm_password`: Confirmation of the new password

**Response:**

- `200 OK`: Password changed successfully.
- `400 Bad Request`: Invalid request data or old password is incorrect.

## ForgotPassword

**URL:** `/forgot-password/`  
**Method:** `POST`  
**Description:** Sends an OTP to the user's email for password reset.  
**Request Body:**

- `email`: User's email

**Response:**

- `200 OK`: Password reset OTP sent to email.
- `400 Bad Request`: Invalid request data.
- `404 Not Found`: User does not exist.

## ResetPassword

**URL:** `/reset-password/`  
**Method:** `POST`  
**Description:** Resets the user's password using email, OTP, and new password.  
**Request Body:**

- `email`: User's email
- `otp`: OTP code sent to the user's email
- `new_password`: New password
- `confirm_password`: Confirmation of the new password

**Response:**

- `200 OK`: Password reset successfully.
- `400 Bad Request`: Invalid request data or OTP.
- `403 Forbidden`: OTP has expired or is invalid.
- `404 Not Found`: User does not exist.

## ResendOTP

**URL:** `/resend-otp/`  
**Method:** `POST`  
**Description:** Resends an OTP to the user's email for account activation or password reset.  
**Request Body:**

- `email`: User's email
- `purpose`: Purpose of the OTP ('forgot_password', 'activate', 'reactivate')

**Response:**

- `200 OK`: OTP resent successfully.
- `400 Bad Request`: Invalid request data or purpose.
- `404 Not Found`: User does not exist.

## GetCategoriesWithSubcategories

**URL:** `/get-categories-with-subcategories/`  
**Method:** `GET`  
**Description:** Retrieves all categories with their subcategories and item counts.  
**Response:**

- `200 OK`: Categories and subcategories data.
- `400 Bad Request`: An error occurred.

## AddItem

**URL:** `/add-item/`  
**Method:** `POST`  
**Description:** Adds a new item for the authenticated user.  
**Request Body:**

- `item_name`: Name of the item
- `item_price`: Price of the item
- `item_location`: Location of the item
- `item_negotiable`: Whether the item price is negotiable
- `item_subcategory_id`: ID of the subcategory
- `item_status`: Status of the item
- `item_description`: Description of the item
- `images`: List of images for the item

**Response:**

- `201 Created`: Item and images added successfully.
- `400 Bad Request`: Invalid request data.
- `404 Not Found`: User profile not found.

## UpdateItem

**URL:** `/update-item/`  
**Method:** `PATCH`  
**Description:** Updates an existing item for the authenticated user.  
**Request Body:**

- `item_id`: ID of the item
- `item_name`: New name of the item (optional)
- `item_price`: New price of the item (optional)
- `item_location`: New location of the item (optional)
- `item_negotiable`: Whether the item price is negotiable (optional)
- `item_status`: New status of the item (optional)
- `item_description`: New description of the item (optional)
- `item_subcategory_id`: New ID of the subcategory (optional)
- `images`: List of new images for the item (optional)

**Response:**

- `200 OK`: Item updated successfully.
- `400 Bad Request`: Invalid request data.
- `403 Forbidden`: User not authorized to update the item.
- `404 Not Found`: Item not found.

## DeleteItemImage

**URL:** `/delete-item-image/`  
**Method:** `DELETE`  
**Description:** Deletes an image of an item for the authenticated user.  
**Request Body:**

- `image_id`: ID of the image

**Response:**

- `200 OK`: Image deleted successfully.
- `400 Bad Request`: Invalid request data.
- `403 Forbidden`: User not authorized to delete the image.
- `404 Not Found`: Image not found.

## GetItems

**URL:** `/get-items/`  
**Method:** `POST`  
**Description:** Retrieves items based on category and subcategory filters with pagination.  
**Request Body:**

- `category_id`: ID of the category (optional)
- `subcategory_id`: ID of the subcategory (optional)

**Response:**

- `200 OK`: Items data with pagination.
- `400 Bad Request`: An error occurred.

## GetItemDetails

**URL:** `/get-item-details/`  
**Method:** `POST`  
**Description:** Retrieves details of a specific item.  
**Request Body:**

- `item_id`: ID of the item

**Response:**

- `200 OK`: Item details data.
- `400 Bad Request`: An error occurred.
- `404 Not Found`: Item not found.

## GetItemsPromoted

**URL:** `/get-items-promoted/`  
**Method:** `GET`  
**Description:** Retrieves promoted items.  
**Response:**

- `200 OK`: Promoted items data.
- `400 Bad Request`: An error occurred.

## WishUnWish

**URL:** `/wish-unwish/`  
**Method:** `POST`  
**Description:** Adds or removes an item from the authenticated user's wishlist.  
**Request Body:**

- `item_id`: ID of the item

**Response:**

- `200 OK`: Item added to or removed from wishlist.
- `201 Created`: Item added to wishlist.
- `400 Bad Request`: Invalid request data.
- `404 Not Found`: Item not found.

## GetUserWishlist

**URL:** `/get-user-wishlist/`  
**Method:** `GET`  
**Description:** Retrieves the wishlist of the authenticated user.  
**Response:**

- `200 OK`: Wishlist data.
- `400 Bad Request`: An error occurred.

## SendMessage

**URL:** `/send-message/`  
**Method:** `POST`  
**Description:** Sends a message to another user regarding an item.  
**Request Body:**

- `receiver_id`: ID of the receiver
- `item_id`: ID of the item
- `message`: Message content

**Response:**

- `201 Created`: Message sent successfully.
- `400 Bad Request`: Invalid request data or user cannot send a message to themselves.
- `404 Not Found`: Receiver or item not found.

## GetChatsWithMessages

**URL:** `/get-chats-with-messages/`  
**Method:** `GET`  
**Description:** Retrieves chats and messages for the authenticated user.  
**Response:**

- `200 OK`: Chats and messages data.
- `500 Internal Server Error`: An error occurred.

## SubmitReview

**URL:** `/submit-review/`  
**Method:** `POST`  
**Description:** Submits a review for an item.  
**Request Body:**

- `item_id`: ID of the item
- `review`: Review text

**Response:**

- `201 Created`: Review submitted successfully.
- `400 Bad Request`: Invalid request data or user has already reviewed the item.
- `404 Not Found`: Item not found.

## MakeReportOfAbuse

**URL:** `/make-report-of-abuse/`  
**Method:** `POST`  
**Description:** Submits a report of abuse for an item.  
**Request Body:**

- `item_id`: ID of the item
- `reason`: Reason for the report
- `description`: Description of the report

**Response:**

- `201 Created`: Abuse report submitted successfully.
- `400 Bad Request`: Invalid request data.
- `404 Not Found`: Item not found.

## ContactUs

**URL:** `/contact-us/`  
**Method:** `POST`  
**Description:** Submits a contact request.  
**Request Body:**

- `name`: Name of the sender
- `email`: Email of the sender
- `phone_number`: Phone number of the sender
- `subject`: Subject of the message
- `message`: Message content

**Response:**

- `201 Created`: Contact request submitted successfully.
- `400 Bad Request`: Invalid request data.

## AddNewsLetterSubcriber

**URL:** `/add-newsletter-subscriber/`  
**Method:** `POST`  
**Description:** Adds a new subscriber to the newsletter.  
**Request Body:**

- `name`: Name of the subscriber
- `email`: Email of the subscriber

**Response:**

- `201 Created`: Subscriber added successfully.
- `400 Bad Request`: Invalid request data.

## GetFAQs

**URL:** `/get-faqs/`  
**Method:** `GET`  
**Description:** Retrieves all FAQs.  
**Response:**

- `200 OK`: FAQs data.

## SearchItems

**URL:** `/search-items/`  
**Method:** `POST`  
**Description:** Searches for items based on a query.  
**Request Body:**

- `search_query`: Search query

**Response:**

- `200 OK`: Search results data.
- `400 Bad Request`: An error occurred.


# Models Documentation

## UserProfile

**Description:** Stores additional information about the user.

**Attributes:**

- `Client (str)`: Role choice for Client.
- `Vendor (str)`: Role choice for Vendor.
- `Admin (str)`: Role choice for Admin.
- `ROLE_CHOICES (list)`: List of tuples containing role choices.
- `user (OneToOneField)`: One-to-one relationship with the User model.
- `contact (CharField)`: Contact information of the user.
- `address (CharField)`: Address of the user.
- `user_profile_picture (URLField)`: URL of the user's profile picture.
- `user_national_id_or_passport (CharField)`: National ID or passport number of the user.
- `scanned_national_id_or_passport_document (URLField)`: URL of the scanned national ID or passport document.
- `otp_code (PositiveBigIntegerField)`: One-time password code for the user.
- `otp_created_at (DateTimeField)`: Timestamp when the OTP was created.
- `user_role (CharField)`: Role of the user, chosen from ROLE_CHOICES.
- `created_at (DateTimeField)`: Timestamp when the user profile was created.
- `updated_at (DateTimeField)`: Timestamp when the user profile was last updated.

**Methods:**

- `save(*args, **kwargs)`: Custom save method to handle file uploads to Cloudinary.
- `__str__()`: Returns the email of the associated user as the string representation of the UserProfile.

## Category

**Description:** Stores information about item categories.

**Attributes:**

- `category_name (CharField)`: Name of the category.
- `created_at (DateTimeField)`: Timestamp when the category was created.
- `updated_at (DateTimeField)`: Timestamp when the category was last updated.

**Methods:**

- `__str__()`: Returns the name of the category.

## SubCategory

**Description:** Stores information about item subcategories.

**Attributes:**

- `subcategory_name (CharField)`: Name of the subcategory.
- `subcategory_category (ForeignKey)`: Foreign key to the Category model.
- `created_at (DateTimeField)`: Timestamp when the subcategory was created.
- `updated_at (DateTimeField)`: Timestamp when the subcategory was last updated.

**Methods:**

- `__str__()`: Returns the name of the subcategory.

## Item

**Description:** Stores information about items.

**Attributes:**

- `STATUS_CHOICES (list)`: List of tuples containing status choices.
- `seller (ForeignKey)`: Foreign key to the User model.
- `item_name (CharField)`: Name of the item.
- `item_price (DecimalField)`: Price of the item.
- `item_location (CharField)`: Location of the item.
- `item_negotiable (BooleanField)`: Whether the item price is negotiable.
- `item_promoted (BooleanField)`: Whether the item is promoted.
- `slug (SlugField)`: Unique slug for the item.
- `item_subcategory (ForeignKey)`: Foreign key to the SubCategory model.
- `item_status (CharField)`: Status of the item, chosen from STATUS_CHOICES.
- `item_description (TextField)`: Description of the item.
- `created_at (DateTimeField)`: Timestamp when the item was created.
- `updated_at (DateTimeField)`: Timestamp when the item was last updated.

**Methods:**

- `__str__()`: Returns the name of the item and the username of the seller.

## ItemImage

**Description:** Stores images for items.

**Attributes:**

- `item (ForeignKey)`: Foreign key to the Item model.
- `image (URLField)`: URL of the image.
- `uploaded_at (DateTimeField)`: Timestamp when the image was uploaded.

**Methods:**

- `save(*args, **kwargs)`: Custom save method to handle file uploads to Cloudinary.
- `__str__()`: Returns a string representation of the image for the item.

## Wishlist

**Description:** Stores wishlist items for users.

**Attributes:**

- `user (ForeignKey)`: Foreign key to the User model.
- `item (ForeignKey)`: Foreign key to the Item model.
- `is_wished (BooleanField)`: Whether the item is wished.
- `created_at (DateTimeField)`: Timestamp when the wishlist item was created.
- `updated_at (DateTimeField)`: Timestamp when the wishlist item was last updated.

**Methods:**

- `__str__()`: Returns a string representation of the wishlist item.

## Review

**Description:** Stores reviews for items.

**Attributes:**

- `reviewer (ForeignKey)`: Foreign key to the User model.
- `item (ForeignKey)`: Foreign key to the Item model.
- `review (TextField)`: Review text.
- `created_at (DateTimeField)`: Timestamp when the review was created.
- `updated_at (DateTimeField)`: Timestamp when the review was last updated.

**Methods:**

- `__str__()`: Returns the review text.

## Chat

**Description:** Stores chat information between users.

**Attributes:**

- `participants (ManyToManyField)`: Many-to-many relationship with the User model.
- `item (ForeignKey)`: Foreign key to the Item model.
- `created_at (DateTimeField)`: Timestamp when the chat was created.
- `updated_at (DateTimeField)`: Timestamp when the chat was last updated.

**Methods:**

- `__str__()`: Returns a string representation of the chat with participant IDs.

## Message

**Description:** Stores messages in chats.

**Attributes:**

- `chat (ForeignKey)`: Foreign key to the Chat model.
- `sender (ForeignKey)`: Foreign key to the User model for the sender.
- `receiver (ForeignKey)`: Foreign key to the User model for the receiver.
- `message (TextField)`: Message text.
- `message_read (BooleanField)`: Whether the message has been read.
- `created_at (DateTimeField)`: Timestamp when the message was created.
- `updated_at (DateTimeField)`: Timestamp when the message was last updated.

**Methods:**

- `__str__()`: Returns a string representation of the message in the chat.

## ReportAbuse

**Description:** Stores abuse reports for items.

**Attributes:**

- `ABUSE_REASONS (list)`: List of tuples containing abuse reasons.
- `STATUS_CHOICES (list)`: List of tuples containing status choices.
- `reporter (ForeignKey)`: Foreign key to the User model for the reporter.
- `item (ForeignKey)`: Foreign key to the Item model.
- `reason (CharField)`: Reason for the abuse report.
- `description (TextField)`: Detailed description of the abuse.
- `created_at (DateTimeField)`: Timestamp when the report was created.
- `updated_at (DateTimeField)`: Timestamp when the report was last updated.
- `status (CharField)`: Status of the report, chosen from STATUS_CHOICES.

**Methods:**

- `__str__()`: Returns a string representation of the abuse report.

## Contact

**Description:** Stores contact requests from users.

**Attributes:**

- `name (CharField)`: Name of the sender.
- `email (EmailField)`: Email of the sender.
- `phone_number (CharField)`: Phone number of the sender.
- `subject (CharField)`: Subject of the message.
- `message (TextField)`: Message content.
- `created_at (DateTimeField)`: Timestamp when the contact request was created.

**Methods:**

- `__str__()`: Returns a string representation of the contact request.

## NewsLetterSubcribers

**Description:** Stores newsletter subscribers.

**Attributes:**

- `name (CharField)`: Name of the subscriber.
- `email (EmailField)`: Email of the subscriber.
- `subscribed_at (DateTimeField)`: Timestamp when the subscription was created.

**Methods:**

- `__str__()`: Returns the email of the subscriber.

## FAQ

**Description:** Stores frequently asked questions.

**Attributes:**

- `CATEGORY_CHOICES (list)`: List of tuples containing category choices.
- `category (CharField)`: Category of the FAQ.
- `question (CharField)`: Question text.
- `answer (TextField)`: Answer text.
- `created_at (DateTimeField)`: Timestamp when the FAQ was created.
- `updated_at (DateTimeField)`: Timestamp when the FAQ was last updated.

**Methods:**

- `__str__()`: Returns a string representation of the FAQ.

## ActivityLog

**Description:** Stores activity logs for users.

**Attributes:**

- `user (ForeignKey)`: Foreign key to the User model.
- `action (TextField)`: Description of the action.
- `ip_address (GenericIPAddressField)`: IP address of the user.
- `user_agent (TextField)`: User agent information of the user's device.
- `timestamp (DateTimeField)`: Timestamp when the activity was logged.

**Methods:**

- `__str__()`: Returns a string representation of the activity log.

# URLs Documentation

## Authentication
- **URL:** `/register/`
  - **View:** `views.Register`
  - **Description:** Registers a new user.

- **URL:** `/activateaccount/`
  - **View:** `views.ActivateAccount`
  - **Description:** Activates a user account using email and OTP code.

- **URL:** `/login/`
  - **View:** `views.Login`
  - **Description:** Logs in a user using email and password.

- **URL:** `/googlelogin/`
  - **View:** `views.GoogleLogin`
  - **Description:** Logs in a user using Google OAuth2 token.

- **URL:** `/changepassword/`
  - **View:** `views.ChangePassword`
  - **Description:** Changes the password of the authenticated user.

- **URL:** `/forgotpassword/`
  - **View:** `views.ForgotPassword`
  - **Description:** Sends an OTP to the user's email for password reset.

- **URL:** `/resetpassword/`
  - **View:** `views.ResetPassword`
  - **Description:** Resets the user's password using email, OTP, and new password.

- **URL:** `/resendotp/`
  - **View:** `views.ResendOTP`
  - **Description:** Resends an OTP to the user's email for account activation or password reset.

## User Profile
- **URL:** `/getuserprofile/`
  - **View:** `views.GetUserProfile`
  - **Description:** Retrieves the profile of the authenticated user.

- **URL:** `/updateuserprofile/`
  - **View:** `views.UpdateUserProfile`
  - **Description:** Updates the profile of the authenticated user.

- **URL:** `/getmyshopprofile/`
  - **View:** `views.GetMyShopProfile`
  - **Description:** Retrieves the shop profile of the authenticated user.

- **URL:** `/getshopprofile/`
  - **View:** `views.GetShopProfile`
  - **Description:** Retrieves the shop profile of a specified user.

## Items
- **URL:** `/getcategories/`
  - **View:** `views.GetCategoriesWithSubcategories`
  - **Description:** Retrieves all categories with their subcategories and item counts.

- **URL:** `/additem/`
  - **View:** `views.AddItem`
  - **Description:** Adds a new item for the authenticated user.

- **URL:** `/updateitem/`
  - **View:** `views.UpdateItem`
  - **Description:** Updates an existing item for the authenticated user.

- **URL:** `/deleteitemimage/`
  - **View:** `views.DeleteItemImage`
  - **Description:** Deletes an image of an item for the authenticated user.

- **URL:** `/getitems/`
  - **View:** `views.GetItems`
  - **Description:** Retrieves items based on category and subcategory filters with pagination.

- **URL:** `/getitemdetails/`
  - **View:** `views.GetItemDetails`
  - **Description:** Retrieves details of a specific item.

- **URL:** `/getitemspromoted/`
  - **View:** `views.GetItemsPromoted`
  - **Description:** Retrieves promoted items.

- **URL:** `/wishunwish/`
  - **View:** `views.WishUnWish`
  - **Description:** Adds or removes an item from the authenticated user's wishlist.

- **URL:** `/getuserwishlist/`
  - **View:** `views.GetUserWishlist`
  - **Description:** Retrieves the wishlist of the authenticated user.

## Messaging
- **URL:** `/sendmessage/`
  - **View:** `views.SendMessage`
  - **Description:** Sends a message to another user regarding an item.

- **URL:** `/getchatswithmessages/`
  - **View:** `views.GetChatsWithMessages`
  - **Description:** Retrieves chats and messages for the authenticated user.

## Reviews and Reports
- **URL:** `/submitreview/`
  - **View:** `views.SubmitReview`
  - **Description:** Submits a review for an item.

- **URL:** `/makereportofabuse/`
  - **View:** `views.MakeReportOfAbuse`
  - **Description:** Submits a report of abuse for an item.

## Contact and Subscription
- **URL:** `/contactus/`
  - **View:** `views.ContactUs`
  - **Description:** Submits a contact request.

- **URL:** `/subscribe/`
  - **View:** `views.AddNewsLetterSubcriber`
  - **Description:** Adds a new subscriber to the newsletter.

## FAQs
- **URL:** `/getfaqs/`
  - **View:** `views.GetFAQs`
  - **Description:** Retrieves all FAQs.

## Search
- **URL:** `/searchitems/`
  - **View:** `views.SearchItems`
  - **Description:** Searches for items based on a query.