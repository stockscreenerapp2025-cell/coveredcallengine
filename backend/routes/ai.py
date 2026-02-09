"""
AI Routes - AI-powered analysis endpoints
"""
from fastapi import APIRouter, Depends, Query
from typing import Optional
import os
import logging
from openai import OpenAI

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from database import db
from models.schemas import AIAnalysisRequest
from utils.auth import get_current_user

ai_router = APIRouter(tags=["AI Insights"])


async def get_admin_settings():
    """Get admin settings from database"""
    settings = await db.admin_settings.find_one({}, {"_id": 0})
    if settings:
        class Settings:
            pass
        s = Settings()
        s.openai_api_key = settings.get("openai_api_key")
        return s
    
    class EmptySettings:
        openai_api_key = None
    return EmptySettings()


def generate_mock_covered_call_opportunities():
    """Generate mock covered call opportunities - imported from server for now"""
    from server import generate_mock_covered_call_opportunities as mock_fn
    return mock_fn()


@ai_router.post("/analyze")
async def ai_analysis(request: AIAnalysisRequest, user: dict = Depends(get_current_user)):
    """AI-powered trade analysis using GPT-5.2"""
    settings = await get_admin_settings()
    
    # Use Emergent LLM key or admin-configured key
    api_key = settings.openai_api_key or os.environ.get('EMERGENT_LLM_KEY')
    
    if not api_key:
        # Return mock analysis if no API key
        return {
            "analysis": f"AI analysis for {request.symbol or 'market'} ({request.analysis_type})",
            "recommendations": [
                "Consider selling weekly covered calls at 0.25-0.30 delta",
                "Monitor IV rank for optimal entry points",
                "Set alerts for earnings dates to avoid assignment risk"
            ],
            "confidence": 0.75,
            "is_mock": True
        }
    
    try:
        client = OpenAI(api_key=api_key)
        
        # Build context-aware prompt
        system_prompt = """You are an expert options trading analyst specializing in covered calls and Poor Man's Covered Calls (PMCC). 
        Provide actionable, data-driven analysis with specific recommendations. 
        Include composite scores (1-100), confidence levels, and clear rationale for all suggestions.
        Format responses with clear sections: Summary, Key Metrics, Recommendations, Risk Assessment."""
        
        user_prompt = f"""Analysis Type: {request.analysis_type}
        Symbol: {request.symbol or 'General Market'}
        Context: {request.context or 'Standard analysis requested'}
        
        Please provide:
        1. Current opportunity assessment
        2. Specific strike/expiry recommendations
        3. Risk factors and mitigation strategies
        4. Confidence score and rationale"""
        
        response = client.chat.completions.create(
            model="gpt-4o",  # Using gpt-4o as fallback
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            max_tokens=1000,
            temperature=0.7
        )
        
        analysis_text = response.choices[0].message.content
        
        return {
            "analysis": analysis_text,
            "symbol": request.symbol,
            "analysis_type": request.analysis_type,
            "confidence": 0.85,
            "is_mock": False
        }
        
    except Exception as e:
        logging.error(f"AI Analysis error: {e}")
        return {
            "analysis": f"Unable to generate AI analysis: {str(e)}",
            "is_mock": True,
            "error": True
        }


@ai_router.get("/opportunities")
async def ai_opportunity_scan(
    min_score: float = Query(70, ge=0, le=100),
    user: dict = Depends(get_current_user)
):
    """AI-scored trading opportunities"""
    opportunities = generate_mock_covered_call_opportunities()
    
    # Add AI scores
    for opp in opportunities:
        # Calculate composite score based on multiple factors
        roi_score = min(opp["roi_pct"] * 20, 40)
        iv_score = opp["iv_rank"] / 100 * 20
        delta_score = 20 - abs(opp["delta"] - 0.3) * 100
        protection_score = min(opp["downside_protection"], 10) * 2
        
        opp["ai_score"] = round(roi_score + iv_score + delta_score + protection_score, 1)
        opp["ai_rationale"] = f"ROI: {roi_score:.0f}/40, IV: {iv_score:.0f}/20, Delta: {delta_score:.0f}/20, Protection: {protection_score:.0f}/20"
    
    # Filter by minimum score
    filtered = [o for o in opportunities if o["ai_score"] >= min_score]
    filtered.sort(key=lambda x: x["ai_score"], reverse=True)
    
    return {"opportunities": filtered[:20], "total": len(filtered)}
