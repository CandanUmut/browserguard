# BrowserGuard

**Parental controls that work in every browser on the machine — free, offline, and no account.**

BrowserGuard applies *enterprise browser policy*: the same mechanism IT departments
use to manage thousands of corporate machines. Filtering is enforced by the browser
itself, so it survives incognito mode, VPNs, and encrypted DNS — and the setting
appears greyed out with "managed by your organization" rather than as a toggle a
child can flip.

[![Release](https://img.shields.io/github/v/release/CandanUmut/browserguard)](https://github.com/CandanUmut/browserguard/releases/latest)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

---

## Why this instead of the usual options

Most free filtering advice ends at "change your DNS". DNS filtering is genuinely
useful, but on its own it has holes:

| | DNS filtering | Browser extension | **BrowserGuard** |
|---|---|---|---|
| Survives incognito | yes | usually not | **yes** |
| Survives the browser's own encrypted DNS (DoH) | **no** | no | **yes** |
| Can be turned off in browser settings | n/a | yes | **no** |
| Needs a subscription | often | often | **no** |
| Works offline | no | no | **yes** |
| Per-browser setup | n/a | every browser | **all at once** |

The browser's built-in DNS-over-HTTPS is the one that catches people out: turn it
on and the browser resolves names itself over HTTPS, straight past any DNS filter
on the machine or the router. BrowserGuard turns that off by policy, so your DNS
filtering keeps working.

**Use both.** BrowserGuard covers browsers; DNS filtering covers everything else on
the network. Neither replaces the other.

---

## Install

Download `BrowserGuard.exe` from the
[latest release](https://github.com/CandanUmut/browserguard/releases/latest) and run it.

There is no installer and nothing runs in the background unless you ask for it.
Windows will prompt for administrator rights, because browser policy lives in
`HKEY_LOCAL_MACHINE` and that is what makes it apply to every user account and
resist being switched off.

> **SmartScreen warning:** the executable is not code-signed — a certificate costs
> a few hundred dollars a year, which would make this not free. Click
> *More info* then *Run anyway*, or build it yourself with the instructions below.

---

## How the waiting period works

This is the part most tools get wrong, so it is worth being precise:

- **The app always opens.** No passcode to launch it or look at anything.
- **Making protection stronger applies immediately.** No wait, no passcode.
- **Making protection weaker waits**, then applies on its own.
- **The passcode only skips that wait.** Nothing else.
- **Lost the passcode? Just wait.** The change still lands.

That last point is deliberate. A parental control that can lock you out of your own
computer is malware wearing a friendly hat. Here, the worst case for losing the
passcode is that you wait a day. Generate a passcode, save the text file somewhere
other than the machine it protects, or hand it to someone you trust.

Set the waiting period to `0` to make every change immediate.

---

## What it can do

**Block by category.** Adult, proxies/VPNs, gambling, dating, social, gaming and
streaming lists ship inside the app and need no internet connection.

**Block by category, properly.** A blocklist only covers sites somebody listed.
BrowserGuard also enables Chrome's `SafeSitesFilterBehavior`, which classifies
pages as they load, so it catches adult sites that are on nobody's list.

**Close the bypass routes**, which is where most home setups leak:

| Bypass | Policy used |
|---|---|
| Browser's encrypted DNS (DoH) | `DnsOverHttpsMode = off` |
| Incognito / private windows | `IncognitoModeAvailability = 1` |
| F12 developer tools editing the page | `DeveloperToolsAvailability = 2` |
| Guest profiles starting with no policy | `BrowserGuestModeEnabled = 0` |
| Extensions that undo filtering | `ExtensionInstallBlocklist = *` |

**Schedules.** Block social media 09:00–15:00 on weekdays, or gaming after 22:00.
Overnight windows are handled. A schedule can only *add* restrictions, never remove
one, so it can't be used to sidestep the waiting period.

**Verify.** A tab that reads back what is actually in the registry, browser by
browser. Cross-check it against `chrome://policy` in the browser itself.

---

## Browsers it covers

Chrome, Edge, Brave, Vivaldi, Opera, Firefox, Waterfox, Chromium and **unbranded
Chromium forks** such as Ecosia.

That last group is the interesting one. Most parental-control tools hardcode
Chrome, Edge and Firefox. Any other Chromium fork then silently ignores every
policy written — it looks protected, and isn't.

Chromium stores its policy registry path as a literal string inside `chrome.dll`.
BrowserGuard reads it directly, in both ASCII and UTF-16, rather than guessing a
vendor name:

```
Ecosia Browser  ->  SOFTWARE\Policies\Chromium     (read from chrome.dll)
Brave           ->  SOFTWARE\Policies\BraveSoftware\Brave
Vivaldi         ->  SOFTWARE\Policies\Vivaldi
```

Ecosia is the case that prompted the feature: it ships as plain Chromium, so
writing `SOFTWARE\Policies\Google\Chrome` for it does precisely nothing.

Policy is also written for supported browsers that are *not* installed, so a
browser installed later is already covered rather than arriving as a fresh hole.

---

## A note on YouTube Restricted Mode

It is **off by default**, on purpose. Restricted Mode hides every comment on every
video and blocks most live streams. That surprises people who only wanted adult
sites blocked, and it is hard to diagnose because the browser reports nothing wrong.
Turn it on if you want it, but now you know what it does.

---

## Command line

The release also ships `browserguard-cli.exe` with the same features:

```powershell
browserguard-cli status                     # what is in force
browserguard-cli detect                     # browsers found, and their policy keys
browserguard-cli level strict               # set a protection level
browserguard-cli block example.com          # block specific sites
browserguard-cli allow school.example.edu   # add an exception
browserguard-cli passcode --out C:\code.txt # generate a passcode
browserguard-cli verify                     # read policy back from the registry
browserguard-cli background install         # schedules + unattended pending changes
browserguard-cli uninstall                  # remove everything it wrote
```

`--sync` is what the background task runs: it applies any change whose wait has
elapsed and refreshes schedule-driven policy.

---

## Removing it

From the app: **Security → Remove all protection**. From the command line:
`browserguard-cli uninstall`. Either removes every value BrowserGuard wrote and
deletes the background task. Policy set by anything else is left alone — it only
ever touches its own known list of value names.

If the app will not start, the manual equivalent is deleting the BrowserGuard
values under `HKLM\SOFTWARE\Policies\...` with `regedit` as administrator. There is
no hidden service, no driver, and nothing that reinstalls itself.

---

## Build it yourself

```powershell
git clone https://github.com/CandanUmut/browserguard
cd browserguard
python -m venv .venv
.\.venv\Scripts\pip install -e ".[dev]"
.\.venv\Scripts\python -m pytest          # 40 tests, no admin needed
.\.venv\Scripts\pyinstaller browserguard.spec --noconfirm
```

The executables land in `dist/`. The test suite swaps the registry for an
in-memory stand-in, so it runs on any platform and never touches a real machine.

---

## Limitations, stated plainly

- **Windows only.** Policy lives in the Windows registry.
- **A determined administrator can undo it.** Anyone with admin rights can edit the
  registry directly. The waiting period is designed to stop impulsive changes, not
  a motivated adult.
- **Blocklists are finite.** They cover listed sites. SafeSites and DNS filtering
  cover the rest — use the layers together.
- **Not code-signed**, so SmartScreen will warn on first run.
- **Restart browsers** after applying. Policy is read at startup.

---

## License

MIT — see [LICENSE](LICENSE). Free to use, change and redistribute.
