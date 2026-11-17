"""Pure session state machine. Only desired progress is persisted by HA."""
from dataclasses import dataclass


@dataclass
class Session:
    uid: str
    index: int
    audio: str = ""
    playing: bool = False
    since: float | None = None
    done: bool = False


class Engine:
    def __init__(self, books, threshold, indices=None):
        self.books = books
        self.threshold = threshold
        self.indices = {uid: (indices or {}).get(uid, 0) for uid in books}
        self.sessions = {}
        self.armed = set()

    def reset(self):
        self.sessions.clear()
        self.armed.clear()

    def manual(self, uid, index):
        self.indices[uid] = index
        # Suppress all existing sessions for this tag, including on the other box.
        for session in self.sessions.values():
            if session.uid == uid:
                session.done = True
                session.since = None

    def event(self, box, kind, payload, now):
        session = self.sessions.get(box)
        if kind == "TagValid":
            uid = payload.upper()
            if not uid or uid.startswith("-"):
                self.armed.add(box)
                self.sessions.pop(box, None)
                return
            if uid not in self.books:
                self.armed.add(box)
                self.sessions.pop(box, None)
                return
            if box not in self.armed:
                return
            if session is None or session.uid != uid:
                self.sessions[box] = Session(uid, self.indices[uid])
            return
        if session is None:
            return
        if kind == "Playback":
            session.playing = payload == "ON"
            if not session.playing:
                # OFF may be a startup prelude; never permit it to re-arm a done session.
                session.since = None
        elif kind == "ContentAudioId":
            session.audio = payload
            if payload != str(self.books[session.uid]["segments"][session.index]["audio_id"]):
                session.since = None
        expected = str(self.books[session.uid]["segments"][session.index]["audio_id"])
        if session.playing and session.audio == expected and not session.done:
            if session.since is None:
                session.since = now

    def due(self, now):
        changed = []
        for session in self.sessions.values():
            if session.done or session.since is None or now - session.since < self.threshold:
                continue
            session.done = True
            uid = session.uid
            # Another box or a manual selection may already have changed the index.
            if self.indices[uid] != session.index:
                continue
            next_index = min(session.index + 1, len(self.books[uid]["segments"]) - 1)
            if next_index != session.index:
                self.manual(uid, next_index)
                changed.append(uid)
        return changed
