# Telegram Campaign Manager

<!-- impeccable:product-schema 1 -->

## Platform
web

## Stack
Delegated by the user: Python, Telethon, FastAPI, SQLite, and plain HTML/CSS/JavaScript. Local Windows launcher; no Node.js requirement.

## Users
One operator managing their own Telegram accounts on a Windows PC.

## Product Purpose
Collect group member lists first, review recipients, then manually launch campaigns with automatic account rotation.

## Operating Context
Local browser dashboard in Persian, right-to-left. Multiple personal accounts with independent sessions. The app must remain running while sending.

## Capabilities and Constraints
Member lists and campaigns have confirmed delete actions. List deletion preserves existing campaign snapshots; campaign deletion removes its local delivery history. Shared campaign photos are retained, while unreferenced uploads can be cleaned up from Accounts. Deletion and cleanup are blocked during active jobs.
Accounts can be removed from this app with confirmation. Local session files are removed, historical reports retain the account label, and unfinished campaigns using the removed sender require replacement accounts and another preview review. This does not deactivate the Telegram account or remotely revoke its authorization.
Collection also supports visible message authors from all accessible group history or a selected number of days before a fixed collection start. History collection stores author records without message contents. Historical authors may no longer be members. Default history range is all history; a limited range starts at 30 days.
Group collection and CSV username import; persistent reviewed recipient snapshots; text or one photo with a caption; batches of 10 attempts per account; one global queue with a random 30–60 second delay. Pause the entire campaign on Telegram restrictions. Manual start, pause, resume, cancel. Restart restores unfinished work as paused. Telegram may expose only part of a group's membership.

## Product Principles
- Collection never sends messages.
- Show actual state and collection limitations.
- Preserve confirmed deliveries and flag uncertain outcomes for review.
- Keep credentials, sessions, and private data on this PC.

## Accessibility & Inclusion
Persian RTL interface, mixed-direction usernames, keyboard-accessible forms, readable status labels.
