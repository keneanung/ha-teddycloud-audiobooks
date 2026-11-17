# Integration test procedure

Use one box, a dedicated tag and two short, distinct TAFs, each longer than the
test threshold. Leave other boxes out of `boxes`. Back up the tag's original
metadata, HA package and progress storage before testing. Set threshold to 30.

1. Verify both files through TeddyCloud's file index and record their actual
   audio IDs. Ensure the tag has existing metadata and a shared namespace.
2. Select segment 1 in HA. Confirm `assignment_pending=false` and GET metadata
   returns segment 1's source. A UI selection is authoritative immediately.
3. Passively observe that box's TagValid, Playback and ContentAudioId topics
   using an MQTT client with existing credentials. Do not expose credentials
   or inject simulated box events into the live household broker.
4. Remove and replace the tag. Verify UID, ON and segment 1 ID. At 20 seconds,
   confirm HA still shows segment 1. Remove the tag before 30 seconds and
   verify it stays at 1. Repeat placement to start a new session.
5. Leave playback running past 30 seconds. HA should change once to segment 2,
   persist index 1 (zero-based), and POST the new source. Read it back through
   GET. Ask the listener to confirm ongoing playback was not interrupted.
6. Leave the tag in place for another threshold; there must be no extra
   advancement. At the final segment, the index remains final.
7. Remove the tag, perform the normal manual freshness check, and place it.
   Verify the segment 2 ContentAudioId and confirm audibly with the listener.
8. Manually select segment 1 while segment 2 is playing. Verify the new source
   is assigned and remains authoritative after the old threshold passes.
   The current box continues its already loaded audio.
9. Restart HA. Confirm selected book, saved index and assignment survive.
   A tag left in place must not resume a timer from restored/stale events.
   Remove/re-place it before the next intended listening test.
10. Exercise disconnect/reconnect with an isolated test broker or unit tests;
    do not restart the household broker just to test this integration.
    Retained snapshots and repeated ON/placement must not increment progress.
11. Test API timeout, a successful retry, mismatched read-back, and persistence
    failure with the automated manager tests. Never redirect production HA
    to a fake API while children are using it.
12. Return threshold to 600 when replacing test material with production
    segments of suitable duration. Explicitly migrate/reset the pilot catalog;
    do not silently replace files at paths referenced by saved progress.

Run `python -m unittest discover -s tests -v` in the repository. All tests need
the HA runtime for full coverage; local standard Python runs only engine tests.
CI includes HA for persistence, retained-event and API reconciliation checks.

Record each result as observed, simulated, or pending. Passing automated tests
is not evidence of successful hardware playback or cache replacement.
