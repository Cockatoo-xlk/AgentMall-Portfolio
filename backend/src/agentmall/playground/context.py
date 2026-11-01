from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from uuid import UUID


@dataclass
class CallScope:
    run_id: UUID
    thread_id: UUID
    user_id: UUID
    store_id: UUID
    ordinals: dict = field(default_factory=dict)

    def next(self, role, node):
        key = (role, node)
        self.ordinals[key] = self.ordinals.get(key, 0) + 1
        return self.ordinals[key]


current_scope = ContextVar("agentmall_playground_scope", default=None)


@contextmanager
def call_scope(scope):
    local = CallScope(scope.run_id, scope.thread_id, scope.user_id, scope.store_id)
    token = current_scope.set(local)
    try:
        yield
    finally:
        current_scope.reset(token)
