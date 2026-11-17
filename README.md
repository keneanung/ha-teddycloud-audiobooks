# TeddyCloud Audiobooks

Prepare the next audiobook segment from Home Assistant while a classic Toniebox
continues playing its current file. Progress belongs to the NFC tag, so the same
book can move between configured boxes. Two selectors provide optional manual
correction for any number of books.

This custom integration is configured through **Settings → Devices & services**.
It uses HA's existing MQTT
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

1. Prepare bounded, existing TAF files in TeddyCloud's library, leaving M4B
   originals unchanged. Give files sortable names such as `segment-01.taf`.
   Each segment needs a distinct embedded audio ID.
2. Place the book's tag once to create its metadata in TeddyCloud. Both boxes
   must share the tag's content namespace. For manual selection backwards,
   verify `cloud.updateOnLowerAudioId=true` in TeddyCloud's effective settings.
3. In **Settings → Devices & services → Add integration**, select **TeddyCloud
   Audiobooks**. Enter the server URL, MQTT prefix, one box certificate common
   name per line, and the playback threshold (default 600 seconds). HTTP
   credentials are optional; MQTT uses HA's existing broker configuration.
4. Enter the audiobook name and tag UID, then choose its folder relative to
   TeddyCloud's library, for example `AudiobookSegments/MyBook`. Select the TAF
   files. The integration reads actual header IDs from TeddyCloud; you do not
   enter them manually. The initial order follows filenames.
5. Use **Configure** on the integration to edit connection settings, add/remove
   books, replace a book's segment list from a library folder, rename segments,
   or change their positions. Changes are staged until Save. Removing files
   requires confirmation before an affected book can reset to segment 1.
6. Add the [dashboard card](examples/dashboard.yaml). Existing entity IDs are
   preserved across the YAML-to-UI migration. Normal IDs are `select.audiobook`
   and `select.audiobook_segment`; use registered IDs if HA resolves a collision.
7. Remove and replace the tag to establish a fresh session, and perform the
   normal manual freshness check to load a changed assignment.

The URL must be HTTP(S), without a query or fragment. Use a trusted LAN or HTTPS
with a certificate trusted by HA; certificate verification is never disabled.
Passwords are stored by Home Assistant in its private integration configuration,
not in this repository. A blank password while editing preserves the saved one;
clear the username to remove HTTP credentials.

**Upgrading from 0.1 YAML:** existing YAML imports once into a single UI config
entry while retaining saved progress and entity IDs. Verify the entry is loaded,
then remove only the `teddycloud_audiobooks:` section from YAML. Keep unrelated
package/dashboard settings. After import, Configure is authoritative; YAML does
not overwrite an existing UI entry. [The YAML example](examples/configuration.example.yaml)
is retained only for one-time import/migration. Settings changes reload the
integration automatically and discard incomplete playback timers; no HA restart
is required after UI edits.

Default threshold is 600 seconds. Use 30 during a supervised pilot with files
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
Back it up before edits. UI reordering preserves progress by matching the assigned
segment's source and audio ID, rather than blindly retaining its old numerical
position. If that segment is removed or replaced, Save requires permission to
reset the affected book to segment 1. Surviving segments keep their progress.
Adding books requires no additional helpers or automations. Configuration lives
in the native HA config entry; include it and the progress Store in backups.
Avoid editing `.storage` manually.

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
