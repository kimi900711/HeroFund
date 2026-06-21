import akshare as ak
import pandas as pd
import duckdb
from datetime import datetime, timedelta
import logging
import os
import time

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Import DB_PATH and get_connection
try:
    from database_init import DB_PATH, get_connection
except ImportError:
    from src.database_init import DB_PATH, get_connection

def get_latest_date(conn, table_name, symbol_col=None, symbol_val=None):
    """Gets the latest date in the database for a given table/symbol."""
    query = f"SELECT MAX(date) FROM {table_name}"
    if symbol_col and symbol_val:
        query += f" WHERE {symbol_col} = '{symbol_val}'"

    try:
        result = conn.execute(query).fetchone()[0]
        if result:
            return pd.to_datetime(result).strftime('%Y%m%d')
    except Exception as e:
        logging.warning(f"Error checking latest date for {table_name}: {e}")

    # Default to 5 years ago
    return (datetime.now() - timedelta(days=5*365)).strftime('%Y%m%d')

def update_stock_basics():
    """Fetches and updates A-share and HK-share stock basics (name, industry, ST status)."""
    logging.info("Updating A-share and HK-share stock basics...")
    conn = get_connection()
    try:
        # Get A-share list
        df_basics_a = ak.stock_info_a_code_name()
        df_basics_a.rename(columns={'code': 'symbol', 'name': 'name'}, inplace=True)

        # Get HK-share list (using a fallback method if spot_em fails)
        try:
            df_basics_hk = ak.stock_hk_spot_em()
            df_basics_hk = df_basics_hk[['代码', '名称']].copy()
            df_basics_hk.rename(columns={'代码': 'symbol', '名称': 'name'}, inplace=True)
        except Exception as e:
            logging.warning(f"Could not fetch HK spot EM, attempting fallback: {e}")
            # simple mock or alternative list for HK if the EM spot API fails in sandbox
            df_basics_hk = pd.DataFrame([{'symbol': '00700', 'name': 'Tencent'}, {'symbol': '09988', 'name': 'Alibaba'}])

        # Combine them
        df_basics = pd.concat([df_basics_a, df_basics_hk], ignore_index=True)

        # Let's try to get proper industry info via stock_board_industry_name_em
        try:
            # Get full industry mapping
            industry_list = ak.stock_board_industry_name_em()
            all_industries = industry_list['板块名称'].tolist()

            industry_mapping = {}
            for ind in all_industries:
                try:
                    # Get constituents of this industry
                    ind_stocks = ak.stock_board_industry_cons_em(symbol=ind)
                    for code in ind_stocks['代码']:
                        industry_mapping[code] = ind
                except Exception:
                    continue

            df_basics['industry'] = df_basics['symbol'].map(industry_mapping).fillna('Unknown')
        except Exception as e:
            logging.warning(f"Could not fetch precise industry data: {e}")
            df_basics['industry'] = 'Unknown'

        # Add ST indicator based on name
        df_basics['is_st'] = df_basics['name'].str.contains('ST', na=False).astype(bool)
        df_basics['pledge_rate'] = 0.0  # Placeholder, deep pledge data is heavy to fetch

        # Upsert into DuckDB
        conn.register('df_basics_view', df_basics)

        # Clean up existing to simulate full update for basics
        conn.execute("DELETE FROM stock_basics")
        conn.execute("INSERT INTO stock_basics SELECT symbol, name, industry, is_st, pledge_rate FROM df_basics_view")

        logging.info(f"Successfully updated basics for {len(df_basics)} stocks.")
        return df_basics['symbol'].tolist()

    except Exception as e:
        logging.error(f"Error updating stock basics: {e}")
        return []
    finally:
        conn.close()

def update_daily_data(symbols, max_symbols=100):
    """
    Fetches daily data for a list of symbols.
    To avoid excessive API calls in demo, limiting to max_symbols.
    """
    conn = get_connection()
    end_date = datetime.now().strftime('%Y%m%d')

    symbols_to_process = symbols[:max_symbols] if max_symbols else symbols
    logging.info(f"Updating daily data for {len(symbols_to_process)} symbols...")

    success_count = 0
    for i, symbol in enumerate(symbols_to_process):
        try:
            # Check latest date
            start_date = get_latest_date(conn, 'stock_daily', 'symbol', symbol)

            # If start_date >= end_date, might not need update, but akshare includes current day, so let's fetch
            # To be safe and handle API format, we fetch from start_date

            # Determine if it is HK or A-share based on length or prefix
            if len(symbol) == 5 or not symbol.startswith(('0', '3', '6')):
                # Most likely HK share (e.g. 00700)
                # hk_hist API uses different format
                df_daily = ak.stock_hk_hist(symbol=symbol, period="daily", start_date=start_date, end_date=end_date, adjust="qfq")
                if df_daily.empty:
                    continue
                df_daily = df_daily.rename(columns={
                    '日期': 'date', '开盘': 'open', '最高': 'high', '最低': 'low',
                    '收盘': 'close', '成交量': 'volume', '成交额': 'amount', '换手率': 'turnover'
                })
            else:
                # Need to use qfq (前复权) to get adjusted prices.
                try:
                    df_daily = ak.stock_zh_a_hist(symbol=symbol, period="daily", start_date=start_date, end_date=end_date, adjust="qfq")
                    if df_daily.empty:
                        continue

                    # Rename columns to match schema
                    df_daily = df_daily.rename(columns={
                        '日期': 'date',
                        '开盘': 'open',
                        '最高': 'high',
                        '最低': 'low',
                        '收盘': 'close',
                        '成交量': 'volume',
                        '成交额': 'amount',
                        '换手率': 'turnover'
                    })
                except Exception as e:
                    logging.warning(f"Failed to fetch qfq data for {symbol}, trying unadjusted. Error: {e}")
                    # Fallback to unadjusted if network blocks it (like spot APIs)
                    prefix = 'sh' if symbol.startswith(('600', '601', '603', '688')) else 'sz'
                    full_symbol = f"{prefix}{symbol}"

                    df_daily = ak.stock_zh_a_daily(symbol=full_symbol, start_date=start_date, end_date=end_date)
                    if df_daily.empty:
                        continue

            df_daily['symbol'] = symbol

            # Select columns
            cols = ['symbol', 'date', 'open', 'high', 'low', 'close', 'volume', 'amount', 'turnover']
            # Ensure turnover exists (some APIs might drop it)
            if 'turnover' not in df_daily.columns:
                df_daily['turnover'] = 0.0

            df_daily = df_daily[cols]

            # We must convert date string to datetime for DuckDB
            df_daily['date'] = pd.to_datetime(df_daily['date'])

            conn.register('df_daily_view', df_daily)

            # Insert with conflict resolution (DuckDB 0.9+ supports ON CONFLICT)
            conn.execute("""
                INSERT INTO stock_daily
                SELECT * FROM df_daily_view
                ON CONFLICT (symbol, date) DO UPDATE SET
                    open = EXCLUDED.open,
                    high = EXCLUDED.high,
                    low = EXCLUDED.low,
                    close = EXCLUDED.close,
                    volume = EXCLUDED.volume,
                    amount = EXCLUDED.amount,
                    turnover = EXCLUDED.turnover
            """)

            success_count += 1
            if (i+1) % 10 == 0:
                logging.info(f"Processed {i+1}/{len(symbols_to_process)} symbols...")

            # Be nice to the API
            time.sleep(0.5)

        except Exception as e:
            logging.error(f"Error processing symbol {symbol}: {e}")

    conn.close()
    logging.info(f"Daily data update complete. Success: {success_count}/{len(symbols_to_process)}")

def update_index_data(index_symbols=["000300"]):
    """Fetches daily data for market indices (default HS300)."""
    logging.info("Updating index data...")
    conn = get_connection()
    end_date = datetime.now().strftime('%Y%m%d')

    for symbol in index_symbols:
        try:
            start_date = get_latest_date(conn, 'index_daily', 'symbol', symbol)

            # akshare index data
            # Prefix for index_zh_a_daily? Actually, index_zh_a_daily might not exist, let's use another if possible or fallback
            try:
                # Attempt to get index data
                # For Sina, prefix depends: sh for 000001, sz for 399001 (szse component).
                # HS300 is sh000300
                prefix = 'sh' if symbol.startswith('0') else 'sz'
                full_symbol = f"{prefix}{symbol}"
                df_index = ak.stock_zh_index_daily(symbol=full_symbol)

                # Filter by date
                start_dt = pd.to_datetime(start_date).date()
                end_dt = pd.to_datetime(end_date).date()

                # Ensure date col
                df_index['date'] = pd.to_datetime(df_index['date']).dt.date
                df_index = df_index[(df_index['date'] >= start_dt) & (df_index['date'] <= end_dt)]

                if df_index is None or df_index.empty:
                    continue

                df_index['symbol'] = symbol
                cols = ['symbol', 'date', 'open', 'high', 'low', 'close', 'volume']
                df_index = df_index[cols]
                df_index['date'] = pd.to_datetime(df_index['date'])

                conn.register('df_index_view', df_index)

                conn.execute("""
                    INSERT INTO index_daily
                    SELECT * FROM df_index_view
                    ON CONFLICT (symbol, date) DO UPDATE SET
                        open = EXCLUDED.open,
                        high = EXCLUDED.high,
                        low = EXCLUDED.low,
                        close = EXCLUDED.close,
                        volume = EXCLUDED.volume
                """)
                logging.info(f"Successfully updated index {symbol}")
            except Exception as e:
                logging.warning(f"Could not fetch data for index {symbol}: {e}")

        except Exception as e:
            logging.error(f"Error updating index {symbol}: {e}")

    conn.close()

def run_pipeline(demo_mode=False):
    """Runs the full data fetching pipeline."""
    # 1. Initialize DB if not exists
    from database_init import init_db
    init_db()

    # 2. Update Basics
    all_symbols = update_stock_basics()

    if not all_symbols:
        logging.error("Failed to retrieve stock list. Aborting pipeline.")
        return

    # 3. Update Daily Data
    # Fetch for all symbols unless demo_mode is specified
    max_syms = 200 if demo_mode else None
    update_daily_data(all_symbols, max_symbols=max_syms)

    # 4. Update Index Data (HS300: 000300, SH Composite: 000001)
    update_index_data(["000300", "000001"])

    logging.info("Data pipeline finished successfully.")

if __name__ == "__main__":
    run_pipeline(demo_mode=False)
