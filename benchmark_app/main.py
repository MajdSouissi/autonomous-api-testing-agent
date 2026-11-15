
"""
Benchmark FastAPI target application for the Autonomous API Testing & Code Generation Agent.
Contains 3 deliberate bugs for testing purposes (BUG-1, BUG-2, BUG-3).
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.responses import JSONResponse, Response
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt

from benchmark_app.models import (
    ItemCreate,
    ItemResponse,
    ItemUpdate,
    Token,
    UserCreate,
    UserResponse,
)

# ── JWT config ────────────────────────────────────────────────────────────────
SECRET_KEY = "test-secret-key-for-benchmark"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

# ── In-memory stores ──────────────────────────────────────────────────────────
users_db: Dict[str, dict] = {}          # username → {id, username, hashed_password}
items_db: Dict[int, dict] = {}          # item_id  → {id, title, description, price, owner_id}
user_id_counter: int = 0
item_id_counter: int = 0

# ── FastAPI app ───────────────────────────────────────────────────────────────
app = FastAPI(
    title="Benchmark Target API",
    description="A FastAPI application with intentional bugs used as a benchmark target.",
    version="1.0.0",
)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _hash_password(password: str) -> str:
    """Very simple 'hash' – NOT for production use."""
    return f"hashed:{password}"


def _verify_password(plain: str, hashed: str) -> bool:
    return hashed == f"hashed:{plain}"


def _create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=15))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


async def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    """Decode JWT and return user dict; raises 401 on any error."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: Optional[str] = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = users_db.get(username)
    if user is None:
        raise credentials_exception
    return user


# ── Auth routes ───────────────────────────────────────────────────────────────

@app.post(
    "/auth/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    responses={422: {"description": "Validation Error"}},
)
async def register(user_in: UserCreate) -> UserResponse:
    global user_id_counter

    if user_in.username in users_db:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already registered",
        )

    user_id_counter += 1
    users_db[user_in.username] = {
        "id": user_id_counter,
        "username": user_in.username,
        "hashed_password": _hash_password(user_in.password),
    }
    return UserResponse(id=user_id_counter, username=user_in.username)


@app.post(
    "/auth/token",
    response_model=Token,
    responses={401: {"description": "Incorrect credentials"}, 422: {"description": "Validation Error"}},
)
async def login(form_data: OAuth2PasswordRequestForm = Depends()) -> Token:
    user = users_db.get(form_data.username)
    if user is None or not _verify_password(form_data.password, user["hashed_password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = _create_access_token(
        data={"sub": user["username"]},
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    return Token(access_token=access_token, token_type="bearer")


# ── Item routes ───────────────────────────────────────────────────────────────

@app.post(
    "/items/",
    response_model=ItemResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        401: {"description": "Not authenticated"},
        422: {"description": "Validation Error"},
    },
)
async def create_item(
    item_in: ItemCreate,
    current_user: dict = Depends(get_current_user),
) -> ItemResponse:
    global item_id_counter

    item_id_counter += 1
    item = {
        "id": item_id_counter,
        "title": item_in.title,
        "description": item_in.description,
        "price": 0.0,  # BUG-3: price field is silently zeroed out
        "owner_id": current_user["id"],
    }
    items_db[item_id_counter] = item
    return ItemResponse(**item)


@app.get(
    "/items/",
    response_model=List[ItemResponse],
    responses={
        401: {"description": "Not authenticated"},
    },
)
async def list_items(
    current_user: dict = Depends(get_current_user),
) -> List[ItemResponse]:
    return [ItemResponse(**item) for item in items_db.values()]


@app.get(
    "/items/{item_id}",
    response_model=ItemResponse,
    responses={
        401: {"description": "Not authenticated"},
        404: {"description": "Item not found"},
    },
)
async def get_item(
    item_id: int,
    current_user: dict = Depends(get_current_user),
) -> ItemResponse:
    # BUG-2: Missing 404 handler causes 500 on missing item
    item = items_db[item_id]  # KeyError → unhandled → 500
    return ItemResponse(**item)


@app.put(
    "/items/{item_id}",
    response_model=ItemResponse,
    responses={
        401: {"description": "Not authenticated"},
        404: {"description": "Item not found"},
        422: {"description": "Validation Error"},
    },
)
async def update_item(
    item_id: int,
    item_in: ItemUpdate,
    current_user: dict = Depends(get_current_user),
) -> ItemResponse:
    if item_id not in items_db:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")

    item = items_db[item_id]
    if item_in.title is not None:
        item["title"] = item_in.title
    if item_in.description is not None:
        item["description"] = item_in.description
    if item_in.price is not None:
        item["price"] = item_in.price
    items_db[item_id] = item
    return ItemResponse(**item)


@app.delete(
    "/items/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        204: {"description": "Item successfully deleted"},
        401: {"description": "Not authenticated"},
        404: {"description": "Item not found"},
    },
)
async def delete_item(
    item_id: int,
    current_user: dict = Depends(get_current_user),
):
    if item_id not in items_db:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")

    del items_db[item_id]
    # BUG-1: Returns 200 instead of spec-required 204
    return JSONResponse(status_code=200, content={"deleted": True})
