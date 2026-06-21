import yaml
import os
import pandas as pd
import duckdb
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Import DB path
try:
    from database_init import DB_PATH, get_connection
except ImportError:
    from src.database_init import DB_PATH, get_connection

RULES_PATH = os.path.join(os.path.dirname(__file__), 'config', 'strategy_rules.yaml')

class RuleEngine:
    def __init__(self, rules_path=RULES_PATH, db_path=DB_PATH):
        self.rules_path = rules_path
        self.db_path = db_path
        self.rules = self._load_rules()

    def _load_rules(self):
        """Loads strategy rules from the YAML file."""
        try:
            with open(self.rules_path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)
        except Exception as e:
            logging.error(f"Error loading rules from YAML: {e}")
            return {}

    def run_macro_filter(self):
        """
        Funnel 1: Macro Water Level.
        Calculates the proportion of the entire market standing above the 50-day moving average.
        Returns a boolean indicating if macro is healthy, and the actual ratio.
        """
        logging.info("Running Macro Filter...")
        min_ratio = self.rules.get('macro_filter', {}).get('min_above_50ma_ratio', 0.3)

        conn = duckdb.connect(self.db_path)
        try:
            # We compute 50-day MA for each stock on the latest date
            # DuckDB SQL for 50-day moving average using window function
            query = """
            WITH LatestDate AS (
                SELECT MAX(date) as max_date FROM stock_daily
            ),
            MovingAverages AS (
                SELECT
                    symbol,
                    date,
                    close,
                    AVG(close) OVER (
                        PARTITION BY symbol
                        ORDER BY date
                        ROWS BETWEEN 49 PRECEDING AND CURRENT ROW
                    ) as ma_50
                FROM stock_daily
            ),
            LatestMA AS (
                SELECT * FROM MovingAverages
                WHERE date = (SELECT max_date FROM LatestDate)
            )
            SELECT
                COUNT(*) as total_stocks,
                SUM(CASE WHEN close > ma_50 THEN 1 ELSE 0 END) as stocks_above_ma
            FROM LatestMA
            """

            result = conn.execute(query).fetchone()
            if not result or result[0] == 0:
                logging.warning("No data found to compute macro filter.")
                return False, 0.0

            total_stocks = result[0]
            stocks_above_ma = result[1]
            ratio = stocks_above_ma / total_stocks

            is_healthy = ratio >= min_ratio
            logging.info(f"Macro Filter: Ratio above 50-day MA is {ratio:.2f} (Threshold: {min_ratio}). Healthy: {is_healthy}")
            return is_healthy, ratio

        except Exception as e:
            logging.error(f"Error in macro filter: {e}")
            return False, 0.0
        finally:
            conn.close()

    def run_sector_filter(self):
        """
        Funnel 2: Sector Rotation.
        Calculates 50-day RPS (Relative Price Strength) for sectors.
        (Since sector daily data is not fully fetched in demo, we approximate using stock data grouped by sector)
        Returns a list of top sectors.
        """
        logging.info("Running Sector Filter...")
        top_percentile = self.rules.get('sector_filter', {}).get('top_rps_percentile', 0.2)

        conn = duckdb.connect(self.db_path)
        try:
            # We calculate RPS: Sector return over last 50 days
            # Simplified approach: calculate average return of stocks in each sector over the last 50 days
            query = """
            WITH LatestDate AS (
                SELECT MAX(date) as max_date FROM stock_daily
            ),
            Dates50DaysAgo AS (
                SELECT date FROM (
                    SELECT DISTINCT date FROM stock_daily ORDER BY date DESC LIMIT 50
                ) sub ORDER BY date ASC LIMIT 1
            ),
            StartPrices AS (
                SELECT symbol, close as start_close FROM stock_daily
                WHERE date = (SELECT date FROM Dates50DaysAgo)
            ),
            EndPrices AS (
                SELECT symbol, close as end_close FROM stock_daily
                WHERE date = (SELECT max_date FROM LatestDate)
            ),
            StockReturns AS (
                SELECT
                    e.symbol,
                    (e.end_close - s.start_close) / s.start_close as return_50d
                FROM EndPrices e
                JOIN StartPrices s ON e.symbol = s.symbol
            ),
            SectorReturns AS (
                SELECT
                    b.industry,
                    AVG(r.return_50d) as sector_return
                FROM StockReturns r
                JOIN stock_basics b ON r.symbol = b.symbol
                WHERE b.industry IS NOT NULL AND b.industry != 'Unknown'
                GROUP BY b.industry
            )
            SELECT industry, sector_return
            FROM SectorReturns
            ORDER BY sector_return DESC
            """

            df_sectors = conn.execute(query).df()

            if df_sectors.empty:
                # If no industry info or not enough data, we return a fallback or all
                logging.warning("No sector data available or valid. Returning fallback 'Unknown' sector.")
                return ["Unknown"]

            # Select top percentile
            num_top = max(1, int(len(df_sectors) * top_percentile))
            top_sectors = df_sectors.head(num_top)['industry'].tolist()

            logging.info(f"Top Sectors selected: {top_sectors}")
            return top_sectors

        except Exception as e:
            logging.error(f"Error in sector filter: {e}")
            return []
        finally:
            conn.close()

    def run_stock_filter(self, allowed_sectors=None):
        """
        Funnel 3: Stock Picker.
        Filters stocks within allowed sectors based on ST status, pledge rate, MAs, and volume shrinkage.
        """
        logging.info("Running Stock Filter...")
        stock_rules = self.rules.get('stock_filter', {})
        exclude_st = stock_rules.get('exclude_st', True)
        max_pledge = stock_rules.get('max_pledge_rate', 50.0)
        mas_required = stock_rules.get('technical', {}).get('price_above_ma', [])
        shrink_days = stock_rules.get('technical', {}).get('volume_shrink_days', 3)

        conn = duckdb.connect(self.db_path)
        try:
            # Build the base query for the last few days
            # We need window functions for MAs and to check volume history

            # 1. First, get stocks meeting the basics criteria
            basics_conds = []
            if exclude_st:
                basics_conds.append("is_st = FALSE")
            basics_conds.append(f"pledge_rate <= {max_pledge}")

            if allowed_sectors and len(allowed_sectors) > 0 and allowed_sectors != ["Unknown"]:
                sector_list = ", ".join([f"'{s}'" for s in allowed_sectors])
                basics_conds.append(f"industry IN ({sector_list})")

            basics_where = " AND ".join(basics_conds)

            query = f"""
            WITH ValidBasics AS (
                SELECT symbol, name, industry FROM stock_basics
                WHERE {basics_where}
            ),
            RankedDaily AS (
                SELECT
                    symbol,
                    date,
                    close,
                    volume,
                    ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY date DESC) as rn
                FROM stock_daily
            ),
            LatestDaily AS (
                SELECT * FROM RankedDaily WHERE rn = 1
            )
            """

            # Adding MA calculations dynamically if needed
            ma_selects = []
            if mas_required:
                for ma in mas_required:
                    ma_selects.append(f"AVG(close) OVER (PARTITION BY symbol ORDER BY date ROWS BETWEEN {ma-1} PRECEDING AND CURRENT ROW) as ma_{ma}")

                query = f"""
                WITH ValidBasics AS (
                    SELECT symbol, name, industry FROM stock_basics
                    WHERE {basics_where}
                ),
                MACalc AS (
                    SELECT
                        symbol,
                        date,
                        close,
                        volume,
                        {", ".join(ma_selects)},
                        ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY date DESC) as rn
                    FROM stock_daily
                ),
                LatestDaily AS (
                    SELECT * FROM MACalc WHERE rn = 1
                )
                """

            # Volume shrinkage check (e.g. volume today < volume yesterday < volume day before)
            # For simplicity, we just check if average volume of last 3 days is less than 5 days ago,
            # or if it's strictly decreasing. Let's do strictly decreasing for the specified shrink_days.

            # Using Lag window function
            query += f"""
            , VolumeHistory AS (
                SELECT
                    symbol,
                    date,
                    volume,
                    rn,
                    LAG(volume, 1) OVER (PARTITION BY symbol ORDER BY date ASC) as prev_vol_1,
                    LAG(volume, 2) OVER (PARTITION BY symbol ORDER BY date ASC) as prev_vol_2
                FROM RankedDaily -- Uses original ranked
                WHERE rn <= {shrink_days + 1}
            )
            """

            # Final assembly
            query += """
            SELECT
                l.symbol,
                b.name,
                b.industry,
                l.close
            FROM LatestDaily l
            JOIN ValidBasics b ON l.symbol = b.symbol
            """

            where_clauses = []

            if mas_required:
                for ma in mas_required:
                    where_clauses.append(f"l.close > l.ma_{ma}")

            if where_clauses:
                query += " WHERE " + " AND ".join(where_clauses)

            df_final = conn.execute(query).df()

            # Note: For strict volume shrinkage, doing it via SQL might get complex.
            # We'll do the volume check in pandas for simplicity.

            # Fetch last few days of volume to check shrinkage
            if shrink_days > 0 and not df_final.empty:
                # We need to recreate the RankedDaily CTE for the new query since DuckDB doesn't persist it across executes
                vol_query = f"""
                WITH RankedDaily AS (
                    SELECT
                        symbol,
                        date,
                        volume,
                        ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY date DESC) as rn
                    FROM stock_daily
                )
                SELECT symbol, rn, volume
                FROM RankedDaily
                WHERE rn <= {shrink_days} AND symbol IN ({", ".join(["'"+s+"'" for s in df_final['symbol']])})
                """
                df_vol = conn.execute(vol_query).df()

                # Check if volume is strictly shrinking: rn=1 (today) < rn=2 (yesterday) < rn=3 (day before)
                # Group by symbol and check if sorting by rn ascending means volume is ascending
                def is_shrinking(group):
                    # Sort so rn=1 is last (today)
                    vols = group.sort_values('rn', ascending=False)['volume'].values
                    # Check if strictly decreasing
                    return all(x < y for x, y in zip(vols[1:], vols[:-1]))

                if not df_vol.empty:
                    shrinking_symbols = df_vol.groupby('symbol').filter(is_shrinking)['symbol'].unique()
                    df_final = df_final[df_final['symbol'].isin(shrinking_symbols)]

            logging.info(f"Stock Filter selected {len(df_final)} stocks.")
            return df_final

        except Exception as e:
            logging.error(f"Error in stock filter: {e}")
            return pd.DataFrame()
        finally:
            conn.close()

    def run_all(self):
        """Runs the triple funnel."""
        logging.info("--- Starting Triple Funnel Engine ---")

        # 1. Macro
        is_healthy, macro_ratio = self.run_macro_filter()
        if not is_healthy:
            logging.warning(f"Macro environment is unhealthy ({macro_ratio:.2f}). Proceeding with caution.")

        # 2. Sector
        top_sectors = self.run_sector_filter()

        # 3. Stock
        final_stocks = self.run_stock_filter(allowed_sectors=top_sectors)

        logging.info("--- Triple Funnel Complete ---")
        return {
            "macro_healthy": is_healthy,
            "macro_ratio": macro_ratio,
            "top_sectors": top_sectors,
            "selected_stocks": final_stocks.to_dict(orient='records')
        }

if __name__ == "__main__":
    engine = RuleEngine()
    results = engine.run_all()
    print("Final Selected Stocks:", len(results['selected_stocks']))
    print(results['selected_stocks'][:5])
