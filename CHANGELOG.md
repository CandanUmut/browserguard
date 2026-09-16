# Changelog

## 1.0.0

First release.

### Added
- Browser policy applied to Chrome, Edge, Brave, Vivaldi, Opera, Firefox,
  Waterfox and Chromium.
- Detection of unbranded Chromium forks by reading the policy path out of
  `chrome.dll`, in both ASCII and UTF-16. Ecosia is the case this was built for.
- Seven bundled blocklist categories, stored in the executable so no network
  access is needed.
- Bypass hardening: browser DoH off, incognito off, developer tools off, guest
  profiles off, optional extension lockdown.
- Chrome SafeSites adult classification, which covers sites no blocklist has.
- Waiting period on any change that reduces protection, with a passcode that
  skips the wait and no way to be locked out.
- Time-based schedules, including windows that run overnight.
- Verify view that reads live policy back from the registry.
- Command line with the same features, and `--sync` for the background task.

### Notes
- YouTube Restricted Mode ships **off**. It hides all comments and blocks most
  live streams, which is rarely what people expect.
