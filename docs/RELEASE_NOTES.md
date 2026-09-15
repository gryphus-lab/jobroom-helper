# Release Notes

## Unreleased

- Breaking change: replaced the Notion backend with a local SQLite database.
  Records are now stored in `data/applications.db` (or `JOBROOM_DB_PATH`) via
  the new `ApplicationStore` class, a drop-in replacement for the old Notion
  helper. The `notion-client` dependency and all Notion configuration
  (`NOTION_API_KEY`, `DATABASE_ID`, property maps) have been removed.
- Added a `list` command that prints all tracked applications.
- Renamed the package from `selenium_notion_autofill` to `jobroom_helper`.
