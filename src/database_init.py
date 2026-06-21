import duckdb
import os
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

DB_PATH = os.path.join(os.path.dirname(__file__), 'market_data.duckdb')

def get_connection():
    """Returns a connection to the DuckDB database."""
    return duckdb.connect(DB_PATH)

def init_db():
    """Initializes the DuckDB database with the required tables."""
    conn = get_connection()
    try:
        # Create daily price-volume table for stocks
        conn.execute("""
            CREATE TABLE IF NOT EXISTS stock_daily (
                symbol VARCHAR,
                date DATE,
                open DOUBLE,
                high DOUBLE,
                low DOUBLE,
                close DOUBLE,
                volume DOUBLE,
                amount DOUBLE,
                turnover DOUBLE,
                PRIMARY KEY (symbol, date)
            )
        """)

        # Create stock basic info table (including ST and pledge info if available)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS stock_basics (
                symbol VARCHAR PRIMARY KEY,
                name VARCHAR,
                industry VARCHAR,
                is_st BOOLEAN,
                pledge_rate DOUBLE
            )
        """)

        # Create market index daily table (e.g., HS300, etc.)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS index_daily (
                symbol VARCHAR,
                date DATE,
                open DOUBLE,
                high DOUBLE,
                low DOUBLE,
                close DOUBLE,
                volume DOUBLE,
                PRIMARY KEY (symbol, date)
            )
        """)

        logging.info("DuckDB initialized successfully with schema.")
    except Exception as e:
        logging.error(f"Error initializing DuckDB: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    init_db()
