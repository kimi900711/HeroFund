import os
from src.ai_skills import AISkillsManager

# Assuming user provides GEMINI_API_KEY
manager = AISkillsManager()
print(manager.diagnose_position("002460", "test logic"))
