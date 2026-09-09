"""Single rollout (v1 = single-step action prediction)."""
from __future__ import annotations

from .schema import Step, Task, Trajectory


def rollout(task: Task, env, brain, memory_text: str, salt: str = "0") -> Trajectory:
    """`salt` (seed:index) makes trajectories diverge under uncertainty, reproducibly."""
    traj_id = f"{task.id}:{salt}"
    obs = env.initial_obs(task)
    thought, action, can_derive = brain.act(task, obs, memory_text, salt=salt)
    success = env.evaluate(task, action)
    step = Step(thought=thought, action=action, obs=obs)
    return Trajectory(
        task_id=task.id, traj_id=traj_id, steps=[step],
        final_answer=action, env_success=success,
        meta={"can_derive": can_derive},
    )
