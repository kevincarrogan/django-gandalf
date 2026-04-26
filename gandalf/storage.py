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

    def get_submissions(self, run_id):
        run_data = self.get_run_data(run_id)
        return run_data.get("submissions", [])

    def set_submissions(self, run_id, submissions):
        run_data = self.get_run_data(run_id)
        run_data["submissions"] = submissions
        self.request.session.modified = True
