# GitHub Actions Pins

A minimal repository for tracking pinned GitHub Actions metadata.

- `pins/actions.txt` is the source list of actions to track.
- `_data/pins.json` is the generated metadata file.
- GitHub Pages publishes only `/pins.json`.

## Automation

- `PR / Pins Source` validates `pins/actions.txt`.
- `PR / Pins Data` validates changes to `_data/pins.json`.
- `Cron / Hourly Refresh Pins` refreshes one shard of `_data/pins.json` and opens a pull request.
- `Pages` copies `_data/pins.json` into `dist/pins.json` and deploys it to GitHub Pages.

## License

© 2026 [Daniel Morris]\
Made available under the terms of the [MIT License].

[daniel morris]: https://unfun.co
[mit license]: LICENSE.md
