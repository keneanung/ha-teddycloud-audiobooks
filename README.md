# TeddyCloud Audiobooks

Prepare the next audiobook segment from Home Assistant while a classic Toniebox
continues playing its current file. Progress belongs to the NFC tag, so the same
book can move between configured boxes. Two selectors provide optional manual
correction for any number of books.

This is a YAML-configured custom integration. It uses HA's existing MQTT
integration, HA storage, and TeddyCloud's HTTP API. No extra running service,
transcoding server, per-book helpers, scripts, or automations are needed.

## Installation

Requires Home Assistant 2026.11 or later, configured MQTT, and TeddyCloud 0.7.1.
The implementation has been checked against HA 2026.11.1 and TeddyCloud 0.7.1;
other versions and Toniebox 2 are not verified.

<!-- ha-marketplace:exclude-start -->
The directory containing this README is a complete standalone repository tree.
Published at [keneanung/ha-teddycloud-audiobooks](https://github.com/keneanung/ha-teddycloud-audiobooks).
Marketplace catalog inclusion is a separate step (see [publishing](docs/publishing.md)).
Add its public GitHub URL as an **Integration** custom repository
in Marketplace (HACS on older HA installations), download, and restart HA.
For manual installation, copy `custom_components/teddycloud_audiobooks` into
HA's `/config/custom_components/` and restart after configuration.
<!-- ha-marketplace:exclude-end -->

1. Prepare bounded, existing TAF files in TeddyCloud's library. Keep M4B originals.
   Use unique embedded audio IDs per segment; preferably increasing IDs. Read the
   real IDs from TeddyCloud's library index rather than guessing from filenames.
2. Place the audiobook tag once to create its content metadata in TeddyCloud.
   The integration deliberately requires that metadata to exist before writing.
3. Copy [the example](examples/configuration.example.yaml) into HA configuration
   or an existing packages directory. Replace the example URL, box certificate
   common names, 16-digit uppercase tag UIDs (no colons), sources, and audio IDs.
   `lib://` paths are relative to TeddyCloud's library. Configure only prepared
   TAFs; an invalid source can cause TeddyCloud to attempt runtime transcoding.
4. Use `!secret` for HTTP credentials when needed. Keep the API on a trusted LAN,
   or use HTTPS with a certificate trusted by HA. The integration never disables
   TLS verification. It does not change MQTT broker credentials or configuration.
5. Ensure both boxes resolve the tag through the same TeddyCloud content namespace.
   Per-box isolated content directories are outside this version's scope. To
   support manual selection backwards with `live=false`, verify TeddyCloud's
   `cloud.updateOnLowerAudioId=true` for the relevant boxes. This integration
   does not modify global or per-box settings.
6. Check HA configuration, restart, and add the [dashboard card](examples/dashboard.yaml).
   Entity IDs normally are `select.audiobook` and `select.audiobook_segment`;
   use their registered IDs if HA resolves a naming collision differently.
7. Remove the tag, then place it again to establish a fresh session.

Default threshold is 600 seconds. Use 30 during a supervised test with files
longer than 30 seconds, then restore 600 for ordinary listening.

## Behavior and persistence

The segment selector shows the **saved assignment for the next session**. After
the threshold it changes while the box continues its current segment. Selecting
a book changes which progress is displayed. Selecting a segment updates that
tag's authoritative progress and reconciles its server assignment immediately.

A session needs a fresh tag placement, playback ON, and a matching embedded audio
ID. Events may arrive in either order after placement. Retained MQTT messages are
ignored. Duplicate events do not restart the clock or increment twice. One tag
advances at most once per continuous session, including simultaneous observations
from two boxes. The final segment is never exceeded. Playing an older cached
segment does not advance the saved index again.

Stopping or removing a tag before the threshold discards that session's elapsed
time. No time is credited while HA is down or MQTT disconnected. After HA or
MQTT/TeddyCloud reconnects, remove/re-place the tag (or observe another fresh
empty/removal boundary) before progress can resume. This conservative policy
prevents reconnect state snapshots from being treated as listening.

HA persists the index before updating TeddyCloud. Failed API calls leave a
visible `assignment_pending` attribute and retry once per minute. Each retry reads
the current metadata and writes only differing managed fields; successful writes
are read back. Manual corrections invalidate older session timers. Startup
reconciles saved state with TeddyCloud, including a write interrupted by a crash.
Other metadata fields are preserved by TeddyCloud's partial form API.

Indices and the segment source/ID catalog live in HA's
`.storage/teddycloud_audiobooks`, included in normal HA configuration backups.
Back it up before edits. Do not reorder or replace an existing book's segment
catalog in place: startup rejects a changed catalog to avoid silently moving
progress to a different chapter. To migrate, stop HA, back up the storage file,
and explicitly migrate its matching catalog and zero-based index, or remove that
tag's saved catalog/index to intentionally reset it. Add new books with new tag
UIDs; no new helpers or automations are needed. Restart after YAML changes.

## Limits

RTNL playback is a firmware report, not measured audible audio. In TeddyCloud
0.7.1, `PLAYBACK_STARTING` falls through to ON, so startup/buffering can be counted.
A lost stop/removal event while MQTT stays connected can also overcount. There is
no verified periodic playhead or reliable per-box playback heartbeat in this
implementation; it cannot prove ten minutes of audible playback or detect a box
silently going offline. It uses reported playback plus a matching audio ID rather
than tag dwell alone. Verify the actual firmware's events in the pilot before
relying on it. Short segments that end before the threshold will not advance.

Source reassignment changes metadata only; it does not send stop/play commands,
replace an in-use TAF, or modify TAF audio IDs. Source inspection shows an ongoing
request keeps its resolved file. Actual non-interruption, cache replacement and
manual freshness behavior still require a hardware check. The normal/manual
freshness check must occur before the box loads the newly assigned content.
The system cannot make a child perform that check automatically.

See [verified interfaces](docs/interfaces.md), [integration test procedure](docs/testing.md),
and [publishing](docs/publishing.md). No audiobook media belongs in this repository.

## Development

```sh
python -m unittest discover -s tests -v
```

Session tests run with standard Python. Manager and API tests require the HA
runtime and are skipped when it is unavailable. CI runs them with HA 2026.11.1.
The validation workflow also runs HACS validation and hassfest when this tree is
published as its own repository. MIT licensed.
