import csv
import asyncio
import hashlib
import io
import json
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field, model_validator
from telethon import errors

from .engine import Engine, Problem, STOP_ERRORS, uid
from .store import Store

ROOT = Path(__file__).resolve().parent.parent


class Credentials(BaseModel):
    api_id: int = Field(gt=0)
    api_hash: str = Field(pattern=r"^[a-fA-F0-9]{32}$")


class Login(BaseModel):
    label: str = Field(min_length=1, max_length=100)
    phone: str = Field(max_length=30)


class Verify(BaseModel):
    code: str | None = Field(default=None, max_length=20)
    password: str | None = Field(default=None, max_length=256)


class Source(BaseModel):
    account_id: str
    group_id: int


class Collect(BaseModel):
    title: str = Field(min_length=1, max_length=150)
    sources: list[Source] = Field(min_length=1, max_length=50)
    method: Literal["members", "history"] = "members"
    days_back: int | None = Field(default=None, ge=1, le=36500, strict=True)

    @model_validator(mode="after")
    def history_period(self):
        if self.method != "history" and self.days_back is not None:
            raise ValueError("فیلتر روز فقط برای تاریخچه گفتگو است.")
        return self


class Campaign(BaseModel):
    title: str = Field(min_length=1, max_length=150)
    list_id: str
    text: str = Field(default="", max_length=4096)
    photo_id: str | None = None
    account_ids: list[str] = Field(min_length=1, max_length=100)
    batch_size: int = Field(default=10, ge=1, le=10000)
    delay_min: float = Field(default=30, ge=1, le=86400, allow_inf_nan=False)
    delay_max: float = Field(default=60, ge=1, le=86400, allow_inf_nan=False)

    @model_validator(mode="after")
    def bounds(self):
        if self.delay_min > self.delay_max:
            raise ValueError("حداقل زمان نباید از حداکثر بیشتر باشد.")
        return self


class Exclusion(BaseModel):
    excluded: bool


class Accounts(BaseModel):
    account_ids: list[str] = Field(min_length=1, max_length=100)


class Resolution(BaseModel):
    action: str = Field(pattern="^(sent|pending|skipped)$")


def create_app(data_root=None, client_factory=None):
    store = Store(Path(data_root or os.getenv("TABCHI_DATA_DIR", ROOT / "data")))
    engine = Engine(store, client_factory)
    token = secrets.token_urlsafe(32)
    cookie_name = "tabchi_" + hashlib.sha256(str(store.root.resolve()).encode()).hexdigest()[:12]

    @asynccontextmanager
    async def lifespan(app):
        store.recover()
        yield
        await engine.close()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.engine = engine
    app.state.store = store

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        host = request.headers.get("host", "").split(":")[0]
        origin = request.headers.get("origin")
        expected = f"http://{request.headers.get('host', '')}"
        if host not in {"127.0.0.1", "localhost", "testserver"}:
            return JSONResponse({"detail": "Local access only"}, status_code=403)
        if origin and origin != expected:
            return JSONResponse({"detail": "Foreign origin rejected"}, status_code=403)
        if request.headers.get("sec-fetch-site") == "cross-site":
            return JSONResponse({"detail": "Cross-site request rejected"}, status_code=403)
        if request.url.path.startswith("/api/"):
            if not secrets.compare_digest(request.cookies.get(cookie_name, ""), token):
                return JSONResponse({"detail": "Dashboard session required; reload the dashboard"}, status_code=403)
            if request.method not in {"GET", "HEAD", "OPTIONS"}:
                if not secrets.compare_digest(request.headers.get("x-csrf-token", ""), token):
                    return JSONResponse({"detail": "Invalid local request token"}, status_code=403)
                length = request.headers.get("content-length")
                if length and int(length) > 12 * 1024 * 1024:
                    return JSONResponse({"detail": "File too large"}, status_code=413)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; form-action 'self'; base-uri 'none'"
        if request.url.path.startswith(("/api/", "/static/")) or request.url.path in {"/", "/health"}:
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(Problem)
    async def problem_handler(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(errors.RPCError)
    async def telegram_handler(request, exc):
        # Telegram errors are identified by type, never raw request/secret repr.
        return JSONResponse({"detail": f"Telegram: {type(exc).__name__}",
                             "seconds": getattr(exc, "seconds", None)}, status_code=400)

    @app.exception_handler(OSError)
    async def network_handler(request, exc):
        return JSONResponse({"detail": "خطای ارتباط یا فایل؛ اتصال اینترنت و دسترسی فایل را بررسی کنید."}, status_code=503)

    @app.get("/")
    async def index():
        response = FileResponse(ROOT / "static" / "index.html")
        response.set_cookie(cookie_name, token, httponly=True, samesite="strict")
        return response

    @app.get("/health")
    async def health():
        return {"app": "tabchi", "instance_id": os.getenv("TABCHI_INSTANCE_ID", "")}

    @app.get("/api/bootstrap")
    async def bootstrap():
        return {"token": token}

    @app.get("/api/state")
    async def state():
        accounts = store.all("SELECT * FROM accounts WHERE status!='deleted' ORDER BY rowid")
        account_labels = {row["id"]: row["label"] + (" · حذف‌شده" if row["status"] == "deleted" else "")
                          for row in store.all("SELECT id,label,status FROM accounts")}
        lists = store.all("""SELECT l.*, COUNT(m.id) total, COALESCE(SUM(m.excluded=0),0) included
                             FROM lists l LEFT JOIN members m ON m.list_id=l.id WHERE l.status!='deleted' GROUP BY l.id ORDER BY l.created DESC""")
        campaigns = store.all("SELECT * FROM campaigns ORDER BY created DESC")
        for c in campaigns:
            c["counts"] = {r["status"]: r["n"] for r in store.all("SELECT status,COUNT(*) n FROM deliveries WHERE campaign_id=? GROUP BY status", (c["id"],))}
            c["account_ids"] = json.loads(c.pop("accounts_json"))
        return {"configured": bool(store.get_setting("credentials")), "accounts": accounts,
                "lists": lists, "campaigns": campaigns, "busy": engine.busy(), "account_labels": account_labels}

    @app.post("/api/credentials")
    async def credentials(body: Credentials):
        if engine.busy() or engine.clients:
            raise Problem("برای تغییر API، برنامه را ببندید و دوباره باز کنید و پیش از اتصال حساب‌ها آن را تغییر دهید.")
        store.set_setting("credentials", body.model_dump())
        return {"ok": True}

    @app.post("/api/accounts/login")
    async def login(body: Login):
        return await engine.login(body.label, body.phone)

    @app.post("/api/accounts/{account_id}/verify")
    async def verify(account_id: str, body: Verify):
        return await engine.verify_login(account_id, body.code, body.password)

    @app.post("/api/accounts/{account_id}/check")
    async def check(account_id: str):
        await engine.check_account(account_id)
        return {"ok": True}

    @app.delete("/api/accounts/{account_id}")
    async def delete_account(account_id: str):
        await engine.delete_account(account_id)
        return {"ok": True}

    @app.get("/api/accounts/{account_id}/groups")
    async def groups(account_id: str):
        return await engine.groups(account_id)

    @app.post("/api/lists/collect")
    async def collect(body: Collect):
        return {"id": engine.collect(body.title, [s.model_dump() for s in body.sources], body.method, body.days_back)}

    @app.delete("/api/lists/{list_id}")
    async def delete_list(list_id: str):
        engine.delete_list(list_id)
        return {"ok": True}

    @app.post("/api/cleanup")
    async def cleanup():
        return {"ok": True, "deleted_photos": engine.cleanup_uploads()}

    @app.post("/api/lists/import")
    async def import_list(file: UploadFile = File(...)):
        content = await file.read(5 * 1024 * 1024 + 1)
        if len(content) > 5 * 1024 * 1024:
            raise Problem("حداکثر حجم CSV پنج مگابایت است.")
        return {"id": engine.import_csv(Path(file.filename or "CSV").stem[:150], content)}

    @app.post("/api/lists/{list_id}/stop")
    async def stop_collection(list_id: str):
        engine.require("lists", list_id)
        task = engine.jobs.get("collect:" + list_id)
        if task and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            store.execute("UPDATE lists SET status='partial',note='جمع‌آوری متوقف شد.' WHERE id=? AND status='collecting'", (list_id,))
        return {"ok": True}

    @app.get("/api/lists/{list_id}/members")
    async def members(list_id: str, offset: int = 0, limit: int = 100, search: str = ""):
        engine.require("lists", list_id)
        if offset < 0 or limit not in range(1, 501):
            raise Problem("صفحه معتبر نیست.")
        query = "%" + search[:100] + "%"
        total = store.one("SELECT COUNT(*) n FROM members WHERE list_id=? AND (name LIKE ? OR username LIKE ?)", (list_id, query, query))["n"]
        rows = store.all("SELECT id,user_id,username,name,excluded FROM members WHERE list_id=? AND (name LIKE ? OR username LIKE ?) ORDER BY id LIMIT ? OFFSET ?",
                         (list_id, query, query, limit, offset))
        return {"total": total, "rows": rows}

    @app.post("/api/lists/{list_id}/members/{member_id}")
    async def exclude(list_id: str, member_id: int, body: Exclusion):
        source = engine.require("lists", list_id)
        if source["status"] == "collecting":
            raise Problem("ابتدا جمع‌آوری را تمام کنید.")
        store.execute("UPDATE members SET excluded=? WHERE id=? AND list_id=?", (int(body.excluded), member_id, list_id))
        return {"ok": True}

    @app.post("/api/photos")
    async def photo(file: UploadFile = File(...)):
        content = await file.read(10 * 1024 * 1024 + 1)
        if len(content) > 10 * 1024 * 1024:
            raise Problem("حداکثر حجم عکس ۱۰ مگابایت است.")
        try:
            with Image.open(io.BytesIO(content)) as image:
                if image.format not in {"JPEG", "PNG"} or image.width + image.height > 10000 or max(image.size) / min(image.size) > 20:
                    raise Problem("یک عکس PNG یا JPEG با ابعاد مناسب تلگرام انتخاب کنید.")
                ext = ".jpg" if image.format == "JPEG" else ".png"
                image.verify()
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError, ValueError):
            raise Problem("فایل عکس معتبر نیست.")
        photo_id = uid()
        relative = f"uploads/{photo_id}{ext}"
        (store.root / relative).write_bytes(content)
        store.execute("INSERT INTO uploads VALUES (?,?,?)", (photo_id, relative, "image/jpeg" if ext == ".jpg" else "image/png"))
        return {"id": photo_id}

    @app.get("/api/photos/{photo_id}")
    async def show_photo(photo_id: str):
        row = engine.require("uploads", photo_id)
        return FileResponse(store.root / row["path"], media_type=row["mime"])

    @app.post("/api/campaigns")
    async def create_campaign(body: Campaign):
        return {"id": engine.create_campaign(**body.model_dump())}

    @app.delete("/api/campaigns/{campaign_id}")
    async def delete_campaign(campaign_id: str):
        return engine.delete_campaign(campaign_id)

    @app.get("/api/campaigns/{campaign_id}")
    async def campaign(campaign_id: str, offset: int = 0, limit: int = 100):
        c = engine.require("campaigns", campaign_id)
        if offset < 0 or limit not in range(1, 501):
            raise Problem("صفحه معتبر نیست.")
        rows = store.all("SELECT id,user_id,username,name,account_id,status,error,message_id,attempted_at FROM deliveries WHERE campaign_id=? ORDER BY id LIMIT ? OFFSET ?", (campaign_id, limit, offset))
        total = store.one("SELECT COUNT(*) n FROM deliveries WHERE campaign_id=?", (campaign_id,))["n"]
        c["account_ids"] = json.loads(c.pop("accounts_json"))
        return {"campaign": c, "rows": rows, "total": total}

    @app.post("/api/campaigns/{campaign_id}/review")
    async def review(campaign_id: str):
        engine.review(campaign_id)
        return {"ok": True}

    @app.post("/api/campaigns/{campaign_id}/accounts")
    async def reassign(campaign_id: str, body: Accounts):
        engine.reassign(campaign_id, body.account_ids)
        return {"ok": True}

    @app.post("/api/campaigns/{campaign_id}/start")
    async def start(campaign_id: str):
        engine.start(campaign_id)
        return {"ok": True}

    @app.post("/api/campaigns/{campaign_id}/pause")
    async def pause(campaign_id: str):
        engine.stop(campaign_id)
        return {"ok": True}

    @app.post("/api/campaigns/{campaign_id}/cancel")
    async def cancel(campaign_id: str):
        engine.stop(campaign_id, cancel=True)
        return {"ok": True}

    @app.post("/api/campaigns/{campaign_id}/deliveries/{delivery_id}/resolve")
    async def resolve(campaign_id: str, delivery_id: int, body: Resolution):
        engine.resolve_uncertain(campaign_id, delivery_id, body.action)
        return {"ok": True}

    @app.get("/api/campaigns/{campaign_id}/report")
    async def report(campaign_id: str):
        engine.require("campaigns", campaign_id)
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(["user_id", "username", "name", "account", "status", "error", "message_id", "attempted_at"])
        for row in store.all("""SELECT d.*, a.label FROM deliveries d JOIN accounts a ON a.id=d.account_id
                                WHERE campaign_id=? ORDER BY d.id""", (campaign_id,)):
            values = [row[k] for k in ["user_id", "username", "name", "label", "status", "error", "message_id", "attempted_at"]]
            # Prevent spreadsheet formulas when names/labels are opened in Excel.
            writer.writerow(["'" + v if isinstance(v, str) and v.startswith(("=", "+", "-", "@", "\t", "\r")) else v for v in values])
        return Response("\ufeff" + output.getvalue(), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="campaign-{campaign_id}.csv"'})

    app.mount("/static", StaticFiles(directory=ROOT / "static", check_dir=False), name="static")
    return app


app = create_app()
