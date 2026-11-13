# Watchtower Community

A local macOS app that monitors research websites in the background and sends
macOS notifications when updates arrive.

## What it monitors

- Google Scholar citations, h-index and i10-index.
- XJTU student mail unread counts and recent message headers.
- XJTU OA public announcements.
- OpenReview account notifications.
- ScholarOne manuscript status for IEEE TIFS, TDSC, ToN, TMC and JSAC.

## Get started

1. Use an Apple Silicon Mac running macOS 12 or later.
2. Install **Watchtower Community.app** from an upstream release when available,
   or build it from source using Python 3.9+ and Xcode Command Line Tools.
3. Open the app and connect the modules you need with your own accounts or
   Google Scholar profile link. All nine modules start disabled.
4. Set your monitoring and notification schedules, then keep the app running.
   Closing its window leaves it active in the menu bar. Quitting stops checks.

Source-build instructions are available in the build guide. [Build guide](docs/BUILD.md)

## Local storage

Credentials use macOS Keychain. Settings and monitoring snapshots stay on your
Mac, and the backend listens on the loopback interface. Website integrations
depend on each service's login, verification and availability requirements.

Read the full documentation for setup details and compatibility limits.
[Full README](README.md) · [Privacy](docs/PRIVACY.md)

Licensed under MIT. [License](LICENSE)
