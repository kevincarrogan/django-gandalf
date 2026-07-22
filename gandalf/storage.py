import uuid


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

    def delete_run(self, run_id):
        """Forget the run entirely. Idempotent: deleting an unknown run is
        not an error, so callers need not check first."""
        gandalf_runs = self.request.session[self.SESSION_KEY]
        gandalf_runs.pop(str(run_id), None)
        self.request.session.modified = True
