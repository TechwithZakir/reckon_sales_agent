"""frappe.enqueue reserves some keyword names for itself; job arguments must not use them."""
import ast
import unittest
from pathlib import Path

APP = Path(__file__).parents[1] / "reckon_sales_agent"

# Keyword arguments frappe.enqueue consumes instead of passing to the job function.
RESERVED = {"method", "queue", "timeout", "event", "is_async", "job_name", "now", "enqueue_after_commit",
            "on_success", "on_failure", "at_front", "job_id", "deduplicate"}
CONTROL = {"queue", "timeout", "job_id", "deduplicate", "enqueue_after_commit", "at_front", "now", "is_async"}


class EnqueueContractTests(unittest.TestCase):
    def enqueue_calls(self):
        for path in APP.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "enqueue":
                    yield path, node

    def test_job_arguments_do_not_use_reserved_names(self):
        offenders = []
        for path, call in self.enqueue_calls():
            for keyword in call.keywords:
                if keyword.arg in RESERVED and keyword.arg not in CONTROL:
                    offenders.append(f"{path.relative_to(APP)}:{call.lineno} passes {keyword.arg}=")
        self.assertEqual(offenders, [], "frappe.enqueue would swallow these job arguments")

    def test_enqueued_functions_accept_the_arguments_sent(self):
        functions = {}
        for path in APP.rglob("*.py"):
            module = ".".join(path.relative_to(APP.parent).with_suffix("").parts)
            for node in ast.parse(path.read_text(encoding="utf-8")).body:
                if isinstance(node, ast.FunctionDef):
                    params = {a.arg for a in node.args.args + node.args.kwonlyargs}
                    functions[f"{module}.{node.name}"] = (params, node.args.kwarg is not None)
        for _path, call in self.enqueue_calls():
            target = call.args[0].value if call.args and isinstance(call.args[0], ast.Constant) else None
            if not target:
                continue
            params, has_kwargs = functions[target]
            sent = {k.arg for k in call.keywords if k.arg not in RESERVED}
            missing = sent - params
            self.assertTrue(has_kwargs or not missing, f"{target} does not accept {missing}")


if __name__ == "__main__":
    unittest.main()
