# Maestro flows

UI flows that drive the debug app on the iOS simulator against the local backend.

| Flow | What it proves |
| --- | --- |
| `add_link.yaml` | Dev login, add a link, the worker's title appears in Library |
| `sign_out.yaml` | Dev login, Today tab, account button, Sign out, back on the Apple sign-in screen |
| `offline_*.yaml` + `run_offline.sh` | Add a link with the backend down ("1 change waiting"), restart it, the change syncs and the title arrives |

## One-time setup

- Java 17+: `brew install openjdk@17`
- Maestro: `curl -fsSL "https://get.maestro.mobile.dev" | bash`
- The Makefile and `run_offline.sh` put both on `PATH` themselves (`/opt/homebrew/opt/openjdk@17/bin` and `~/.maestro/bin`). To run `maestro` by hand, export that `PATH` in your shell; nothing edits your shell rc files.

## Running

1. Boot an iOS simulator (e.g. iPhone 17 Pro) and install the debug build: `cd app && npx expo run:ios`. Leave Metro running.
2. `make maestro` with the backend up in another terminal (`make start-local`). Runs `add_link` and `sign_out`.
3. `make maestro-offline` with the backend **stopped**: the script starts and stops `make start-local` itself.

Both targets first empty the local dev database's synced data (`make reset-local-data`), and each flow starts with a clean app install (state and keychain cleared).

## Notes

- `archie://dev/login` needs `ARCHIE_ENV=dev`, which `make start-local` sets. iOS asks "Open in Archie?" for the link; the flows tap Open.
- Flows need a network connection: the worker fetches `paulgraham.com` and `example.com` for real.
- The offline flow adds `https://example.com/` (not a made-up path): example.com now returns 404 for other paths, so the worker could not read a title.
