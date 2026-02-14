"""
AI Routes - AI-powered analysis endpoints

Note: Mock fallback blocked in production (ENVIRONMENT check).
"""
from fastapi import APIRouter, Depends, Query, HTTPException
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
from utils.environment import allow_mock_data

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
    """
    Generate mock covered call opportunities - imported from server.
    
    Returns empty list in production to prevent mock data leakage.
    """
    if not allow_mock_data():
        logging.warning("MOCK_FALLBACK_BLOCKED_PRODUCTION | function=ai.generate_mock_covered_call_opportunities")
        return []
    
    from server import generate_mock_covered_call_opportunities as mock_fn
    return mock_fn()


@ai_router.post("/analyze")
async def ai_analysis(request: AIAnalysisRequest, user: dict = Depends(get_current_user)):
    """AI-powered trade analysis (uses AI tokens)"""
    from ai_wallet.ai_service import AIExecutionService
    
    ai_service = AIExecutionService(db)
    
    # Build the prompt
    user_prompt = f"""Analysis Type: {request.analysis_type}
    Symbol: {request.symbol or 'General Market'}
    Context: {request.context or 'Standard analysis requested'}
    
    Please provide:
    1. Current opportunity assessment
    2. Specific strike/expiry recommendations
    3. Risk factors and mitigation strategies
    4. Confidence score and rationale"""
    
    # Execute with token guard
    result = await ai_service.execute_general_analysis(
        user_id=user["id"],
        analysis_request=user_prompt
    )
    
    if not result["success"]:
        # Check if this is a token issue
        if result.get("error_code") == "INSUFFICIENT_TOKENS":
            from fastapi import HTTPException
            raise HTTPException(
                status_code=402,
                detail={
                    "error": result["error"],
                    "error_code": "INSUFFICIENT_TOKENS",
                    "remaining_balance": result.get("remaining_balance", 0)
                }
            )
        
        # For other errors, check if mock fallback is allowed
        if allow_mock_data():
            logging.warning(f"MOCK_FALLBACK_USED | endpoint=ai_analysis | reason={result.get('error')}")
            return {
                "analysis": f"AI analysis for {request.symbol or 'market'} ({request.analysis_type})",
                "recommendations": [
                    "Consider selling weekly covered calls at 0.25-0.30 delta",
                    "Monitor IV rank for optimal entry points",
                    "Set alerts for earnings dates to avoid assignment risk"
                ],
                "confidence": 0.75,
                "is_mock": True,
                "error": result.get("error")
            }
        else:
            # Production: fail explicitly
            logging.warning(f"MOCK_FALLBACK_BLOCKED_PRODUCTION | endpoint=ai_analysis | reason={result.get('error')}")
            raise HTTPException(
                status_code=503,
                detail={
                    "data_status": "UNAVAILABLE",
                    "reason": "AI_SERVICE_ERROR",
                    "details": result.get("error"),
                    "is_mock": False
                }
            )
    
    return {
        "analysis": result["response"],
        "symbol": request.symbol,
        "analysis_type": request.analysis_type,
        "confidence": 0.85,
        "is_mock": False,
        "tokens_used": result.get("tokens_used", 0),
        "remaining_balance": result.get("remaining_balance", 0)
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
