from types import SimpleNamespace

from hippo.brain import LLMBrain
from hippo.schema import Task


class FakeLLM:
    def __init__(self, text):
        self.text = text

    def chat(self, *args, **kwargs):
        return self.text

    def embed(self, texts):
        return [[0.0] for _ in texts]


def test_judge_step_rejects_task_specific_lesson():
    brain = LLMBrain(FakeLLM(
        '{"genuine": false, "lesson": "To find coffee makers, use the search box.", "key": "search"}'
    ), cfg={})
    task = Task(id="t", prompt="Browse coffee makers that are rated 5 stars.", scope="site:kohls")
    step = SimpleNamespace(obs="[textbox] Search by keyword or web id")

    out = brain.judge_step(task, step, "use search", "TYPE [1] [coffee maker]", False,
                           "[textbox] Search by keyword or web id -> TYPE: coffee maker")

    assert out["lesson"] is None


def test_extract_step_experiences_keeps_only_abstract_site_facts():
    brain = LLMBrain(FakeLLM(
        '{"facts": ['
        '{"statement": "To find events in New York City, select New York City, NY.", "key": "nyc"},'
        '{"statement": "The Search by city textbox is used to set the event location.", "key": "city-search"}'
        ']}'
    ), cfg={})
    task = Task(id="t", prompt="Find Hamilton tickets in New York on April.", scope="site:seatgeek")
    step = SimpleNamespace(obs="[searchbox] Search by city...")

    items = brain.extract_step_experiences(
        task,
        step,
        attempts=[{"thought": "x", "chosen": "CLICK [1]", "correct": False}],
        gold_repr="[searchbox] Search by city... -> TYPE: New York",
        mode="aggregate",
    )

    assert [it.statement for it in items] == [
        "The Search by city textbox is used to set the event location."
    ]
