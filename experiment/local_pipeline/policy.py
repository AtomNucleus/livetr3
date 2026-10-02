"""Small tentative-prefix policy and bounded latest-hypothesis mailbox."""
from collections import OrderedDict
from dataclasses import dataclass
import re
import threading


def words(text):
    return re.findall(r'\w+', text.casefold(), flags=re.UNICODE)


def prefix_length(a, b):
    count = 0
    for x, y in zip(a, b):
        if x != y:
            break
        count += 1
    return count


@dataclass(frozen=True)
class Span:
    line: int
    text: str
    final: bool
    committed: float
    acoustic_end: float


class CommitPolicy:
    """Repeat a prefix across two updates; translate at most once per second.

    A commit is tentative, not irreversible confidence. Translate the complete
    prefix (bounded by the recognizer's line), preserving within-line context.
    Final ASR always supersedes a tentative prefix, including negation changes.
    """
    def __init__(self, min_words=4, interval=1.0):
        self.min_words, self.interval = min_words, interval
        self.previous, self.sent, self.last = {}, {}, {}
        self.completed = set()

    def update(self, line, text, final, now, acoustic_end):
        if line in self.completed:
            return None
        tokens = text.split()
        previous = self.previous.get(line, [])
        self.previous[line] = tokens
        if final:
            self.completed.add(line)
            chosen = text.strip()
        else:
            # Split on whitespace for emission; use the same whitespace units
            # for stability to avoid punctuation changing token indices.
            count = prefix_length([s.casefold().strip('.,!?;:') for s in previous],
                                  [s.casefold().strip('.,!?;:') for s in tokens])
            if count < self.min_words or now - self.last.get(line, -1e9) < self.interval:
                return None
            chosen = ' '.join(tokens[:count])
            if chosen == self.sent.get(line):
                return None
        self.sent[line], self.last[line] = chosen, now
        return Span(line, chosen, final, now, acoustic_end)


class Mailbox:
    """One active generation plus at most four pending lines; coalesce by line.

    Finals cannot be evicted by partials. Overflow fails loudly instead of
    dropping an accepted line or accumulating an unbounded translation queue.
    """
    def __init__(self, capacity=4):
        self.capacity, self.pending = capacity, OrderedDict()
        self.cv, self.closed, self.peak, self.coalesced = threading.Condition(), False, 0, 0

    def put(self, span):
        with self.cv:
            if self.closed:
                raise RuntimeError('Translation mailbox is closed')
            old = self.pending.get(span.line)
            if old and old.final and not span.final:
                return
            if old is None and len(self.pending) >= self.capacity:
                raise RuntimeError('Translation queue overflow; replay aborted, events retained')
            self.coalesced += int(old is not None)
            self.pending[span.line] = span
            self.peak = max(self.peak, len(self.pending))
            self.cv.notify()

    def get(self):
        with self.cv:
            self.cv.wait_for(lambda: self.pending or self.closed)
            return self.pending.popitem(last=False)[1] if self.pending else None

    def close(self):
        with self.cv:
            self.closed = True
            self.cv.notify_all()
