"""The Python written inside the workflows (`python -c "..."`) is not read by ruff nor by the renaming tool: a name that was renamed breaks the workflow, and nothing says so until it runs
on GitHub (it happened to the catalogue check). This reads those one-liners and checks that the module attributes they call exist."""
import importlib
import re
import unittest
from pathlib import Path

import context  # noqa: F401

WORKFLOWS = Path(__file__).resolve().parent.parent / ".github" / "workflows"
ONE_LINER = re.compile(r"from lutin import (\w+)([^\n\"]*)")


class WorkflowsPython(unittest.TestCase):
    def test_every_module_attribute_a_workflow_calls_exists(self):
        checked = 0
        for workflow in sorted(WORKFLOWS.glob("*.yml")):
            for line in workflow.read_text(encoding="utf-8").splitlines():
                for module_name, rest in ONE_LINER.findall(line):
                    module = importlib.import_module("lutin." + module_name)
                    for attribute in re.findall(r"\b%s\.(\w+)" % module_name, rest):
                        checked += 1
                        self.assertTrue(hasattr(module, attribute), "%s calls %s.%s, which does not exist" % (workflow.name, module_name, attribute))
        self.assertGreater(checked, 0, "the check found nothing to check: the pattern no longer matches the workflows")


if __name__ == "__main__":
    unittest.main()
