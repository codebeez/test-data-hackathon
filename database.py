import logging
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base

# --- Configuration ---
# Ensure these match your docker-compose.yml or local setup
DATABASE_URL = "postgresql://hackathon_user:7ylRKOD7JP5Ham9V64c6624sXp0MXFEh@dpg-d144d5fdiees73ari230-a/hackathon_db_hy6g"
# For local testing without Docker, you might use:
# DATABASE_URL = "postgresql+asyncpg://your_local_user:your_local_pass@localhost/your_local_db"

logger = logging.getLogger(__name__)

# --- SQLAlchemy Engine Setup ---
# `echo=True` is useful for debugging SQL queries during development
engine = create_async_engine(DATABASE_URL, echo=False, future=True)

# --- SQLAlchemy Session Factory ---
# expire_on_commit=False is often recommended for FastAPI with async sessions
AsyncSessionFactory = sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    future=True
)

# --- Base for Declarative Models ---
# All SQLAlchemy models will inherit from this Base
Base = declarative_base()

# --- Database Initialization ---
async def init_db():
    """
    Initializes the database by creating all tables defined in the models.
    This should be called once at application startup.
    """
    async with engine.begin() as conn:
        logger.info("Dropping all tables (if they exist) and recreating for a fresh start...")
        # For a hackathon, dropping and recreating can be useful for a clean slate.
        # In production, you'd use migrations (e.g., Alembic).
        # await conn.run_sync(Base.metadata.drop_all) # Careful with this in prod!
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables created (or already exist).")

# --- Dependency for FastAPI to Get DB Session ---
async def get_async_session() -> AsyncSession:
    """
    Dependency that provides an asynchronous database session for each request.
    Ensures the session is closed after the request is processed.
    """
    async_session = AsyncSessionFactory()
    try:
        yield async_session
        await async_session.commit() # Commit changes if no exceptions
    except Exception as e:
        await async_session.rollback() # Rollback on error
        logger.error(f"Database session error: {e}")
        raise
    finally:
        await async_session.close()
