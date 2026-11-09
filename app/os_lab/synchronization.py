"""Producer-Consumer synchronization using a bounded buffer."""

from collections import deque
from threading import Condition


class BoundedBuffer:
    def __init__(self, capacity):
        if capacity <= 0:
            raise ValueError("Buffer capacity must be positive.")

        self.capacity = capacity
        self.buffer = deque()
        self.condition = Condition()
        self.log = []

    def produce(self, item):
        with self.condition:
            while len(self.buffer) >= self.capacity:
                self.condition.wait()

            self.buffer.append(item)
            self.log.append(f"Produced: {item}")
            self.condition.notify_all()

    def consume(self):
        with self.condition:
            while not self.buffer:
                self.condition.wait()

            item = self.buffer.popleft()
            self.log.append(f"Consumed: {item}")
            self.condition.notify_all()
            return item

    def get_status(self):
        with self.condition:
            return {
                "buffer": list(self.buffer),
                "capacity": self.capacity,
                "items": len(self.buffer),
                "log": list(self.log),
            }
