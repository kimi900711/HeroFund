import os
import json
import logging
import time
import requests
from google import genai
from google.genai import types

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Ensure API Key is set in environment for Google Gemini
# Can be set via `export GEMINI_API_KEY="..."` before running
api_key = os.environ.get("GEMINI_API_KEY", "")

class LLMRouter:
    def __init__(self):
        # Using the standard model names for 1.5 Pro and 1.5 Flash
        self.pro_model_name = "gemini-1.5-pro"
        self.flash_model_name = "gemini-1.5-flash"

        # Configure client if API key is present
        if api_key:
            self.client = genai.Client(api_key=api_key)
        else:
            self.client = None

    def generate_text(self, prompt: str, fallback_to_flash: bool = True) -> str:
        """
        Calls Gemini 1.5 Pro by default.
        Falls back to Gemini 1.5 Flash if Pro hits a 429 quota error or other network issue.
        """
        if not self.client:
            return "Error: GEMINI_API_KEY environment variable not set. Please set it to use LLM features."

        try:
            logging.info(f"Routing request to {self.pro_model_name}...")
            response = self.client.models.generate_content(
                model=self.pro_model_name,
                contents=prompt
            )
            return response.text
        except Exception as e:
            error_str = str(e)
            logging.warning(f"Error calling {self.pro_model_name}: {error_str}")

            # Check for rate limiting / 429 or quota exceeded
            is_429_or_quota = "429" in error_str or "quota" in error_str.lower() or "exhausted" in error_str.lower()

            if fallback_to_flash and is_429_or_quota:
                logging.info(f"Falling back to {self.flash_model_name}...")
                try:
                    response = self.client.models.generate_content(
                        model=self.flash_model_name,
                        contents=prompt
                    )
                    return response.text
                except Exception as flash_e:
                    logging.error(f"Error calling fallback {self.flash_model_name}: {flash_e}")
                    return f"Error: Both Pro and Flash models failed. Flash error: {flash_e}"
            else:
                return f"Error with Pro model: {error_str}"

class SequoiaXSkill:
    """Mock interface for local/cloud Sequoia-X Deep Learning Alpha Skill."""
    def __init__(self, endpoint_url="http://localhost:8000/api/v1/sequoia_x/score"):
        self.endpoint_url = endpoint_url

    def get_alpha_scores(self, stock_symbols: list) -> dict:
        """
        Sends a list of stock symbols to Sequoia-X and returns their multi-factor scores.
        """
        logging.info(f"Calling Sequoia-X for {len(stock_symbols)} stocks...")

        # This is a mock implementation since we don't have the real Sequoia-X service
        try:
            # Uncomment for real HTTP call
            # response = requests.post(self.endpoint_url, json={"symbols": stock_symbols}, timeout=10)
            # response.raise_for_status()
            # return response.json()

            # Mock behavior: assign a random score between 0 and 100 to each stock
            import random
            time.sleep(0.5) # Simulate network delay
            scores = {sym: round(random.uniform(40.0, 99.9), 2) for sym in stock_symbols}
            return {"status": "success", "scores": scores}
        except Exception as e:
            logging.error(f"Error connecting to Sequoia-X: {e}")
            return {"status": "error", "message": str(e), "scores": {}}

class SerenitySkill:
    """Mock interface for Serenity Supply Chain & Bottleneck Discovery Skill."""
    def __init__(self, endpoint_url="http://localhost:8000/api/v1/serenity/verify"):
        self.endpoint_url = endpoint_url

    def verify_supply_chain(self, symbol: str) -> dict:
        """
        Calls the Serenity plugin to perform alternative data deep dive (GitHub, SEC filings)
        to verify if the company is a true bottleneck/critical player in the supply chain.
        """
        logging.info(f"Calling Serenity Skill to verify {symbol}...")

        # Mock implementation
        try:
            # Uncomment for real HTTP call
            # response = requests.get(f"{self.endpoint_url}?symbol={symbol}", timeout=15)
            # response.raise_for_status()
            # return response.json()

            time.sleep(1.0) # Simulate deeper analysis delay
            # Mock insights
            insights = f"Serenity Deep Dive: Analyzed GitHub commits and recent procurement filings for {symbol}. " \
                       f"Evidence suggests strong IP moats in key components, but some reliance on overseas raw materials."
            return {
                "status": "success",
                "symbol": symbol,
                "is_bottleneck": True,
                "risk_level": "Medium",
                "insights": insights
            }
        except Exception as e:
            logging.error(f"Error connecting to Serenity Skill: {e}")
            return {"status": "error", "symbol": symbol, "message": str(e)}

# Unified AI Skills Manager
class AISkillsManager:
    def __init__(self):
        self.llm = LLMRouter()
        self.sequoia_x = SequoiaXSkill()
        self.serenity = SerenitySkill()

    def review_daily(self, macro_data, top_sectors, radar_list):
        """
        Tab 2: Daily Review.
        Generates Core Lessons and Tomorrow's Plan using Gemini.
        """
        prompt = f"""
        You are a senior quantitative trading analyst. Please review today's market data:

        Macro Context:
        - Favorable: {macro_data.get('macro_healthy')}
        - Breadth (Stocks > 50MA): {macro_data.get('macro_ratio'):.2%}

        Strongest Sectors (Top RPS):
        {', '.join(top_sectors) if top_sectors else 'None identified'}

        AI Radar Candidates (Passed Triple Funnel):
        {json.dumps(radar_list, ensure_ascii=False) if radar_list else 'No stocks passed all filters today.'}

        Please provide:
        1. Core Lessons from today's market structure.
        2. Tomorrow's Pre-Plan (Actionable advice on these specific sectors/stocks).
        Keep it structured, insightful, and concise.
        """
        return self.llm.generate_text(prompt)

    def diagnose_position(self, symbol, logic):
        """
        Tab 1: Position Check.
        Uses Serenity for supply chain check + Gemini for risk synthesis.
        """
        # Get alternative data from Serenity
        serenity_result = self.serenity.verify_supply_chain(symbol)

        prompt = f"""
        You are a rigorous risk-management AI. A user is holding/planning to buy stock {symbol}.
        User's Thesis: "{logic}"

        Serenity Alternative Data System Check:
        {json.dumps(serenity_result, ensure_ascii=False)}

        Please synthesize a Risk Diagnosis Report:
        1. Thesis Validation: Does the data support their logic?
        2. Hidden Risks: Are there supply chain bottlenecks or vulnerabilities?
        3. Final Verdict: Green (Go), Yellow (Caution), or Red (Stop).
        """
        return self.llm.generate_text(prompt)

if __name__ == "__main__":
    # Test
    manager = AISkillsManager()
    print("Sequoia-X Test:", manager.sequoia_x.get_alpha_scores(["000001", "000002"]))
    print("Serenity Test:", manager.serenity.verify_supply_chain("000001"))

    if os.environ.get("GEMINI_API_KEY"):
        print("\nLLM Test (Pro -> Flash Router):")
        print(manager.llm.generate_text("Say 'Hello, AI Trading System' in 3 words."))
    else:
        print("\nSkipping LLM test: GEMINI_API_KEY not set.")
