# دفتر ارسال — Windows Telegram Campaign Manager

A local Persian, right-to-left dashboard for personal Telegram accounts. Member collection and message sending are separate operations.

## Run on Windows

Double-click **Start.cmd**. Keep its terminal window open while the app is running. The launcher opens the dashboard in your default browser. Closing the terminal stops collection and sending; unfinished campaigns reopen paused.

If the app is already running, double-clicking **Start.cmd** reopens the existing dashboard instead of starting another server. The launcher keeps its messages visible until you press a key. If the browser does not open, copy the address shown after `Dashboard:` into your browser. Startup errors also remain visible. The current dashboard address is recorded in `data/server.json` while the app is running.

The launcher requires [uv](https://docs.astral.sh/uv/getting-started/installation/) and internet access for the first dependency installation. uv is already available on this PC. Python dependencies are installed in `.venv` within this folder. Dependency versions are locked in `uv.lock` and `requirements.txt`.

1. Open **حساب‌ها** (Accounts). Enter your API ID and API Hash from [my.telegram.org](https://my.telegram.org), under API development tools.
2. Add each account with its international phone number, Telegram login code, and two-step verification password if required. Enter credentials directly in the local app.
3. Open **فهرست اعضا** (Member lists). Choose **جمع‌آوری از گروه**, pick an account, load its joined groups, and select groups. You can add groups from several accounts to one collection.
4. Start collection and wait for it to finish. Review the saved members and uncheck recipients to exclude. Collection never sends messages. Incomplete results are marked explicitly.
5. Choose **ساخت کمپین از این فهرست**. Enter text or attach a PNG/JPEG photo with a caption. Select and reorder sender accounts, batch size, and minimum/maximum delay.
6. Save the campaign, review its frozen recipient list and message, and confirm the preview. Click **شروع ارسال** separately to begin.

Default rotation is 10 recipient attempts per account, cycling through the selected accounts. A new random delay between 30 and 60 seconds separates attempts across the entire queue, including account switches. These values can be changed when creating a campaign. One campaign runs at a time.

## Collect authors from chat history

In **جمع‌آوری از گروه**, choose **نویسندگان پیام‌های گفتگو** as the collection method. Choose **همه تاریخچه قابل دسترس** to scan all available history, or **تعداد روزهای گذشته** and enter how many days back to scan (1–36,500; starts at 30). The collection window is fixed at the start and shared across all selected groups. The list shows its method, period, messages examined, and unique authors collected.

This records identifiable message authors, not current membership. Historical authors may have left. Bots, deleted users, connected sender accounts, service messages, and anonymous/channel identities are excluded. Forwarded messages contribute their visible sender, not the original forwarded author. Deleted messages and history Telegram does not expose cannot be scanned. Message text is not saved. Stop retains the partial author list for review; collection does not start sending.

## Delete member lists, campaigns, and unused photos

Use **حذف** in the list or campaign table, or **حذف فهرست / حذف کمپین** in its detail view. Deleting a list removes its saved members while existing campaigns keep their own recipient snapshots. Deleting a campaign permanently removes its local recipients and delivery report; it does not remove messages already sent in Telegram. An attached photo is removed only if no other campaign uses it.

Under **حساب‌ها**, **پاکسازی عکس‌های بدون استفاده** removes uploaded photos that no campaign uses, including uploads left behind when composing a campaign was cancelled. Delete and cleanup actions require confirmation and are blocked while collection or sending is active.

## CSV alternative

Import a UTF-8 CSV with a `username` header. Duplicates are removed case-insensitively; invalid rows are counted. Usernames can include `@` or `https://t.me/`.

```csv
username
example_user_one
@example_user_two
```

## Remove an account

Open **حساب‌ها** and click **حذف** beside the account, then confirm. This removes the account from this app and deletes its local session files. It does not deactivate the Telegram account or revoke authorization remotely. Campaign reports retain its name; unfinished campaigns assigned to it return to draft. Open those campaigns, choose replacement accounts under **تغییر حساب‌های گیرنده‌های باقی‌مانده**, and review them again. Deletion is disabled while collection or sending is active. If cleanup fails, the account remains unavailable and shows **تلاش مجدد برای حذف** so removal can be retried.

## Scheduling, activity, and account bios

- The optional start time uses this PC's local time. Save the campaign, review it, and click Start to arm it. Keep the application running. Past times start immediately; restarting the app leaves unfinished campaigns paused for manual resume.
- Random attempt delays retain the default 30–60 second range. Scheduled starts and Telegram wait deadlines are enforced independently of this interval.
- The optional activity filter uses observed group-message dates, not Telegram last-seen status. Collect with the history method first. With the filter enabled, unknown activity (including old lists and CSV-only recipients) is excluded. Campaign review shows qualifying, inactive, and unknown counts. Recipient activity is frozen with the campaign snapshot.
- Optional bio texts are entered one per line: up to 20 texts, each at most 70 characters. A selection is saved for each sending account and shown before review. It is applied before that account's first send in the campaign and remains afterward. Interrupted updates are checked against the current profile before another update is attempted. Bio changes are not proven to reduce bans.
- Reports include the observed activity timestamp and destination wait deadline as Unix timestamps. Profile-update status appears in campaign details.

## Pause, errors, and recovery

- Pause and Cancel prevent further attempts after any current Telegram request finishes. Cancel does not delete messages already delivered.
- Telegram rate limits, restrictions, bans, and expired authorization pause the entire campaign. The app does not switch accounts in response to those errors. Finite wait times remain enforced across restarts.
- Login and reconnect cannot clear an active account cooldown. Slow-mode errors retain a destination deadline without marking the entire account restricted. Posting-permission errors pause the campaign rather than continuing through the list.
- After the reported waiting period, inspect the account under Accounts. **بررسی اتصال** checks authorization; Telegram does not provide a guarantee that this means a sending restriction has cleared. A new sending restriction will pause the campaign again.
- To remove an affected sender, use **تغییر حساب‌های گیرنده‌های باقی‌مانده** on a paused campaign. This reassigns only pending recipients and requires reviewing the campaign again.
- A timeout or interrupted request can have an uncertain result. Inspect that account's Telegram chat, then mark the delivery sent, skipped, or pending. Uncertain deliveries block resume until reviewed.
- Privacy restrictions and unavailable recipients are recorded as skipped. Unexpected definite Telegram errors are recorded as failed and pause the campaign.
- Delivery reports can be downloaded as UTF-8 CSV from each campaign.

## Telegram limitations

Only members Telegram exposes to the collecting account can be listed. Hidden membership and permission restrictions can result in partial lists. Private groups must already be joined; the app does not auto-join groups.

Telegram user access hashes belong to individual account sessions. The app preserves that distinction. A sending account must be able to resolve a recipient through its own collected access information, public username, or session cache; otherwise the recipient is skipped. A member visible to one account is not necessarily reachable by another.

The application cannot guarantee message delivery or prevent account restrictions. No live Telegram login or delivery has been tested without your credentials; perform a separate small test campaign with a recipient you control first.

## Local data

The app binds to `127.0.0.1` on an available port, rejects foreign-origin requests, and protects API actions with a per-run local session token. It is intended for a single trusted operator on this PC.

`data/` contains the SQLite database, API credentials, account session files, uploaded photos, saved member lists, and delivery history. These files are **not encrypted at rest**. Keep this folder private and back it up only to trusted storage. Codes and two-step verification passwords are not stored. Do not share account session files; they authorize access to the accounts. Removing a local session file is not the same as revoking it through Telegram's Devices settings.

## Development and verification

```powershell
uv pip install --python .venv\Scripts\python.exe -r pyproject.toml --group dev
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
node --check static\app.js
```

Node.js is optional and used only for the JavaScript syntax check. Tests use simulated Telegram clients and isolated databases under `.cache/tests`; they do not send Telegram messages.

For an isolated dashboard with clearly labeled sample data and sending disabled:

```powershell
.\.venv\Scripts\python.exe -m tests.preview
```

Then open `http://127.0.0.1:8766`. Production account data is not used by this preview.
