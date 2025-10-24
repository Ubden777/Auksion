import asyncpg
import asyncio

# Global variable to hold the connection pool
_pool = None

async def init_pool(db_config: dict):
    """Initializes the database connection pool."""
    global _pool
    if _pool is None:
        try:
            _pool = await asyncpg.create_pool(
                user=db_config.get("user"),
                password=db_config.get("password"),
                database=db_config.get("database"),
                host=db_config.get("host"),
                min_size=1,
                max_size=10
            )
            print("Database connection pool initialized successfully.")
        except Exception as e:
            print(f"Error initializing database pool: {e}")
            raise

def get_pool() -> asyncpg.Pool:
    """Returns the existing connection pool."""
    if _pool is None:
        raise RuntimeError("Database pool has not been initialized. Call init_pool() first.")
    return _pool

async def close_pool():
    """Closes the database connection pool."""
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
        print("Database connection pool closed.")
