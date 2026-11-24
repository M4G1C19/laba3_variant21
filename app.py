from fastapi import FastAPI, Form, Request, File, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException
import pandas as pd
import hashlib, shutil, uuid, os
from datetime import datetime

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/images", StaticFiles(directory="images"), name="images")
templates = Jinja2Templates(directory="templates")

AVATAR_DIR = "images"
os.makedirs(AVATAR_DIR, exist_ok=True)

default_img_path = os.path.join(AVATAR_DIR, "default.png")
if not os.path.exists(default_img_path):
    import base64
    img_data = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=")
    with open(default_img_path, "wb") as f:
        f.write(img_data)

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()

if not os.path.exists("users.csv"):
    pd.DataFrame([{"username": "admin", "password": hash_password("admin"), "role": "admin", "avatar": "/images/default.png", "user_id": 0}]).to_csv("users.csv", index=False)

if not os.path.exists("data.csv"):
    pd.DataFrame(columns=["id", "name", "country", "ingredients", "image", "rating"]).to_csv("data.csv", index=False)

if not os.path.exists("logs.csv"):
    pd.DataFrame(columns=["timestamp", "user", "action", "path"]).to_csv("logs.csv", index=False)

def log_action(user, action, path):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    new_log = pd.DataFrame([{"timestamp": now, "user": user or "guest", "action": action, "path": path}])
    new_log.to_csv("logs.csv", mode="a", header=False, index=False)

@app.middleware("http")
async def auth_and_log_middleware(request: Request, call_next):
    path = request.url.path
    user = request.session.get("username")
    
    if not path.startswith("/static") and not path.startswith("/images"):
        log_action(user, "GET Request", path)

    if path.startswith("/edit") or path.startswith("/delete"):
        if request.session.get("role") != "admin":
            return RedirectResponse("/404", status_code=302)
    
    if path in ["/profile"]:
        if not user:
            return RedirectResponse("/login", status_code=302)

    return await call_next(request)

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    df = pd.read_csv("data.csv")
    foods = df.to_dict(orient="records")
    user = request.session.get("username")
    role = request.session.get("role")
    avatar = request.session.get("avatar")
    return templates.TemplateResponse(request=request, name="home.html", context={"foods": foods, "user": user, "role": role, "avatar": avatar})

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(request=request, name="login.html", context={"user": None, "role": None})

@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    df = pd.read_csv("users.csv")
    users = df.to_dict(orient="records")
    for u in users:
        if u["username"] == username and u["password"] == hash_password(password):
            request.session["username"] = username
            request.session["role"] = u["role"]
            request.session["avatar"] = u["avatar"]
            request.session["user_id"] = u["user_id"]
            log_action(username, "LOGIN_SUCCESS", "/login")
            return RedirectResponse("/", status_code=302)
    
    log_action(username, "LOGIN_FAILED", "/login")
    return templates.TemplateResponse(request=request, name="login.html", context={"error": "Неверный логин или пароль", "user": None, "role": None})

@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    return templates.TemplateResponse(request=request, name="register.html", context={"user": None, "role": None})

@app.post("/register")
def register(request: Request, username: str = Form(...), password: str = Form(...), avatar: UploadFile = File(...)):
    df = pd.read_csv("users.csv")
    if username in df["username"].values:
        return templates.TemplateResponse(request=request, name="register.html", context={"error": "Пользователь уже существует", "user": None, "role": None})
    
    ext = os.path.splitext(avatar.filename)[1]
    filename = f"{uuid.uuid4()}{ext}"
    with open(os.path.join(AVATAR_DIR, filename), "wb") as buffer:
        shutil.copyfileobj(avatar.file, buffer)
    
    new_user = {
        "username": username,
        "password": hash_password(password),
        "role": "reader",
        "avatar": f"/images/{filename}",
        "user_id": len(df)
    }
    pd.DataFrame([new_user]).to_csv("users.csv", mode="a", header=False, index=False)
    request.session["username"] = username
    request.session["role"] = "reader"
    request.session["avatar"] = new_user["avatar"]
    log_action(username, "REGISTER", "/register")
    return RedirectResponse("/", status_code=302)

@app.get("/logout")
def logout(request: Request):
    log_action(request.session.get("username"), "LOGOUT", "/logout")
    request.session.clear()
    return RedirectResponse("/", status_code=302)

@app.get("/profile", response_class=HTMLResponse)
def profile(request: Request):
    return templates.TemplateResponse(request=request, name="profile.html", context={
        "user": request.session.get("username"), 
        "role": request.session.get("role"),
        "avatar": request.session.get("avatar")
    })

@app.get("/edit", response_class=HTMLResponse)
def edit_page(request: Request):
    df = pd.read_csv("data.csv")
    foods = df.to_dict(orient="records")
    return templates.TemplateResponse(request=request, name="edit_food.html", context={"foods": foods, "user": request.session.get("username"), "role": request.session.get("role")})

@app.post("/edit")
def add_food(request: Request, name: str = Form(...), country: str = Form(...), ingredients: str = Form(...), rating: float = Form(...), image: UploadFile = File(...)):
    ext = os.path.splitext(image.filename)[1]
    filename = f"{uuid.uuid4()}{ext}"
    with open(os.path.join(AVATAR_DIR, filename), "wb") as buffer:
        shutil.copyfileobj(image.file, buffer)
    
    df = pd.read_csv("data.csv")
    new_id = int(df["id"].max() + 1) if not df.empty else 0
    
    new_food = {
        "id": new_id,
        "name": name,
        "country": country,
        "ingredients": ingredients,
        "image": f"/images/{filename}",
        "rating": rating
    }
    pd.DataFrame([new_food]).to_csv("data.csv", mode="a", header=False, index=False)
    log_action(request.session.get("username"), f"ADD_FOOD: {name}", "/edit")
    return RedirectResponse("/", status_code=302)

@app.get("/delete/{food_id}")
def delete_food(request: Request, food_id: int):
    df = pd.read_csv("data.csv")
    df = df[df["id"] != food_id]
    df.to_csv("data.csv", index=False)
    log_action(request.session.get("username"), f"DELETE_FOOD ID: {food_id}", "/delete")
    return RedirectResponse("/", status_code=302)

@app.exception_handler(404)
def not_found(request: Request, exc):
    return templates.TemplateResponse(request=request, name="404.html", context={"user": request.session.get("username"), "role": request.session.get("role")}, status_code=404)

app.add_middleware(SessionMiddleware, secret_key="secret_recipe_key", max_age=300, https_only=False)