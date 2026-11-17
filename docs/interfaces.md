# Verified TeddyCloud interfaces

The implementation was inspected against upstream release `tc_v0.7.1`, commit
`907acea50ad00ae22b4ef2c690f5b8e564f8a474`, matching the installed binary.
Use these pinned sources when checking behavior after an upgrade:

- [MQTT implementation](https://github.com/toniebox-reverse-engineering/teddycloud/blob/tc_v0.7.1/src/mqtt.c)
- [Tag and playback state](https://github.com/toniebox-reverse-engineering/teddycloud/blob/tc_v0.7.1/src/toniebox_state.c)
- [RTNL decoding](https://github.com/toniebox-reverse-engineering/teddycloud/blob/tc_v0.7.1/src/handler_rtnl.c)
- [HTTP routes](https://github.com/toniebox-reverse-engineering/teddycloud/blob/tc_v0.7.1/src/server.c)
- [Content metadata handlers](https://github.com/toniebox-reverse-engineering/teddycloud/blob/tc_v0.7.1/src/handler_api.c)
- [Content resolution](https://github.com/toniebox-reverse-engineering/teddycloud/blob/tc_v0.7.1/src/handler.c)
- [Freshness handling](https://github.com/toniebox-reverse-engineering/teddycloud/blob/tc_v0.7.1/src/handler_cloud.c)
- [Source path handling](https://github.com/toniebox-reverse-engineering/teddycloud/blob/tc_v0.7.1/src/server_helpers.c)

## MQTT

`mqtt.topic` defaults to `teddyCloud`. `BOX_CN` is the box certificate common
name, not its human-readable name. Topics are case sensitive:

| Topic | Payload |
| --- | --- |
| `teddyCloud/box/BOX_CN/TagValid` | uppercase 16-digit UID on placement; `-UID` on removal; empty on playback stop |
| `teddyCloud/box/BOX_CN/Playback` | `ON` or `OFF` |
| `teddyCloud/box/BOX_CN/ContentAudioId` | decimal embedded audio ID; empty on stop |
| `teddyCloud/box/BOX_CN/LastSeen` | UTC timestamp from RTNL activity, not proof of continuing playback |
| `teddyCloud/status` | `online` / `offline` for the TeddyCloud broker connection |

`mqtt.c` builds the base as `%s/box/%s`; `ha_transmit_topic` appends the entity
name. Event publishes use retain=false. HA subscribes at QoS 0 and also rejects
retained messages defensively. Generic `/event/` topics are not the per-box
playback topic. Payloads here are plain strings, not JSON objects.

`handler_rtnl.c` maps valid placement/removal functions to `tbs_tag_placed` and
`tbs_tag_removed`, and formats the little-endian audio ID as an unsigned decimal.
`tbs_playback` reports ON at STARTED and also at STARTING (fallthrough), and OFF
at STOPPED. OFF at STARTING is immediately followed by ON. This limits the claim
to **reported playback time**, not measured audible playback time.

The pilot observed all three topics and the negative UID removal format on a
classic box, including OFF→ON startup and matching audio IDs. No synthetic MQTT
messages were published to the household broker during tests.

## Content assignment API

The routes in `server.c` are:

- `GET /content/json/get/RUID`: current content metadata JSON.
- `POST /content/json/set/RUID`: partial `application/x-www-form-urlencoded`
  update. Managed fields are `source=lib://.../segment.taf`, `live=false`, and
  `nocloud=true`. Boolean values are lowercase strings. A JSON POST body is
  not the supported format for this handler.

`RUID` is the UID with its eight bytes reversed. For example,
`E004035000000001` becomes `01000000500304e0`. See
`getContentPathFromUID` and `getContentPathFromCharRUID` in `handler.c`.
No per-box overlay query is sent: both boxes must share the default content
namespace. The handler preserves fields absent from the submitted form. It saves
only if a field differs. The integration additionally GETs before POST and GETs
after POST, and never rewrites an unchanged assignment.

A local TAF `source` is resolved directly (`CT_SOURCE_TAF`) when valid, including
`lib://` path resolution. A non-TAF or nonexistent source is not equivalent and
may enter a different conversion path; validate files before enabling a book.

For discovery/preparation, the verified route
`GET /api/fileIndex?special=library&path=/directory` returns a `files` list. A TAF's
`desc` begins `TAF:<hex audio ID>:<hash>:...`. The ID in configuration must be
that header ID converted to decimal. This endpoint was used to validate both
pilot TAFs. It is not polled during listening.

## Audio IDs, freshness and ongoing playback

`process_freshness_check` compares the cached box audio ID with the selected
TAF's header audio ID. Higher effective IDs mark an update; lower IDs also mark
an update if `cloud.updateOnLowerAudioId=true`. Custom IDs use the
`TEDDY_BENCH_AUDIO_ID_DEDUCT` conversion. The integration neither edits the
header nor invents IDs. Use distinct IDs for different files. The same ID with
different audio bytes may not refresh.

The `live` flag can force refreshes but also changes restart/download behavior;
this integration deliberately uses `live=false`. Backwards manual correction
therefore needs `cloud.updateOnLowerAudioId=true`, verified on the pilot server.
Other installations must verify their effective per-box settings.

For a valid local TAF, the content handler resolves the source file for the
request before sending it. Changing metadata does not issue a playback command
or replace that file. The pilot verified that playback continued when the next
source changed, and the user confirmed chapter 2 loaded after manual freshness.
Other firmware/cache combinations still require local verification.
