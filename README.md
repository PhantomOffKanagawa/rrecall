# rrecall

## To-Dos
- [ ] Cover empty file case for `/scripts/install-hooks.*`
- [ ] Show success in response on hook
- [ ] Add options to create and link Project or JIRA Card pages for better Graph View Linking
- [ ] Add option for tool use responses

## Installation Scripts

Hook installer scripts are provided in `scripts/`:

- `install-hooks.sh` — Bash (Linux/macOS)
- `install-hooks.ps1` — PowerShell (Windows/Linux/macOS)

> **Note:** The PowerShell script is tested in CI using PowerShell Core (pwsh 7) on Ubuntu only. It is designed to be compatible with Windows PowerShell 5.1, but this is not verified in automated testing. If you encounter issues on Windows PowerShell 5.1, please open an issue.
