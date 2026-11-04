# Task 14 report
Built the item page (ItemHeader, ItemActions, ItemMenu, FullEmailSheet, EpisodesSheet, timestampLink + tests), Maestro flows finish_item, newsletter_1/2 and run_newsletter.sh.
Checks: typecheck clean; jest 19 suites / 156 tests pass.
Notes:
- Maestro flows rely on testIDs `filter-done`, `filter-inbox`, `tab-library` from Task 12 (not present in this worktree).
- ItemMenu delays opening a follow-up sheet 400ms so iOS does not drop a modal presented during the menu's dismissal; verify on device.
- Spec says topic chip -> /topic/[id] (Task 13 route).
- "Your note" section is hidden when there is neither reaction nor note.
