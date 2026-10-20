"""Collection and sending use different persisted queues. No sending occurs at import."""
import asyncio
import csv
import io
import json
import random
import re
import time
import uuid
from datetime import datetime, timedelta, timezone

from telethon import TelegramClient, errors, types

from .store import Store, now


class Problem(Exception):
    pass


def uid():
    return uuid.uuid4().hex


def normalize_username(value):
    value = value.strip().removeprefix("https://t.me/").removeprefix("http://t.me/").lstrip("@")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{3,31}", value):
        raise Problem("نام کاربری معتبر نیست؛ فقط نام کاربری عمومی تلگرام وارد کنید.")
    return value.lower()


STOP_ERRORS = {"FloodWaitError", "FloodPremiumWaitError", "PeerFloodError", "UserRestrictedError",
               "UserDeactivatedBanError", "UserDeactivatedError", "AuthKeyUnregisteredError",
               "SessionRevokedError", "SessionExpiredError", "PhoneNumberBannedError", "AuthKeyDuplicatedError"}
SKIP_ERRORS = {"UserPrivacyRestrictedError", "UserIsBlockedError", "YouBlockedUserError",
               "InputUserDeactivatedError", "UserNotMutualContactError", "UserIdInvalidError",
               "PeerIdInvalidError", "UsernameInvalidError", "UsernameNotOccupiedError",
               "ChatWriteForbiddenError", "UserBannedInChannelError"}


class Engine:
    def __init__(self, store: Store, client_factory=None):
        self.s = store
        self.factory = client_factory or TelegramClient
        self.clients = {}
        self.pending_codes = {}
        self.jobs = {}
        self.closed = False

    def require(self, table, identifier):
        if table not in {"accounts", "lists", "campaigns", "uploads"}:
            raise ValueError(table)
        row = self.s.one(f"SELECT * FROM {table} WHERE id=?", (identifier,))
        if not row:
            raise Problem("مورد پیدا نشد.")
        if table == "accounts" and row["status"] in {"deleted", "deleting"}:
            raise Problem("این حساب از برنامه حذف شده یا در حال حذف است؛ حساب دیگری انتخاب کنید.")
        if table == "lists" and row["status"] == "deleted":
            raise Problem("این فهرست حذف شده است.")
        return row

    def busy(self):
        return any(not task.done() for task in self.jobs.values())

    def credentials(self):
        value = self.s.get_setting("credentials")
        if not value:
            raise Problem("ابتدا API ID و API Hash را در تنظیمات ثبت کنید.")
        return value

    async def client(self, account_id, authorized=True):
        self.require("accounts", account_id)
        if account_id not in self.clients:
            cred = self.credentials()
            self.clients[account_id] = self.factory(
                str(self.s.root / "sessions" / account_id), cred["api_id"], cred["api_hash"],
                flood_sleep_threshold=0, request_retries=0, connection_retries=2,
                receive_updates=False)
        client = self.clients[account_id]
        if not client.is_connected():
            await client.connect()
        if authorized:
            is_authorized = await client.is_user_authorized()
            self.require("accounts", account_id)
            if not is_authorized:
                self.s.execute("UPDATE accounts SET status='disconnected', error='Authorization required' WHERE id=?", (account_id,))
                raise Problem("ورود این حساب منقضی شده است؛ دوباره متصل شوید.")
        self.require("accounts", account_id)
        return client

    async def login(self, label, phone):
        if self.busy():
            raise Problem("برای ورود به حساب، ابتدا کار در حال اجرا را متوقف کنید.")
        self.credentials()
        phone = re.sub(r"[\s()-]", "", phone)
        if not re.fullmatch(r"\+[1-9][0-9]{6,14}", phone):
            raise Problem("شماره را با کد کشور وارد کنید؛ مانند ‎+989121234567.")
        old = self.s.one("SELECT * FROM accounts WHERE phone=?", (phone,))
        account_id = old["id"] if old else uid()
        if not old:
            self.s.execute("INSERT INTO accounts(id,label,phone,status) VALUES (?,?,?,'pending')",
                           (account_id, label.strip() or phone, phone))
        client = await self.client(account_id, authorized=False)
        if await client.is_user_authorized():
            await self.finish_login(account_id, await client.get_me())
            return {"id": account_id, "step": "done"}
        try:
            sent = await client.send_code_request(phone)
        except Exception as exc:
            # A concurrent delete must not be undone by an old login response.
            self.require("accounts", account_id)
            if type(exc).__name__ in STOP_ERRORS:
                self.restrict(account_id, exc)
            else:
                self.s.execute("UPDATE accounts SET status='disconnected',error=? WHERE id=?", (type(exc).__name__, account_id))
            raise
        self.require("accounts", account_id)
        self.pending_codes[account_id] = sent.phone_code_hash
        self.s.execute("UPDATE accounts SET status='pending', error=NULL WHERE id=?", (account_id,))
        return {"id": account_id, "step": "code"}

    async def verify_login(self, account_id, code=None, password=None):
        account = self.require("accounts", account_id)
        if account_id not in self.pending_codes:
            raise Problem("درخواست کد ورود را دوباره ارسال کنید.")
        client = await self.client(account_id, authorized=False)
        try:
            if password is not None:
                user = await client.sign_in(password=password)
            else:
                user = await client.sign_in(phone=account["phone"], code=code,
                                            phone_code_hash=self.pending_codes[account_id])
        except errors.SessionPasswordNeededError:
            return {"id": account_id, "step": "password"}
        await self.finish_login(account_id, user)
        self.pending_codes.pop(account_id, None)
        return {"id": account_id, "step": "done"}

    async def finish_login(self, account_id, user):
        self.require("accounts", account_id)
        other = self.s.one("SELECT id FROM accounts WHERE user_id=? AND id!=?", (user.id, account_id))
        if other:
            raise Problem("این حساب قبلاً اضافه شده است.")
        self.s.execute("UPDATE accounts SET user_id=?, username=?, status='connected', error=NULL, wait_until=0 WHERE id=?",
                       (user.id, user.username, account_id))

    async def check_account(self, account_id):
        if self.busy():
            raise Problem("ابتدا عملیات جاری را متوقف کنید.")
        account = self.require("accounts", account_id)
        if account["wait_until"] > time.time():
            raise Problem("زمان انتظار اعلام‌شده توسط تلگرام هنوز تمام نشده است.")
        client = await self.client(account_id)
        await self.finish_login(account_id, await client.get_me())

    async def delete_account(self, account_id):
        if self.busy():
            raise Problem("ابتدا جمع‌آوری یا ارسال جاری را متوقف کنید و منتظر پایان درخواست جاری بمانید.")
        account = self.s.one("SELECT * FROM accounts WHERE id=?", (account_id,))
        if not account or account["status"] == "deleted":
            raise Problem("حساب پیدا نشد یا قبلاً حذف شده است.")
        session_root = (self.s.root / "sessions").resolve()
        session_files = [(session_root / f"{account_id}.session{suffix}").resolve()
                         for suffix in ("", "-journal", "-wal", "-shm")]
        if any(path.parent != session_root for path in session_files):
            raise Problem("مسیر نشست حساب معتبر نیست.")
        # Block new requests and late login responses before awaiting disconnect.
        # A failed cleanup remains retryable, without reopening the account.
        self.s.execute("UPDATE accounts SET status='deleting' WHERE id=?", (account_id,))
        self.pending_codes.pop(account_id, None)
        client = self.clients.get(account_id)
        if client is not None:
            await client.disconnect()
        for path in session_files:
            path.unlink(missing_ok=True)
        self.clients.pop(account_id, None)
        with self.s.db() as db:
            db.execute("""UPDATE campaigns SET status='draft',reviewed_at=NULL,
                          note='حساب ارسال حذف شد؛ حساب‌های گیرنده‌های باقی‌مانده را تغییر دهید و دوباره تأیید کنید.'
                          WHERE status NOT IN ('completed','cancelled') AND id IN
                          (SELECT campaign_id FROM deliveries WHERE account_id=? AND status IN ('pending','sending','uncertain'))""",
                       (account_id,))
            # Keep a minimal tombstone for foreign keys and historical reports.
            # Release phone/user uniqueness so the same account can be re-added.
            db.execute("""UPDATE accounts SET status='deleted',phone=?,user_id=NULL,
                          username=NULL,error=NULL,wait_until=0 WHERE id=?""",
                       (f"deleted:{account_id}", account_id))

    async def groups(self, account_id):
        if self.busy():
            raise Problem("ابتدا عملیات جاری را متوقف کنید.")
        client = await self.client(account_id)
        result = []
        async for dialog in client.iter_dialogs():
            if dialog.is_group:
                result.append({"id": str(dialog.id), "title": dialog.name,
                               "count": getattr(dialog.entity, "participants_count", None)})
        return result

    def make_list(self, title, source, status="collecting"):
        list_id = uid()
        self.s.execute("INSERT INTO lists(id,title,status,source,created) VALUES (?,?,?,?,?)",
                       (list_id, title.strip(), status, source, now()))
        return list_id

    def require_idle(self):
        if self.busy():
            raise Problem("ابتدا جمع‌آوری یا ارسال جاری را متوقف کنید و منتظر پایان درخواست جاری بمانید.")

    def delete_list(self, list_id):
        self.require_idle()
        self.require("lists", list_id)
        with self.s.db() as db:
            db.execute("DELETE FROM members WHERE list_id=?", (list_id,))
            if db.execute("SELECT 1 FROM campaigns WHERE list_id=? LIMIT 1", (list_id,)).fetchone():
                # Existing campaigns own independent recipient snapshots.
                db.execute("UPDATE lists SET status='deleted',title='فهرست حذف‌شده',source='deleted',note='' WHERE id=?", (list_id,))
            else:
                db.execute("DELETE FROM lists WHERE id=?", (list_id,))
        self.jobs.pop("collect:" + list_id, None)

    def cleanup_uploads(self, photo_ids=None):
        self.require_idle()
        photos = self.s.all("SELECT * FROM uploads WHERE NOT EXISTS (SELECT 1 FROM campaigns WHERE photo_id=uploads.id)")
        if photo_ids is not None:
            photos = [p for p in photos if p["id"] in photo_ids]
        root = (self.s.root / "uploads").resolve()
        paths = [(p, (self.s.root / p["path"]).resolve()) for p in photos]
        if any(path.parent != root for _, path in paths):
            raise Problem("مسیر فایل عکس معتبر نیست؛ هیچ فایل خارج از پوشه عکس‌ها پاک نشد.")
        for photo, path in paths:
            path.unlink(missing_ok=True)
            self.s.execute("DELETE FROM uploads WHERE id=?", (photo["id"],))
        return len(paths)

    def delete_campaign(self, campaign_id):
        self.require_idle()
        campaign = self.require("campaigns", campaign_id)
        with self.s.db() as db:
            db.execute("DELETE FROM deliveries WHERE campaign_id=?", (campaign_id,))
            db.execute("DELETE FROM campaigns WHERE id=?", (campaign_id,))
            db.execute("DELETE FROM lists WHERE status='deleted' AND NOT EXISTS (SELECT 1 FROM campaigns WHERE list_id=lists.id)")
            db.execute("DELETE FROM accounts WHERE status='deleted' AND NOT EXISTS (SELECT 1 FROM deliveries WHERE account_id=accounts.id)")
        self.jobs.pop("send:" + campaign_id, None)
        warning = None
        if campaign["photo_id"]:
            try:
                self.cleanup_uploads({campaign["photo_id"]})
            except (OSError, Problem):
                warning = "کمپین حذف شد؛ برای حذف عکس باقی‌مانده، پاکسازی عکس‌های بدون استفاده را دوباره اجرا کنید."
        return {"ok": True, "cleanup_warning": warning}

    def collect(self, title, sources, method="members", days_back=None):
        if self.busy():
            raise Problem("یک عملیات دیگر در حال اجرا است؛ ابتدا آن را متوقف کنید.")
        if not sources:
            raise Problem("حداقل یک گروه انتخاب کنید.")
        if method not in {"members", "history"}:
            raise Problem("روش جمع‌آوری معتبر نیست.")
        if days_back is not None and (method != "history" or type(days_back) is not int or not 1 <= days_back <= 36500):
            raise Problem("تعداد روز باید عدد صحیح بین ۱ و ۳۶۵۰۰ باشد و فقط برای تاریخچه استفاده شود.")
        for source in sources:
            account = self.require("accounts", source["account_id"])
            if account["status"] != "connected":
                raise Problem("همه حساب‌های جمع‌آوری باید متصل باشند.")
        started = datetime.now(timezone.utc)
        cutoff = started - timedelta(days=days_back) if days_back is not None else None
        metadata = {"method": method, "days_back": days_back, "started_at": started.isoformat(),
                    "cutoff_at": cutoff.isoformat() if cutoff else None, "groups": sources}
        list_id = self.make_list(title, json.dumps(metadata, ensure_ascii=False))
        self.jobs["collect:" + list_id] = asyncio.create_task(self._collect(list_id, sources, method, started, cutoff))
        return list_id

    def save_collected_user(self, list_id, account_id, user, own_ids):
        if not isinstance(user, types.User) or user.bot or user.deleted or user.id in own_ids:
            return False
        # A minimal user hash is context-bound, not a reusable InputPeerUser hash.
        access = {account_id: str(user.access_hash)} if user.access_hash is not None and not user.min else {}
        member = self.s.one("SELECT * FROM members WHERE list_id=? AND user_id=?", (list_id, user.id))
        name = " ".join(filter(None, [user.first_name, user.last_name]))
        if member:
            merged = json.loads(member["access_json"])
            merged.update(access)
            self.s.execute("UPDATE members SET access_json=?,username=?,name=? WHERE id=?",
                           (json.dumps(merged), user.username or member["username"], name or member["name"], member["id"]))
        else:
            self.s.execute("INSERT INTO members(list_id,user_id,username,name,access_json) VALUES (?,?,?,?,?)",
                           (list_id, user.id, user.username, name, json.dumps(access)))
        return True

    async def collect_history(self, list_id, account_id, client, entity, own_ids, notes, started, cutoff):
        scanned, authors, resolved, unresolved = 0, set(), set(), set()
        notes.append("")
        slot = len(notes) - 1

        def progress():
            notes[slot] = f"{entity.title}: {scanned} پیام بررسی‌شده · {len(authors)} نویسنده · {len(unresolved)} نویسنده نامشخص"
            self.s.execute("UPDATE lists SET note=? WHERE id=?", ("\n".join(notes), list_id))

        progress()
        try:
            # No message-count cap. Walk newest to oldest; new arrivals do not
            # change the fixed collection window. Never persist message bodies.
            async for message in client.iter_messages(entity, limit=None, wait_time=1):
                scanned += 1
                if scanned % 100 == 0:
                    progress()
                    await asyncio.sleep(0)
                date = message.date
                if date.tzinfo is None:
                    date = date.replace(tzinfo=timezone.utc)
                if date > started:
                    continue
                if cutoff is not None and date < cutoff:
                    break
                if getattr(message, "action", None):
                    continue
                sender_id = message.sender_id
                if sender_id is not None and (sender_id <= 0 or sender_id in resolved):
                    continue
                user = message.sender
                if user is None:
                    if sender_id is None or sender_id in unresolved:
                        continue
                    try:
                        user = await message.get_sender()
                    except (ValueError, TypeError):
                        unresolved.add(sender_id)
                        continue
                    except errors.RPCError as exc:
                        if type(exc).__name__ not in SKIP_ERRORS:
                            raise
                        unresolved.add(sender_id)
                        continue
                if not isinstance(user, types.User):
                    if sender_id is not None and user is None:
                        unresolved.add(sender_id)
                    continue
                resolved.add(user.id)
                unresolved.discard(user.id)
                if self.save_collected_user(list_id, account_id, user, own_ids):
                    authors.add(user.id)
        finally:
            progress()
        return bool(unresolved)

    async def _collect(self, list_id, sources, method="members", started=None, cutoff=None):
        notes, partial = [], False
        own_ids = {r["user_id"] for r in self.s.all("SELECT user_id FROM accounts")}
        try:
            for source in sources:
                account_id = source["account_id"]
                label = str(source["group_id"])
                try:
                    client = await self.client(account_id)
                    entity = await client.get_entity(int(source["group_id"]))
                    if not isinstance(entity, (types.Chat, types.Channel)) or getattr(entity, "broadcast", False):
                        raise Problem("انتخاب باید یک گروه باشد.")
                    label = entity.title
                    if method == "history":
                        incomplete = await self.collect_history(list_id, account_id, client, entity, own_ids,
                                                                notes, started, cutoff)
                        partial = partial or incomplete
                        continue
                    count = await client.get_participants(entity, limit=0)
                    expected = getattr(count, "total", None)
                    seen = set()
                    async for user in client.iter_participants(entity):
                        seen.add(user.id)
                        self.save_collected_user(list_id, account_id, user, own_ids)
                    if expected is None or len(seen) < expected:
                        partial = True
                    notes.append(f"{label}: {len(seen)} / {expected if expected is not None else '?'}")
                except Exception as exc:
                    partial = True
                    notes.append(f"{label}: {type(exc).__name__}")
                    if type(exc).__name__ in STOP_ERRORS:
                        self.restrict(account_id, exc)
                        break
            count = self.s.one("SELECT COUNT(*) n FROM members WHERE list_id=?", (list_id,))["n"]
            status = "partial" if partial else "ready"
            if not count and partial:
                status = "failed"
            self.s.execute("UPDATE lists SET status=?, note=? WHERE id=?", (status, "\n".join(notes), list_id))
        except asyncio.CancelledError:
            notes.append("جمع‌آوری متوقف شد؛ افراد ذخیره‌شده حفظ شدند.")
            self.s.execute("UPDATE lists SET status='partial', note=? WHERE id=?", ("\n".join(notes), list_id))
            raise
        except Exception as exc:
            self.s.execute("UPDATE lists SET status='partial', note=? WHERE id=?", (type(exc).__name__, list_id))

    def import_csv(self, title, content):
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise Problem("فایل CSV باید با UTF-8 ذخیره شده باشد.")
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames or "username" not in reader.fieldnames:
            raise Problem("فایل باید ستون username داشته باشد.")
        users, duplicates, bad = {}, 0, 0
        for index, row in enumerate(reader):
            if index >= 100000:
                raise Problem("حداکثر ۱۰۰٬۰۰۰ سطر در هر فایل مجاز است.")
            try:
                username = normalize_username(row.get("username") or "")
                if username in users:
                    duplicates += 1
                users[username] = username
            except Problem:
                bad += 1
        if not users:
            raise Problem("هیچ نام کاربری معتبری در فایل پیدا نشد.")
        list_id = self.make_list(title, "CSV", "ready")
        with self.s.db() as db:
            db.executemany("INSERT INTO members(list_id,username,name) VALUES (?,?,?)",
                           [(list_id, name, name) for name in users])
            db.execute("UPDATE lists SET note=? WHERE id=?", (f"Duplicate rows: {duplicates}; invalid rows: {bad}", list_id))
        return list_id

    def create_campaign(self, title, list_id, text, photo_id, account_ids, batch_size, delay_min, delay_max):
        source = self.require("lists", list_id)
        if source["status"] not in {"ready", "partial"}:
            raise Problem("ابتدا جمع‌آوری اعضا باید تمام شود.")
        if not text.strip() and not photo_id:
            raise Problem("متن یا عکس لازم است.")
        if len(text) > (1024 if photo_id else 4096):
            raise Problem("متن بیش از حد طولانی است؛ متن ۴۰۹۶ و زیرنویس عکس ۱۰۲۴ نویسه.")
        if photo_id:
            self.require("uploads", photo_id)
        self.validate_accounts(account_ids)
        members = self.s.all("SELECT * FROM members WHERE list_id=? AND excluded=0 ORDER BY id", (list_id,))
        own_ids = {r["user_id"] for r in self.s.all("SELECT user_id FROM accounts") if r["user_id"]}
        own_names = {r["username"].lower() for r in self.s.all("SELECT username FROM accounts WHERE username IS NOT NULL")}
        members = [m for m in members if m["user_id"] not in own_ids and (m["username"] or "").lower() not in own_names]
        if not members:
            raise Problem("فهرست گیرنده خالی است.")
        campaign_id = uid()
        with self.s.db() as db:
            db.execute("""INSERT INTO campaigns(id,title,list_id,status,text,photo_id,accounts_json,batch_size,
                          delay_min,delay_max,created) VALUES (?,?,?,'draft',?,?,?,?,?,?,?)""",
                       (campaign_id, title.strip(), list_id, text, photo_id, json.dumps(account_ids),
                        batch_size, delay_min, delay_max, now()))
            for i, member in enumerate(members):
                db.execute("""INSERT INTO deliveries(campaign_id,user_id,username,name,access_json,account_id)
                              VALUES (?,?,?,?,?,?)""",
                           (campaign_id, member["user_id"], member["username"], member["name"],
                            member["access_json"], account_ids[(i // batch_size) % len(account_ids)]))
        return campaign_id

    def validate_accounts(self, account_ids):
        if not account_ids or len(set(account_ids)) != len(account_ids):
            raise Problem("حساب‌های ارسال را بدون تکرار انتخاب کنید.")
        for account_id in account_ids:
            account = self.require("accounts", account_id)
            if account["status"] != "connected":
                raise Problem("حساب‌های انتخاب‌شده باید متصل باشند.")

    def review(self, campaign_id):
        c = self.require("campaigns", campaign_id)
        if c["status"] != "draft":
            raise Problem("فقط پیش‌نویس قابل تأیید است.")
        pending = self.s.all("SELECT DISTINCT account_id FROM deliveries WHERE campaign_id=? AND status IN ('pending','uncertain')", (campaign_id,))
        if pending:
            self.validate_accounts([row["account_id"] for row in pending])
        self.s.execute("UPDATE campaigns SET status='ready', reviewed_at=? WHERE id=?", (now(), campaign_id))

    def reassign(self, campaign_id, account_ids):
        c = self.require("campaigns", campaign_id)
        if c["status"] not in {"draft", "ready", "paused"} or self.busy():
            raise Problem("ابتدا ارسال را متوقف کنید و منتظر پایان درخواست جاری بمانید.")
        self.validate_accounts(account_ids)
        pending = self.s.all("SELECT id FROM deliveries WHERE campaign_id=? AND status='pending' ORDER BY id", (campaign_id,))
        with self.s.db() as db:
            for i, row in enumerate(pending):
                db.execute("UPDATE deliveries SET account_id=? WHERE id=?",
                           (account_ids[(i // c["batch_size"]) % len(account_ids)], row["id"]))
            db.execute("UPDATE campaigns SET accounts_json=?, status='draft', reviewed_at=NULL WHERE id=?", (json.dumps(account_ids), campaign_id))

    def start(self, campaign_id):
        c = self.require("campaigns", campaign_id)
        if self.busy():
            raise Problem("ابتدا عملیات جاری را متوقف کنید و منتظر پایان درخواست جاری بمانید.")
        if c["status"] not in {"ready", "paused"} or not c["reviewed_at"]:
            raise Problem("ابتدا پیش‌نمایش کمپین را بررسی و تأیید کنید.")
        if self.s.one("SELECT id FROM deliveries WHERE campaign_id=? AND status='uncertain'", (campaign_id,)):
            raise Problem("نتیجه ارسال نامشخص را قبل از ادامه بررسی کنید.")
        accounts = self.s.all("SELECT DISTINCT account_id FROM deliveries WHERE campaign_id=? AND status='pending'", (campaign_id,))
        if not accounts:
            self.s.execute("UPDATE campaigns SET status='completed', note='No pending recipients' WHERE id=?", (campaign_id,))
            return
        self.validate_accounts([r["account_id"] for r in accounts])
        self.s.execute("UPDATE campaigns SET status='running',note='' WHERE id=?", (campaign_id,))
        self.jobs["send:" + campaign_id] = asyncio.create_task(self._send(campaign_id))

    def stop(self, campaign_id, cancel=False):
        c = self.require("campaigns", campaign_id)
        if c["status"] in {"completed", "cancelled"}:
            raise Problem("این کمپین پایان یافته است.")
        if not cancel and c["status"] != "running":
            raise Problem("کمپین در حال ارسال نیست.")
        self.s.execute("UPDATE campaigns SET status=?,note=? WHERE id=?",
                       ("cancelled" if cancel else "paused", "درخواست جاری ممکن است کامل شود.", campaign_id))

    def resolve_uncertain(self, campaign_id, delivery_id, action):
        if self.busy():
            raise Problem("ابتدا عملیات جاری را متوقف کنید.")
        row = self.s.one("SELECT * FROM deliveries WHERE id=? AND campaign_id=? AND status='uncertain'", (delivery_id, campaign_id))
        if not row or action not in {"sent", "pending", "skipped"}:
            raise Problem("نتیجه قابل بررسی پیدا نشد.")
        self.s.execute("UPDATE deliveries SET status=?,error='Manually reviewed by operator' WHERE id=?", (action, delivery_id))

    def restrict(self, account_id, exc):
        seconds = getattr(exc, "seconds", 0)
        self.s.execute("UPDATE accounts SET status='restricted',error=?,wait_until=? WHERE id=?",
                       (type(exc).__name__, time.time() + seconds if seconds else 0, account_id))

    async def wait_until(self, campaign_id):
        while True:
            c = self.require("campaigns", campaign_id)
            if c["status"] != "running":
                return False
            remaining = c["next_attempt_at"] - time.time()
            if remaining <= 0:
                return True
            await asyncio.sleep(min(remaining, 0.25))

    async def _send(self, campaign_id):
        current_id = None
        try:
            while await self.wait_until(campaign_id):
                c = self.require("campaigns", campaign_id)
                delivery = self.s.one("SELECT * FROM deliveries WHERE campaign_id=? AND status='pending' ORDER BY id LIMIT 1", (campaign_id,))
                if not delivery:
                    self.s.execute("UPDATE campaigns SET status='completed',note='' WHERE id=?", (campaign_id,))
                    return
                current_id = delivery["id"]
                account = self.require("accounts", delivery["account_id"])
                if account["status"] != "connected":
                    raise Problem("حساب ارسال متصل نیست؛ حساب را بررسی کنید.")
                client = await self.client(account["id"])
                access = json.loads(delivery["access_json"])
                if delivery["user_id"] and account["id"] in access:
                    target = types.InputPeerUser(delivery["user_id"], int(access[account["id"]]))
                else:
                    target = delivery["username"] or delivery["user_id"]
                # Account-specific peer resolution; hashes are never shared across sessions.
                try:
                    user = await client.get_entity(target)
                    if not isinstance(user, types.User) or user.bot or user.deleted:
                        raise ValueError("Recipient unavailable")
                    if delivery["user_id"] and user.id != delivery["user_id"]:
                        raise ValueError("Username now belongs to a different user")
                    duplicate = self.s.one("SELECT id FROM deliveries WHERE campaign_id=? AND user_id=? AND status='sent' AND id!=?",
                                           (campaign_id, user.id, current_id))
                    own = self.s.one("SELECT id FROM accounts WHERE user_id=?", (user.id,))
                    if duplicate or own:
                        raise ValueError("Duplicate or connected account")
                    self.s.execute("UPDATE deliveries SET user_id=? WHERE id=?", (user.id, current_id))
                except (ValueError, TypeError) as exc:
                    self.result(current_id, "skipped", str(exc))
                    self.schedule_next(c)
                    current_id = None
                    continue
                except errors.RPCError as exc:
                    if type(exc).__name__ not in SKIP_ERRORS:
                        raise
                    self.result(current_id, "skipped", type(exc).__name__)
                    self.schedule_next(c)
                    current_id = None
                    continue
                # Re-check after resolution so Pause prevents a new send from starting.
                if self.require("campaigns", campaign_id)["status"] != "running":
                    return
                self.s.execute("UPDATE deliveries SET status='sending',attempted_at=? WHERE id=?", (now(), current_id))
                try:
                    if c["photo_id"]:
                        photo = self.require("uploads", c["photo_id"])
                        message = await client.send_file(user, self.s.root / photo["path"], caption=c["text"], parse_mode=None)
                    else:
                        message = await client.send_message(user, c["text"], parse_mode=None, link_preview=False)
                    self.s.execute("UPDATE deliveries SET status='sent',message_id=?,error=NULL WHERE id=?", (message.id, current_id))
                except Exception as exc:
                    kind = type(exc).__name__
                    if kind in STOP_ERRORS:
                        self.result(current_id, "pending", kind)
                        raise
                    if kind in SKIP_ERRORS:
                        self.result(current_id, "skipped", kind)
                    elif isinstance(exc, errors.RPCError) and not isinstance(exc, (errors.ServerError, errors.RpcCallFailError)):
                        self.result(current_id, "failed", kind)
                        raise
                    else:
                        self.result(current_id, "uncertain", kind)
                        raise
                self.schedule_next(c)
                current_id = None
                pending = self.s.one("SELECT id FROM deliveries WHERE campaign_id=? AND status='pending'", (campaign_id,))
                if not pending and self.require("campaigns", campaign_id)["status"] == "running":
                    self.s.execute("UPDATE campaigns SET status='completed' WHERE id=?", (campaign_id,))
                    return
        except asyncio.CancelledError:
            if current_id:
                self.s.execute("UPDATE deliveries SET status='uncertain',error='Shutdown during send' WHERE id=? AND status='sending'", (current_id,))
            self.s.execute("UPDATE campaigns SET status='paused',note='Application stopped' WHERE id=? AND status='running'", (campaign_id,))
            raise
        except Exception as exc:
            kind = type(exc).__name__
            if current_id and kind in SKIP_ERRORS:
                self.result(current_id, "skipped", kind)
            if current_id and kind in STOP_ERRORS:
                delivery = self.s.one("SELECT account_id FROM deliveries WHERE id=?", (current_id,))
                self.restrict(delivery["account_id"], exc)
            note = str(exc) if isinstance(exc, Problem) else kind
            seconds = getattr(exc, "seconds", 0)
            self.s.execute("UPDATE campaigns SET status='paused',note=?,next_attempt_at=MAX(next_attempt_at,?) WHERE id=? AND status='running'",
                           (note, time.time() + seconds, campaign_id))

    def result(self, delivery_id, status, error):
        self.s.execute("UPDATE deliveries SET status=?,error=?,attempted_at=? WHERE id=?", (status, error, now(), delivery_id))

    def schedule_next(self, campaign):
        self.s.execute("UPDATE campaigns SET next_attempt_at=? WHERE id=?",
                       (time.time() + random.uniform(campaign["delay_min"], campaign["delay_max"]), campaign["id"]))

    async def close(self):
        tasks = [t for t in self.jobs.values() if not t.done()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await asyncio.gather(*(c.disconnect() for c in self.clients.values()), return_exceptions=True)
