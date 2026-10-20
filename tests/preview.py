"""Offline UI fixture. Never connects to Telegram; uses an isolated preview database.

Run: .venv/Scripts/python.exe -m tests.preview
"""
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import uvicorn
from telethon import types

from app.web import create_app


class OfflineCollector:
    """Deterministic synthetic groups; no Telegram connection is possible."""
    def is_connected(self): return True
    async def is_user_authorized(self): return True
    async def disconnect(self): pass
    async def get_entity(self, target):
        return types.Chat(id=4242,title="گروه آزمایشی · بدون اتصال واقعی",photo=types.ChatPhotoEmpty(),
                          participants_count=3,date=datetime.now(timezone.utc),version=1)
    async def iter_dialogs(self):
        yield SimpleNamespace(id=-4242,name="گروه آزمایشی · بدون اتصال واقعی",is_group=True,
                              entity=SimpleNamespace(participants_count=3))
    async def get_participants(self,*args,**kwargs): return SimpleNamespace(total=3)
    async def iter_participants(self,*args,**kwargs):
        for i in range(1,4):
            yield types.User(id=1000+i,first_name=f"نویسنده آزمایشی {i}",username=f"demo_author_{i}",access_hash=i)
    async def iter_messages(self,*args,**kwargs):
        for i,days in enumerate([1,10,100],1):
            author=types.User(id=1000+i,first_name=f"نویسنده آزمایشی {i}",username=f"demo_author_{i}",access_hash=i)
            yield SimpleNamespace(sender=author,sender_id=author.id,action=None,
                                  date=datetime.now(timezone.utc)-timedelta(days=days))


def main():
    data = Path(__file__).resolve().parent.parent / ".cache" / "preview" / uuid.uuid4().hex
    os.environ["TABCHI_DATA_DIR"] = str(data)
    app = create_app(data)
    store, engine = app.state.store, app.state.engine
    for index, account_id in enumerate(["demo-alpha", "demo-beta"]):
        store.execute("INSERT INTO accounts(id,label,phone,user_id,username,status) VALUES (?,?,?,?,?,'connected')",
                      (account_id, ["حساب آزمایشی اول", "حساب آزمایشی دوم"][index], f"+1555000000{index}", 9000+index, "demo_account"+str(index)))
    lid = engine.import_csv("فهرست آزمایشی · بدون اتصال واقعی", ("username\n" + "\n".join(f"demo_user_{i}" for i in range(1,24))).encode())
    names = ["علی رضایی", "نگار احمدی", "سارا محمدی", "محمد کریمی", "مریم عباسی"]
    for i, row in enumerate(store.all("SELECT id FROM members")):
        store.execute("UPDATE members SET name=? WHERE id=?", (names[i%len(names)], row["id"]))
    engine.create_campaign("پیش‌نمایش آزمایشی · ارسال غیرفعال", lid,
                           "سلام!\nاین یک پیام نمونه برای بررسی چیدمان فارسی و پیش‌نمایش کمپین است.\nhttps://example.com", None,
                           ["demo-alpha", "demo-beta"], 10, 30, 60)
    def no_send(*args, **kwargs):
        from app.engine import Problem
        raise Problem("این محیط آزمایشی است و ارسال پیام در آن غیرفعال است.")
    engine.start = no_send
    engine.clients = {"demo-alpha": OfflineCollector(), "demo-beta": OfflineCollector()}
    uvicorn.run(app, host="127.0.0.1", port=8766, access_log=False)


if __name__ == "__main__":
    main()
