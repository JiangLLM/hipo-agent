"""Offline tests for the v2 file-keyed notes mechanism."""
from hippo.swe.notes import FileNotes, NotesInjector, render_notes
from hippo.swe.rollout import _NotesDockerEnvironment


def _bank():
    n = FileNotes()
    n.add("django/db/models/sql/query.py", "Query.split_exclude",
          "creates Query(self.model) without copying annotations")
    n.add("django/forms/models.py", "ModelChoiceIterator.__iter__",
          "blank option controlled by field.empty_label")
    return n


def test_injector_fires_once_per_file():
    inj = NotesInjector(_bank())
    out = inj.peek("sed -n '100,150p' /testbed/django/db/models/sql/query.py")
    assert "split_exclude" in out and "query.py" in out
    assert inj.peek("grep foo django/db/models/sql/query.py") == ""   # second touch: silent
    out2 = inj.peek("cat django/forms/models.py")
    assert "empty_label" in out2


def test_injector_ignores_unknown_files_and_dedups_add():
    n = _bank()
    assert not n.add("django/forms/models.py", "x",
                     "Blank option controlled by field.empty_label")   # case-insensitive dup
    inj = NotesInjector(n)
    assert inj.peek("cat README.md setup.py") == ""


def test_env_wrapper_appends_to_observation():
    class FakeEnv:
        def execute(self, action, **kw):
            return {"output": "file contents here", "returncode": 0}
        def cleanup(self):
            self.cleaned = True
    env = _NotesDockerEnvironment(FakeEnv(), NotesInjector(_bank()))
    out = env.execute({"command": "head django/forms/models.py"})
    assert out["output"].startswith("file contents here")
    assert "[repo-notes]" in out["output"]
    env.cleanup()                                          # delegation works
    assert env._env.cleaned


def test_render_caps_length():
    n = FileNotes()
    for i in range(8):
        n.add("a.py", f"fn{i}", "x" * 400)
    text = render_notes(n.by_file["a.py"], "a.py", limit_chars=900)
    assert len(text) < 1000
