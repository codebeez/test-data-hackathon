from typing import Optional, List
from pydantic import BaseModel, EmailStr, Field, conint
from datetime import datetime

# --- Base Models ---
class UserBase(BaseModel):
    email: EmailStr
    full_name: Optional[str] = None
    is_active: bool = True

class UserCreate(UserBase):
    password: str # In a real app, this would be handled more securely

class UserUpdate(BaseModel):
    email: Optional[EmailStr] = None
    full_name: Optional[str] = None
    is_active: Optional[bool] = None
    # Password updates would typically be a separate, more secure process

class User(UserBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True # Changed from orm_mode for Pydantic v2

class ProductBase(BaseModel):
    name: str = Field(..., min_length=3, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    price: float = Field(..., gt=0)
    category: Optional[str] = Field(None, max_length=50)
    stock: int = Field(..., ge=0)

class ProductCreate(ProductBase):
    pass

class ProductUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=3, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    price: Optional[float] = Field(None, gt=0)
    category: Optional[str] = Field(None, max_length=50)
    stock: Optional[int] = Field(None, ge=0)

class Product(ProductBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True

class OrderBase(BaseModel):
    user_id: int
    product_id: int
    quantity: conint(gt=0) # quantity must be greater than 0
    status: str = Field("pending", examples=["pending", "shipped", "delivered", "cancelled"])

class OrderCreate(OrderBase):
    pass

class OrderUpdate(BaseModel):
    status: Optional[str] = Field(None, examples=["pending", "shipped", "delivered", "cancelled"])
    # Other fields like quantity, product_id are generally not updated post-creation
    # or would involve more complex logic (e.g., cancellations, returns)

class Order(OrderBase):
    id: int
    order_date: datetime
    total_price: float
    user: Optional[User] = None # For nested response
    product: Optional[Product] = None # For nested response

    class Config:
        from_attributes = True

class ReviewBase(BaseModel):
    user_id: int
    product_id: int
    rating: conint(ge=1, le=5) # Rating between 1 and 5
    comment: Optional[str] = Field(None, max_length=1000)

class ReviewCreate(ReviewBase):
    pass

class ReviewUpdate(BaseModel):
    rating: Optional[conint(ge=1, le=5)] = None
    comment: Optional[str] = Field(None, max_length=1000)

class Review(ReviewBase):
    id: int
    review_date: datetime
    user: Optional[User] = None # For nested response
    product: Optional[Product] = None # For nested response (less common to nest product here, user is more typical)

    class Config:
        from_attributes = True


# --- Schemas for Simulated External API ---
class ShippingEstimateRequest(BaseModel):
    product_id: int
    destination_zip_code: str = Field(..., pattern=r"^\d{5}(-\d{4})?$") # US ZIP code format
    weight_kg: float = Field(..., gt=0)
    distance_km: float = Field(..., gt=0)

class ShippingEstimateResponse(BaseModel):
    product_id: int
    destination_zip_code: str
    estimated_cost: float
    estimated_delivery_days: int
    carrier: str