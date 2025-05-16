import asyncio
import random
from faker import Faker
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

# Import models and database session
import models
from database import AsyncSessionFactory, engine # Import engine for direct connection if needed
from schemas import UserCreate, ProductCreate, OrderCreate, ReviewCreate # For type hints and structure

fake = Faker()
# Faker.seed(0) # Optional: for reproducible fake data

# --- Helper Functions for Data Generation ---

async def create_fake_users(db: AsyncSession, count: int = 10) -> list[models.User]:
    """Generates and saves fake users to the database."""
    users = []
    for _ in range(count):
        # Ensure email is unique (Faker might occasionally repeat)
        email = fake.unique.email()
        # Check if user already exists (less likely with unique.email but good practice)
        result = await db.execute(select(models.User).where(models.User.email == email))
        if result.scalars().first():
            continue # Skip if email somehow exists

        user_data = UserCreate(
            email=email,
            full_name=fake.name(),
            password=fake.password(length=12) # Plain text for hackathon simplicity
        )
        user = models.User(**user_data.model_dump())
        db.add(user)
        users.append(user)
    await db.commit()
    for user_obj in users: # Refresh to get IDs (renamed to avoid conflict)
        await db.refresh(user_obj)
    print(f"Generated and saved {len(users)} users.")
    return users

async def create_fake_products(db: AsyncSession, count: int = 50) -> list[models.Product]:
    """Generates and saves fake products to the database."""
    products = []
    categories = ["Electronics", "Books", "Clothing", "Home & Kitchen", "Sports & Outdoors", "Toys & Games", "Beauty", "Automotive"]
    for _ in range(count):
        product_data = ProductCreate(
            name=fake.bs().title(), # Changed from fake.ecommerce_name() to fake.bs() and title cased
            description=fake.text(max_nb_chars=200),
            price=round(random.uniform(5.0, 500.0), 2),
            category=random.choice(categories),
            stock=random.randint(0, 200)
        )
        product = models.Product(**product_data.model_dump())
        db.add(product)
        products.append(product)
    await db.commit()
    for prod in products: # Refresh to get IDs
        await db.refresh(prod)
    print(f"Generated and saved {len(products)} products.")
    return products

async def create_fake_orders(db: AsyncSession, users: list[models.User], products: list[models.Product], orders_per_user: int = 3) -> list[models.Order]:
    """Generates and saves fake orders to the database."""
    if not users or not products:
        print("Cannot create orders without users and products.")
        return []

    orders_list = []
    statuses = ["pending", "shipped", "delivered", "cancelled"]
    for user_obj in users: # Renamed to avoid conflict
        num_orders = random.randint(1, orders_per_user)
        for _ in range(num_orders):
            product = random.choice(products)
            quantity = random.randint(1, 5)

            if product.stock < quantity: # Check stock before creating order
                # print(f"Skipping order for product {product.name} due to insufficient stock ({product.stock} < {quantity}).")
                continue # Skip if not enough stock

            total_price = round(product.price * quantity, 2)
            order_data = OrderCreate(
                user_id=user_obj.id, # Use user_obj
                product_id=product.id,
                quantity=quantity,
                status=random.choice(statuses)
                # total_price is calculated in the endpoint, but we can set it here for direct creation
            )
            order = models.Order(**order_data.model_dump(), total_price=total_price) # Pass total_price explicitly

            # Update product stock (important for consistency)
            product.stock -= quantity
            # db.add(product) # Not strictly necessary to add again if it's already managed by session and modified
            
            db.add(order)
            orders_list.append(order)

    await db.commit() # Commit all orders and stock updates together
    for o in orders_list: # Refresh to get IDs
        await db.refresh(o)
    # No need to refresh products here again unless their IDs or other auto-generated fields are needed immediately after this block
    print(f"Generated and saved {len(orders_list)} orders.")
    return orders_list

async def create_fake_reviews(db: AsyncSession, users: list[models.User], products: list[models.Product], reviews_per_product: int = 2) -> list[models.Review]:
    """Generates and saves fake reviews to the database."""
    if not users or not products:
        print("Cannot create reviews without users and products.")
        return []

    reviews_list = []
    for product in products:
        # Select a subset of users to review this product to avoid too many reviews
        reviewers = random.sample(users, min(len(users), random.randint(1, reviews_per_product + 2)))
        for user_obj in reviewers: # Renamed to avoid conflict
            # Check if this user has already reviewed this product
            result = await db.execute(
                select(models.Review).where(
                    models.Review.user_id == user_obj.id, # Use user_obj
                    models.Review.product_id == product.id
                )
            )
            if result.scalars().first():
                continue # Skip if already reviewed

            review_data = ReviewCreate(
                user_id=user_obj.id, # Use user_obj
                product_id=product.id,
                rating=random.randint(1, 5),
                comment=fake.paragraph(nb_sentences=random.randint(1,3)) if random.choice([True, False]) else None
            )
            review = models.Review(**review_data.model_dump())
            db.add(review)
            reviews_list.append(review)
    await db.commit()
    for r_obj in reviews_list: # Renamed to avoid conflict
        await db.refresh(r_obj)
    print(f"Generated and saved {len(reviews_list)} reviews.")
    return reviews_list

# --- Main Data Generation Function ---
async def generate_initial_data(
    count_users: int = 5000,
    count_products: int = 10000,
    count_orders_per_user: int = 5,
    count_reviews_per_product: int = 3
):
    """
    Main function to generate all initial data.
    This is called from main.py during application startup if tables are empty.
    """
    print("Starting initial data generation...")
    async_session = AsyncSessionFactory()
    try:
        # Check if data already exists to prevent re-population (simplified check)
        # This check is also done in main.py's lifespan, but good to have here for standalone use
        async with engine.connect() as conn: # Use engine for a quick check
            result = await conn.execute(select(models.User).limit(1))
            if result.scalar_one_or_none() is not None:
                print("Data seems to already exist (checked in data_generator). Skipping generation.")
                return

        print(f"Generating {count_users} users...")
        users_list = await create_fake_users(async_session, count_users) # Renamed variable

        print(f"Generating {count_products} products...")
        products_list = await create_fake_products(async_session, count_products) # Renamed variable

        print(f"Generating up to {count_orders_per_user} orders per user...")
        await create_fake_orders(async_session, users_list, products_list, count_orders_per_user)

        print(f"Generating up to {count_reviews_per_product} reviews per product...")
        await create_fake_reviews(async_session, users_list, products_list, count_reviews_per_product)

        # Final commit is handled by individual create_fake_* functions now,
        # or by the get_async_session context manager if called from an endpoint.
        # If running standalone, ensure commits are within each helper or here.
        # For safety, an explicit commit here if any operations might be pending outside helpers.
        # await async_session.commit() # This might be redundant if helpers commit.

        print("Initial data generation completed successfully.")

    except Exception as e:
        await async_session.rollback()
        print(f"An error occurred during data generation: {e}")
        # Consider re-raising or logging more formally
    finally:
        await async_session.close()

# --- Script Execution (for standalone generation) ---
if __name__ == "__main__":
    # This allows running `python data_generator.py` to populate the DB.
    # Ensure your DB is running and accessible.
    print("Running data generator script directly...")

    async def main_standalone(): # Renamed to avoid conflict with main.py's main
        # Initialize DB (create tables if they don't exist)
        async with engine.begin() as conn:
            # await conn.run_sync(models.Base.metadata.drop_all) # Uncomment to clear DB first
            await conn.run_sync(models.Base.metadata.create_all)
        
        await generate_initial_data(
            count_users=50,       # Example: Generate 50 users
            count_products=200,   # Example: Generate 200 products
            count_orders_per_user=5, # Avg orders per user
            count_reviews_per_product=3 # Avg reviews per product
        )

    asyncio.run(main_standalone())