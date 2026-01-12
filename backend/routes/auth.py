"""
Authentication routes
"""
from fastapi import APIRouter, HTTPException, Depends
from datetime import datetime, timezone
import uuid

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from database import db
from models.schemas import UserCreate, UserResponse, TokenResponse
from utils.auth import hash_password, verify_password, create_token, get_current_user

# Use correct pydantic model for login
from pydantic import BaseModel, EmailStr

class UserLogin(BaseModel):
    email: EmailStr
    password: str

auth_router = APIRouter(tags=["Authentication"])


@auth_router.post("/register", response_model=TokenResponse)
async def register(user_data: UserCreate):
    """Register a new user"""
    # Check if user exists
    existing = await db.users.find_one({"email": user_data.email})
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    # Create user
    user_id = str(uuid.uuid4())
    user = {
        "id": user_id,
        "email": user_data.email,
        "name": user_data.name,
        "password": hash_password(user_data.password),
        "is_admin": False,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.users.insert_one(user)
    
    # Generate token
    token = create_token(user_id, user_data.email)
    
    return TokenResponse(
        access_token=token,
        user=UserResponse(
            id=user_id,
            email=user_data.email,
            name=user_data.name,
            is_admin=False,
            created_at=user["created_at"]  # Already a string (isoformat)
        )
    )


@auth_router.post("/login", response_model=TokenResponse)
async def login(credentials: UserLogin):
    """Login user and return token"""
    user = await db.users.find_one({"email": credentials.email})
    if not user or not verify_password(credentials.password, user["password"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    
    # Include role in token for backend authorization
    token = create_token(
        user["id"], 
        user["email"], 
        user.get("is_admin", False),
        user.get("role")
    )
    
    created_at = user.get("created_at")
    # Ensure created_at is a string
    if isinstance(created_at, datetime):
        created_at = created_at.isoformat()
    
    return TokenResponse(
        access_token=token,
        user=UserResponse(
            id=user["id"],
            email=user["email"],
            name=user["name"],
            is_admin=user.get("is_admin", False),
            role=user.get("role"),
            is_support_staff=user.get("is_support_staff", False),
            is_tester=user.get("is_tester", False),
            permissions=user.get("permissions", []),
            created_at=created_at
        )
    )


@auth_router.get("/me", response_model=UserResponse)
async def get_me(user: dict = Depends(get_current_user)):
    """Get current user info"""
    created_at = user.get("created_at")
    # Ensure created_at is a string
    if isinstance(created_at, datetime):
        created_at = created_at.isoformat()
    
    return UserResponse(
        id=user["id"],
        email=user["email"],
        name=user["name"],
        is_admin=user.get("is_admin", False),
        created_at=created_at
    )
