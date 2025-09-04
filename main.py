import asyncio
import logging
from contextlib import asynccontextmanager
from typing import List, Optional, Dict, Any

import httpx
import redis.asyncio as aioredis
from fastapi import FastAPI, HTTPException, Depends, Query, Path
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload # For eager loading

# Import database-related modules
from database import init_db, get_async_session, engine, Base
# Import Pydantic models (schemas)
from schemas import (
    UserCreate, User, UserUpdate,
    ProductCreate, Product, ProductUpdate,
    OrderCreate, Order, OrderUpdate,
    ReviewCreate, Review, ReviewUpdate,
    ShippingEstimateRequest, ShippingEstimateResponse
)
# Import SQLAlchemy models
import models
from data_generator import generate_initial_data

# --- Configuration ---
REDIS_URL = "redis://redis:6379" # Assumes Redis is running on 'redis' host, as in docker-compose
EXTERNAL_SHIPPING_API_URL = "http://shipping_api_mock:8001/estimate" # Mock service

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Redis Connection Pool ---
redis_pool = None

# --- Lifespan Management for DB and Redis ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    global redis_pool
    logger.info("Application startup: Initializing database and Redis...")
    # Initialize database (create tables)
    await init_db()
    logger.info("Database tables checked/created.")

    # Populate initial data if needed (can be made conditional)
    # This is a good place for hackathon setup to ensure data exists.
    # For a real app, you might run this as a separate script or conditionally.
    async with engine.connect() as conn:
        # Check if products table is empty before populating
        result = await conn.execute(select(models.Product).limit(1))
        logger.info("Populating initial data...")
        await generate_initial_data(count_users=10000, count_products=20000, count_orders_per_user=5, count_reviews_per_product=3)
        logger.info("Initial data populated.")
        # if result.scalar_one_or_none() is None:
        #     logger.info("No products found. Populating initial data...")
        #     await generate_initial_data(count_users=100000, count_products=200000, count_orders_per_user=5, count_reviews_per_product=3)
        #     logger.info("Initial data populated.")
        # else:
        #     logger.info("Data already exists. Skipping population.")

    # Initialize Redis pool
    try:
        redis_pool = aioredis.ConnectionPool.from_url(REDIS_URL, decode_responses=True)
        # Test Redis connection
        r = aioredis.Redis(connection_pool=redis_pool)
        await r.ping()
        logger.info("Successfully connected to Redis and Redis pool initialized.")
    except Exception as e:
        logger.error(f"Could not connect to Redis: {e}")
        redis_pool = None # Ensure it's None if connection fails

    yield # Application is running

    # Cleanup on shutdown
    if redis_pool:
        await redis_pool.disconnect()
        logger.info("Redis connection pool closed.")
    await engine.dispose()
    logger.info("Database engine disposed.")
    logger.info("Application shutdown complete.")

app = FastAPI(
    title="Hackathon E-commerce API",
    description="A dummy production API with FastAPI, PostgreSQL, and Redis for a test data generation hackathon.",
    version="1.0.0",
    lifespan=lifespan
)

# --- CORS Middleware ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for simplicity in a hackathon
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Dependency for Redis ---
async def get_redis():
    if not redis_pool:
        raise HTTPException(status_code=503, detail="Redis service unavailable")
    return aioredis.Redis(connection_pool=redis_pool)

# --- API Endpoints ---

# --- User Endpoints ---
@app.post("/users/", response_model=User, status_code=201, tags=["Users"])
async def create_user(user_in: UserCreate, db: AsyncSession = Depends(get_async_session)):
    """
    Create a new user.
    - **email**: Must be unique.
    """
    # Check if user already exists
    result = await db.execute(select(models.User).where(models.User.email == user_in.email))
    db_user = result.scalars().first()
    if db_user:
        raise HTTPException(status_code=400, detail="Email already registered")

    # For simplicity, password is not hashed. In a real app, hash passwords!
    db_user = models.User(**user_in.model_dump())
    db.add(db_user)
    await db.commit()
    await db.refresh(db_user)
    logger.info(f"User created: {db_user.email} (ID: {db_user.id})")
    return db_user

@app.get("/users/", response_model=List[User], tags=["Users"])
async def read_users(skip: int = 0, limit: int = 100, db: AsyncSession = Depends(get_async_session)):
    """
    Retrieve a list of users with pagination.
    - **skip**: Number of records to skip.
    - **limit**: Maximum number of records to return.
    """
    result = await db.execute(select(models.User).offset(skip).limit(limit))
    users = result.scalars().all()
    return users

@app.get("/users/{user_id}", response_model=User, tags=["Users"])
async def read_user(user_id: int = Path(..., title="The ID of the user to get", ge=1),
                    db: AsyncSession = Depends(get_async_session)):
    """
    Get a specific user by their ID.
    """
    result = await db.execute(select(models.User).where(models.User.id == user_id))
    db_user = result.scalars().first()
    if db_user is None:
        logger.warning(f"User with ID {user_id} not found.")
        raise HTTPException(status_code=404, detail="User not found")
    return db_user

@app.put("/users/{user_id}", response_model=User, tags=["Users"])
async def update_user(user_id: int, user_in: UserUpdate, db: AsyncSession = Depends(get_async_session)):
    """
    Update an existing user.
    Allows partial updates.
    """
    result = await db.execute(select(models.User).where(models.User.id == user_id))
    db_user = result.scalars().first()
    if db_user is None:
        raise HTTPException(status_code=404, detail="User not found")

    update_data = user_in.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_user, key, value)

    await db.commit()
    await db.refresh(db_user)
    logger.info(f"User updated: {db_user.email} (ID: {db_user.id})")
    return db_user

# --- Product Endpoints ---
@app.post("/products/", response_model=Product, status_code=201, tags=["Products"])
async def create_product(product_in: ProductCreate, db: AsyncSession = Depends(get_async_session), r: aioredis.Redis = Depends(get_redis)):
    """
    Create a new product.
    """
    db_product = models.Product(**product_in.model_dump())
    db.add(db_product)
    await db.commit()
    await db.refresh(db_product)
    logger.info(f"Product created: {db_product.name} (ID: {db_product.id})")
    # Invalidate cache for product list if it exists
    await r.delete("all_products")
    return db_product

@app.get("/products/", response_model=List[Product], tags=["Products"])
async def read_products(
    skip: int = Query(0, ge=0, description="Number of records to skip for pagination"),
    limit: int = Query(100, ge=1, le=500, description="Maximum number of records to return"),
    min_price: Optional[float] = Query(None, ge=0, description="Minimum price of products"),
    max_price: Optional[float] = Query(None, ge=0, description="Maximum price of products"),
    category: Optional[str] = Query(None, description="Filter by product category"),
    db: AsyncSession = Depends(get_async_session),
    r: aioredis.Redis = Depends(get_redis)
):
    """
    Retrieve a list of products with pagination and filtering.
    - Caches the full list of products (without filters) in Redis for 10 minutes.
    """
    # For simplicity, caching is only applied if no filters are active.
    # A more sophisticated caching strategy would be needed for filtered results.
    cache_key = "all_products"
    if skip == 0 and limit == 100 and min_price is None and max_price is None and category is None:
        cached_products_json_list = await r.lrange(cache_key, 0, -1) # Get list of JSON strings
        if cached_products_json_list:
            logger.info("Serving products from Redis cache.")
            # Deserialize each JSON string in the list
            return [Product.model_validate_json(p_json) for p_json in cached_products_json_list]


    query = select(models.Product)
    if min_price is not None:
        query = query.where(models.Product.price >= min_price)
    if max_price is not None:
        query = query.where(models.Product.price <= max_price)
    if category:
        query = query.where(models.Product.category.ilike(f"%{category}%")) # Case-insensitive search

    result = await db.execute(query.offset(skip).limit(limit))
    products = result.scalars().all()

    if skip == 0 and limit == 100 and min_price is None and max_price is None and category is None and products:
        logger.info("Caching all_products list in Redis.")
        # Store as a list of JSON strings
        async with r.pipeline(transaction=True) as pipe:
            await pipe.delete(cache_key) # Ensure clean slate
            for p_model in products: # Iterate over SQLAlchemy model instances
                # Convert model instance to Pydantic model, then to JSON string
                p_schema = Product.model_validate(p_model)
                await pipe.rpush(cache_key, p_schema.model_dump_json())
            await pipe.expire(cache_key, 600)  # Cache for 10 minutes
            await pipe.execute()

    return products

@app.get("/products/{product_id}", response_model=Product, tags=["Products"])
async def read_product(product_id: int = Path(..., title="The ID of the product to get", ge=1),
                       db: AsyncSession = Depends(get_async_session),
                       r: aioredis.Redis = Depends(get_redis)):
    """
    Get a specific product by its ID.
    - Checks Redis cache first. If not found, fetches from DB and caches for 10 minutes.
    """
    cache_key = f"product:{product_id}"
    cached_product = await r.get(cache_key)
    if cached_product:
        logger.info(f"Product {product_id} found in Redis cache.")
        return Product.model_validate_json(cached_product)

    logger.info(f"Product {product_id} not in cache. Fetching from DB.")
    result = await db.execute(select(models.Product).where(models.Product.id == product_id))
    db_product = result.scalars().first()

    if db_product is None:
        logger.warning(f"Product with ID {product_id} not found.")
        raise HTTPException(status_code=404, detail="Product not found")

    # Cache the product
    await r.set(cache_key, Product.model_validate(db_product).model_dump_json(), ex=600) # Cache for 10 minutes
    logger.info(f"Product {product_id} cached in Redis.")
    return db_product

@app.put("/products/{product_id}", response_model=Product, tags=["Products"])
async def update_product(product_id: int, product_in: ProductUpdate,
                         db: AsyncSession = Depends(get_async_session),
                         r: aioredis.Redis = Depends(get_redis)):
    """
    Update an existing product.
    - Invalidates the product's cache in Redis and the `all_products` list cache.
    """
    result = await db.execute(select(models.Product).where(models.Product.id == product_id))
    db_product = result.scalars().first()
    if db_product is None:
        raise HTTPException(status_code=404, detail="Product not found")

    update_data = product_in.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_product, key, value)

    await db.commit()
    await db.refresh(db_product)
    logger.info(f"Product updated: {db_product.name} (ID: {db_product.id})")

    # Invalidate Redis cache for this product and the list
    await r.delete(f"product:{product_id}")
    await r.delete("all_products")
    logger.info(f"Cache invalidated for product {product_id} and all_products list.")
    return db_product

# --- Order Endpoints ---
@app.post("/orders/", response_model=Order, status_code=201, tags=["Orders"])
async def create_order(order_in: OrderCreate, db: AsyncSession = Depends(get_async_session)):
    """
    Create a new order.
    - Validates that `user_id` and `product_id` exist.
    - Calculates `total_price` based on product price and quantity.
    """
    # Validate user exists
    user_result = await db.execute(select(models.User).where(models.User.id == order_in.user_id))
    db_user = user_result.scalars().first()
    if not db_user:
        raise HTTPException(status_code=404, detail=f"User with id {order_in.user_id} not found")

    # Validate product exists
    product_result = await db.execute(select(models.Product).where(models.Product.id == order_in.product_id))
    db_product = product_result.scalars().first()
    if not db_product:
        raise HTTPException(status_code=404, detail=f"Product with id {order_in.product_id} not found")

    if db_product.stock < order_in.quantity:
        raise HTTPException(status_code=400, detail=f"Not enough stock for product {db_product.name}. Available: {db_product.stock}, Requested: {order_in.quantity}")

    total_price = db_product.price * order_in.quantity

    # Create order
    db_order = models.Order(
        user_id=order_in.user_id,
        product_id=order_in.product_id,
        quantity=order_in.quantity,
        status=order_in.status,
        total_price=total_price
    )
    db.add(db_order)

    # Update product stock
    db_product.stock -= order_in.quantity

    await db.commit()
    await db.refresh(db_order)
    await db.refresh(db_product) # Refresh product to reflect stock change in current session if needed elsewhere

    logger.info(f"Order created: ID {db_order.id} for User {order_in.user_id}, Product {order_in.product_id}")
    return db_order


@app.get("/orders/", response_model=List[Order], tags=["Orders"])
async def read_orders(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
    user_id: Optional[int] = Query(None, description="Filter orders by user ID"),
    product_id: Optional[int] = Query(None, description="Filter orders by product ID"),
    status: Optional[str] = Query(None, description="Filter orders by status (e.g., pending, shipped)"),
    db: AsyncSession = Depends(get_async_session)
):
    """
    Retrieve a list of orders with pagination and filtering.
    - Eagerly loads related User and Product information.
    """
    query = select(models.Order).options(
        selectinload(models.Order.user),
        selectinload(models.Order.product)
    )
    if user_id is not None:
        query = query.where(models.Order.user_id == user_id)
    if product_id is not None:
        query = query.where(models.Order.product_id == product_id)
    if status:
        query = query.where(models.Order.status.ilike(f"%{status}%"))

    result = await db.execute(query.order_by(models.Order.order_date.desc()).offset(skip).limit(limit))
    orders = result.scalars().all()
    return orders


@app.get("/orders/{order_id}", response_model=Order, tags=["Orders"])
async def read_order(order_id: int = Path(..., ge=1), db: AsyncSession = Depends(get_async_session)):
    """
    Get a specific order by its ID.
    - Eagerly loads related User and Product information.
    """
    result = await db.execute(
        select(models.Order)
        .where(models.Order.id == order_id)
        .options(selectinload(models.Order.user), selectinload(models.Order.product))
    )
    db_order = result.scalars().first()
    if db_order is None:
        logger.warning(f"Order with ID {order_id} not found.")
        raise HTTPException(status_code=404, detail="Order not found")
    return db_order

@app.put("/orders/{order_id}", response_model=Order, tags=["Orders"])
async def update_order_status(order_id: int, order_in: OrderUpdate, db: AsyncSession = Depends(get_async_session)):
    """
    Update the status of an existing order.
    Only allows updating the 'status' field.
    """
    result = await db.execute(select(models.Order).where(models.Order.id == order_id))
    db_order = result.scalars().first()
    if db_order is None:
        raise HTTPException(status_code=404, detail="Order not found")

    if order_in.status is not None:
        db_order.status = order_in.status
    # Other fields are not updated through this endpoint for simplicity

    await db.commit()
    await db.refresh(db_order)
    logger.info(f"Order ID {order_id} status updated to: {db_order.status}")
    return db_order


# --- Review Endpoints ---
@app.post("/reviews/", response_model=Review, status_code=201, tags=["Reviews"])
async def create_review(review_in: ReviewCreate, db: AsyncSession = Depends(get_async_session)):
    """
    Create a new review for a product by a user.
    - Validates that `user_id` and `product_id` exist.
    - Validates that `rating` is between 1 and 5.
    """
    if not (1 <= review_in.rating <= 5):
        raise HTTPException(status_code=400, detail="Rating must be between 1 and 5")

    # Validate user exists
    user_result = await db.execute(select(models.User).where(models.User.id == review_in.user_id))
    if not user_result.scalars().first():
        raise HTTPException(status_code=404, detail=f"User with id {review_in.user_id} not found")

    # Validate product exists
    product_result = await db.execute(select(models.Product).where(models.Product.id == review_in.product_id))
    if not product_result.scalars().first():
        raise HTTPException(status_code=404, detail=f"Product with id {review_in.product_id} not found")

    # Check if user has already reviewed this product (optional rule)
    existing_review = await db.execute(
        select(models.Review).where(
            models.Review.user_id == review_in.user_id,
            models.Review.product_id == review_in.product_id
        )
    )
    if existing_review.scalars().first():
        raise HTTPException(status_code=400, detail="User has already reviewed this product")


    db_review = models.Review(**review_in.model_dump())
    db.add(db_review)
    await db.commit()
    await db.refresh(db_review)
    logger.info(f"Review created: ID {db_review.id} for Product {review_in.product_id} by User {review_in.user_id}")
    return db_review

@app.get("/products/{product_id}/reviews", response_model=List[Review], tags=["Reviews"])
async def read_reviews_for_product(
    product_id: int = Path(..., ge=1),
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=50),
    min_rating: Optional[int] = Query(None, ge=1, le=5),
    db: AsyncSession = Depends(get_async_session)
):
    """
    Retrieve reviews for a specific product with pagination and optional rating filter.
    - Eagerly loads related User information for each review.
    """
    # Validate product exists
    product_result = await db.execute(select(models.Product).where(models.Product.id == product_id))
    if not product_result.scalars().first():
        raise HTTPException(status_code=404, detail=f"Product with id {product_id} not found")

    query = select(models.Review).where(models.Review.product_id == product_id).options(
        selectinload(models.Review.user) # Eager load user details
    )
    if min_rating is not None:
        query = query.where(models.Review.rating >= min_rating)

    result = await db.execute(query.order_by(models.Review.review_date.desc()).offset(skip).limit(limit))
    reviews = result.scalars().all()
    return reviews

@app.get("/reviews/{review_id}", response_model=Review, tags=["Reviews"])
async def read_review(review_id: int = Path(..., ge=1), db: AsyncSession = Depends(get_async_session)):
    """
    Get a specific review by its ID.
    - Eagerly loads related User and Product information.
    """
    result = await db.execute(
        select(models.Review)
        .where(models.Review.id == review_id)
        .options(selectinload(models.Review.user), selectinload(models.Review.product))
    )
    db_review = result.scalars().first()
    if db_review is None:
        logger.warning(f"Review with ID {review_id} not found.")
        raise HTTPException(status_code=404, detail="Review not found")
    return db_review

@app.put("/reviews/{review_id}", response_model=Review, tags=["Reviews"])
async def update_review(review_id: int, review_in: ReviewUpdate, db: AsyncSession = Depends(get_async_session)):
    """
    Update an existing review.
    Only allows updating `rating` and `comment`.
    """
    result = await db.execute(select(models.Review).where(models.Review.id == review_id))
    db_review = result.scalars().first()
    if db_review is None:
        raise HTTPException(status_code=404, detail="Review not found")

    update_data = review_in.model_dump(exclude_unset=True)
    if "rating" in update_data and not (1 <= update_data["rating"] <= 5):
        raise HTTPException(status_code=400, detail="Rating must be between 1 and 5")

    for key, value in update_data.items():
        setattr(db_review, key, value)

    await db.commit()
    await db.refresh(db_review)
    logger.info(f"Review ID {review_id} updated.")
    return db_review


# --- Simulated External API Endpoint ---
# This endpoint simulates an external shipping service.
# In a real scenario, this would be a separate microservice.
# For the hackathon, it's part of the same app but could be spun off.

@app.post("/shipping/estimate", response_model=ShippingEstimateResponse, tags=["External Services Simulation"])
async def get_shipping_estimate(request_data: ShippingEstimateRequest):
    """
    Simulates an external API call to get a shipping estimate.
    The actual call is made to `shipping_api_mock_app.py` if running with docker-compose.
    If `shipping_api_mock_app.py` is not running, it returns a fallback mock response.
    """
    # Simple mock logic: estimate based on weight and distance
    # In a real app, you'd call an external service here.
    logger.info(f"Received shipping estimate request: {request_data.model_dump_json()}")

    # Try to call the actual mock service
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(EXTERNAL_SHIPPING_API_URL, json=request_data.model_dump())
            response.raise_for_status() # Raise an exception for bad status codes
            estimate_data = response.json()
            logger.info(f"Received shipping estimate from mock service: {estimate_data}")
            return ShippingEstimateResponse(**estimate_data)
    except httpx.RequestError as e:
        logger.error(f"Could not connect to external shipping API mock ({EXTERNAL_SHIPPING_API_URL}): {e}. Using fallback.")
        # Fallback mock logic if the external service is down
        base_cost = 5.0
        cost_per_kg = 2.0
        cost_per_100km = 1.0
        estimated_cost = base_cost + (request_data.weight_kg * cost_per_kg) + (request_data.distance_km * cost_per_100km / 100)
        estimated_days = max(1, int(request_data.distance_km / 500) + int(request_data.weight_kg / 10))
        
        return ShippingEstimateResponse(
            product_id=request_data.product_id,
            destination_zip_code=request_data.destination_zip_code,
            estimated_cost=round(estimated_cost, 2),
            estimated_delivery_days=estimated_days,
            carrier="MockCarrier Express (Fallback)"
        )
    except httpx.HTTPStatusError as e:
        logger.error(f"External shipping API mock returned error {e.response.status_code}: {e.response.text}. Using fallback.")
        # Fallback for HTTP errors from the mock service
        return ShippingEstimateResponse(
            product_id=request_data.product_id,
            destination_zip_code=request_data.destination_zip_code,
            estimated_cost=99.99, # Indicate error with a fixed high price
            estimated_delivery_days=99,
            carrier="ErrorCarrier (Fallback)"
        )

# --- Health Check Endpoint ---
@app.get("/health", status_code=200, tags=["Health"])
async def health_check(db: AsyncSession = Depends(get_async_session), r: aioredis.Redis = Depends(get_redis)):
    """
    Performs a health check on the API and its dependencies (Database, Redis).
    """
    db_ok = False
    redis_ok = False
    try:
        # Test DB connection
        await db.execute(select(1))
        db_ok = True
    except Exception as e:
        logger.error(f"Database health check failed: {e}")

    try:
        # Test Redis connection
        await r.ping()
        redis_ok = True
    except Exception as e:
        logger.error(f"Redis health check failed: {e}")

    if db_ok and redis_ok:
        return {"status": "healthy", "database": "ok", "redis": "ok"}
    else:
        raise HTTPException(
            status_code=503,
            detail={
                "status": "unhealthy",
                "database": "ok" if db_ok else "error",
                "redis": "ok" if redis_ok else "error",
            }
        )

if __name__ == "__main__":
    # This is for running locally without Uvicorn directly for simple testing.
    # For production, use Uvicorn: uvicorn main:app --host 0.0.0.0 --port 8000 --reload
    import uvicorn
    logger.info("Starting application with Uvicorn (for local testing only)...")
    uvicorn.run(app, host="0.0.0.0", port=8000)