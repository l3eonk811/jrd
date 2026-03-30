from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.schemas.user import (
    UserCreate,
    UserRead,
    Token,
    LoginRequest,
    UserUpdate,
    ChangePasswordRequest,
)
from app.services.auth_service import (
    hash_password,
    authenticate_user,
    create_access_token,
    get_user_by_email,
    get_current_user,
    PasswordError,
    verify_password,
)
from app.services import email_verification_service

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def register(payload: UserCreate, db: Session = Depends(get_db)):
    if get_user_by_email(db, payload.email):
        raise HTTPException(status_code=409, detail="Email already registered")
    if db.query(User).filter(User.username == payload.username).first():
        raise HTTPException(status_code=409, detail="Username already taken")

    try:
        hashed = hash_password(payload.password)
    except PasswordError as e:
        raise HTTPException(status_code=400, detail=str(e))

    user = User(
        email=payload.email,
        username=payload.username,
        hashed_password=hashed,
        phone_number=payload.phone_number,
        role="viewer",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    
    # Send verification email
    try:
        email_verification_service.request_verification_email(db, user)
    except Exception as e:
        # Log error but don't fail registration
        print(f"Failed to send verification email: {e}")
    
    return user


@router.post("/login", response_model=Token)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = authenticate_user(db, payload.email, payload.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if user.is_blocked:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account disabled")
    return {
        "access_token": create_access_token(
            user.id,
            is_admin=bool(user.is_admin),
            role=getattr(user, "role", None) or "viewer",
        ),
        "token_type": "bearer",
    }


@router.get("/me", response_model=UserRead)
def get_me(current_user: User = Depends(get_current_user)):
    return current_user


@router.patch("/me", response_model=UserRead)
def update_me(
    payload: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(current_user, field, value)
    db.commit()
    db.refresh(current_user)
    return current_user


@router.post("/change-password")
def change_password(
    payload: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Change password for the logged-in user (same JWT as mobile app or admin console)."""
    if not verify_password(payload.current_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )
    if payload.new_password == payload.current_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must be different from your current password",
        )
    try:
        current_user.hashed_password = hash_password(payload.new_password)
    except PasswordError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    db.commit()
    return {"message": "Password updated successfully"}


@router.post("/request-verification")
def request_email_verification(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Request a new verification email."""
    email_verification_service.request_verification_email(db, current_user)
    return {"message": "Verification email sent. Please check your inbox."}


@router.post("/verify-email")
def verify_email(
    token: str,
    db: Session = Depends(get_db),
):
    """Verify email with token."""
    user = email_verification_service.verify_email_token(db, token)
    return {
        "message": "Email verified successfully!",
        "user": UserRead.model_validate(user)
    }
