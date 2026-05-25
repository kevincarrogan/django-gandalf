import uuid

from gandalf import tree


class WizardState:
    def __init__(self, entries=None):
        entries = entries if entries is not None else []
        self.entries = list(entries)

    def walk(self, tree_root, select_arm):
        submissions = []
        yield from self._walk_at(tree_root, self.entries, select_arm, submissions)

    def _walk_at(self, node, entries, select_arm, submissions):
        entry_iter = iter(entries)
        while node is not None:
            if isinstance(node, tree.Step):
                entry = next(entry_iter, None)
                stored = entry["step"] if entry is not None else None
                yield node, stored
                if stored is None:
                    return
                submissions.append(stored)
                node = node.next
            else:
                entry = next(entry_iter, None)
                sub_entries = entry["branch"] if entry is not None else []
                arm = select_arm(node, submissions)
                yield from self._walk_at(arm, sub_entries, select_arm, submissions)
                node = node.next

    def submissions(self):
        result = []
        self._collect(self.entries, result)
        return result

    def _collect(self, entries, result):
        for entry in entries:
            if "step" in entry:
                result.append(entry["step"])
            else:
                self._collect(entry["branch"], result)


class SessionStorage:
    SESSION_KEY = "gandalf_runs"

    def __init__(self, request):
        self.request = request

    def initialise_run(self):
        run_id = str(uuid.uuid4())
        gandalf_runs = self.request.session.setdefault(self.SESSION_KEY, {})
        gandalf_runs[run_id] = {}
        self.request.session.modified = True
        return run_id

    def retrieve_run(self, run_id):
        self.request.session[self.SESSION_KEY]
        self.request.session.modified = True
        return run_id

    def get_run_data(self, run_id):
        gandalf_runs = self.request.session[self.SESSION_KEY]
        return gandalf_runs[str(run_id)]

    def get_state(self, run_id):
        run_data = self.get_run_data(run_id)
        return run_data.get("state", [])

    def set_state(self, run_id, state):
        run_data = self.get_run_data(run_id)
        run_data["state"] = state
        self.request.session.modified = True
